"""Task authorization, revisions, actual Lean acceptance, and portable bundles."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mathkernel.model import InputError, read_json
from mathkernel.paths import ROOT, scratch_directory
from mathkernel.verification import lake_environment
from mathkernel.workflow import (accept_iteration, evaluate_iteration, export_iteration,
                                 verify_iteration)
from mathkernel.workspace import (check_task, confirm_task, initialize, load_task,
                                  session_status, write_json)


def lean_available():
    try:
        lake, environment = lake_environment()
        return Path(lake).is_file()
    except FileNotFoundError:
        return False


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=scratch_directory())
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "task"
        initialize(self.root, "matmul-chain")

    def confirm(self):
        return confirm_task(self.root, "integration fixture", "Confirm synthetic model, assumptions, target and budget for this test")

    def edit(self, change):
        task = read_json(self.root / "task.json")
        change(task)
        write_json(self.root / "task.json", task)

    def candidate(self, plan):
        path = self.base / "candidate.json"
        write_json(path, {"plan": plan})
        return path


class TaskPreparationTests(WorkspaceCase):
    def test_empty_task_lists_actionable_missing_information(self):
        root = self.base / "empty"
        initialize(root)
        result = check_task(root)
        self.assertEqual(result["status"], "needs_information")
        missing = {item["field"] for item in result["issues"]}
        self.assertTrue({"specification.inputs", "hardware.fast_memory_bytes", "objective.metric", "budget"} <= missing)
        self.assertFalse(result["ready"])

    def test_complete_task_requires_confirmation_and_changes_invalidate_it(self):
        self.assertEqual(check_task(self.root)["status"], "needs_confirmation")
        self.assertTrue(self.confirm()["ready"])
        self.edit(lambda task: task["budget"].update(max_iterations=20))
        self.assertEqual(check_task(self.root)["status"], "needs_confirmation")
        with self.assertRaises(InputError):
            evaluate_iteration(self.root, self.root / "candidate.json")

    def test_supplement_requires_authorization_then_separate_confirmation(self):
        self.edit(lambda task: task["supplements"].append({"scope": "hardware", "content": "synthetic device", "basis": "test input"}))
        result = check_task(self.root)
        self.assertEqual(result["status"], "needs_information")
        self.assertIn("supplements[0].authorization", {item["field"] for item in result["issues"]})
        self.edit(lambda task: task["supplements"][0].update(authorized_by="user", authorization="Use synthetic parameters for this example"))
        self.assertEqual(check_task(self.root)["status"], "needs_confirmation")
        self.assertTrue(self.confirm()["ready"])

    def test_custom_model_change_invalidates_review(self):
        root = self.base / "fusion"
        initialize(root, "fusion")
        confirm_task(root, "test", "Confirm custom definition")
        path = root / "model" / "Model.lean"
        path.write_text(path.read_text() + "\n-- model revision\n")
        self.assertEqual(check_task(root)["status"], "needs_confirmation")

    def test_invalid_shapes_types_goals_and_paths_produce_diagnostics(self):
        original = read_json(self.root / "task.json")
        for field, value in (("hardware", []), ("model", {"kind": []}), ("objective", {"metric": []}),
                             ("specification", []), ("budget", {"max_iterations": True}),
                             ("objective", {"metric": "flops", "minimum_reduction": {"numerator": 1, "denominator": 0}})):
            with self.subTest(field=field, value=value):
                task = deepcopy(original)
                task[field] = value
                write_json(self.root / "task.json", task)
                self.assertFalse(check_task(self.root)["ready"])
        write_json(self.root / "task.json", original)
        self.edit(lambda task: task["model"].update(definition="../outside.lean"))
        self.assertEqual(check_task(self.root)["status"], "invalid_task")

    def test_incomplete_review_cannot_confirm_a_task(self):
        self.confirm()
        review = read_json(self.root / "review.json")
        review.pop("confirmation")
        write_json(self.root / "review.json", review)
        self.assertEqual(check_task(self.root)["status"], "needs_confirmation")
        write_json(self.root / "review.json", [])
        self.assertEqual(check_task(self.root)["status"], "needs_confirmation")

    def test_absolute_model_paths_are_not_portable_task_inputs(self):
        self.edit(lambda task: task["model"].update(definition=str(self.root / "model" / "task.json")))
        self.assertEqual(check_task(self.root)["status"], "invalid_task")

    def test_budget_counts_failures_and_elapsed_time(self):
        self.confirm()
        task, definition, revision = load_task(self.root)
        directory = self.root / "iterations" / "failed"
        directory.mkdir(parents=True)
        write_json(directory / "iteration.json", {"id": "failed", "revision": revision, "verification_status": "proof_failed"})
        self.assertTrue(session_status(self.root, revision, {"max_iterations": 1})["budget_exhausted"])
        write_json(self.root / "session.json", {"revision": revision, "started_at": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()})
        state = session_status(self.root, revision, {"max_seconds": 1})
        self.assertTrue(state["budget_exhausted"])
        self.assertIsNone(state["best_verified_iteration"])

    def test_cli_check_is_json_and_exits_nonzero_until_confirmed(self):
        completed = subprocess.run([sys.executable, "tools/mathkernel.py", "task", "check", str(self.root)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "needs_confirmation")

    def test_missing_lean_is_preserved_as_a_failed_attempt(self):
        self.confirm()
        with patch.dict(os.environ, {"MATHKERNEL_LAKE": "/nonexistent-mathkernel-lake"}):
            result = evaluate_iteration(self.root, self.root / "candidate.json")
        self.assertEqual(result["verification_status"], "unavailable")
        self.assertTrue((Path(result["iteration_directory"]) / "evaluation" / "lean.log").is_file())
        task, definition, revision = load_task(self.root)
        self.assertEqual(session_status(self.root, revision, task["budget"])["iterations"], 1)


@unittest.skipUnless(lean_available(), "Pinned Lean is not installed")
class WorkflowLeanTests(WorkspaceCase):
    def test_failed_candidate_then_verified_improvement_and_best_result(self):
        self.confirm()
        task = read_json(self.root / "task.json")
        same = evaluate_iteration(self.root, self.candidate(task["baseline"]))
        self.assertFalse(same["model_improvement"])
        self.assertEqual(verify_iteration(self.root, same["iteration"])["verification_status"], "proof_failed")
        better = evaluate_iteration(self.root, self.root / "candidate.json")
        self.assertEqual(verify_iteration(self.root, better["iteration"])["verification_status"], "verified")
        task, definition, revision = load_task(self.root)
        state = session_status(self.root, revision, task["budget"])
        self.assertEqual(state["iterations"], 2)
        self.assertEqual(state["best_verified_iteration"], better["iteration"])

    def test_minimum_reduction_and_constraints_are_proved(self):
        self.edit(lambda task: task["objective"]["minimum_reduction"].update(numerator=99, denominator=100))
        self.confirm()
        result = evaluate_iteration(self.root, self.root / "candidate.json")
        self.assertFalse(result["model_improvement"])
        self.assertEqual(verify_iteration(self.root, result["iteration"])["verification_status"], "proof_failed")
        self.edit(lambda task: task["objective"]["minimum_reduction"].update(numerator=0, denominator=1))
        self.edit(lambda task: task["constraints"].update(flops=1))
        self.confirm()
        result = evaluate_iteration(self.root, self.root / "candidate.json")
        self.assertFalse(result["candidate"]["feasible"])
        self.assertEqual(verify_iteration(self.root, result["iteration"])["verification_status"], "proof_failed")

    def test_changed_task_or_candidate_cannot_reuse_a_proof(self):
        self.confirm()
        result = evaluate_iteration(self.root, self.root / "candidate.json")
        self.edit(lambda task: task.update(name="changed"))
        self.confirm()
        with self.assertRaises(InputError):
            verify_iteration(self.root, result["iteration"])

    def test_forged_report_is_rejected_before_acceptance(self):
        self.confirm()
        result = evaluate_iteration(self.root, self.root / "candidate.json")
        path = Path(result["iteration_directory"]) / "comparison.json"
        comparison = read_json(path)
        comparison["candidate"]["hbm_bytes"] = 1
        write_json(path, comparison)
        accepted = accept_iteration(self.root, result["iteration"])
        self.assertEqual(accepted["acceptance_status"], "rejected")
        self.assertEqual(accepted["verification_status"], "stale_evaluation")

    def test_new_kernel_rejects_sorry_and_missing_semantic_obligations(self):
        root = self.base / "fusion"
        initialize(root, "fusion")
        confirm_task(root, "test", "Confirm exact-real fusion task and model")
        result = evaluate_iteration(root, root / "candidate.json")
        verified = verify_iteration(root, result["iteration"])
        self.assertEqual(verified["verification_status"], "verified")
        proof = root / "Proof.lean"
        original = proof.read_text()
        proof.write_text(original.replace("  rfl", "  sorry"))
        rejected = verify_iteration(root, result["iteration"], proof_path=proof)
        self.assertEqual(rejected["verification_status"], "untrusted_proof")
        task, definition, revision = load_task(root)
        self.assertEqual(session_status(root, revision, task["budget"])["best_verified_iteration"], result["iteration"])
        proof.write_text('import TaskInstance\nnamespace MathKernel.TaskProof\ntheorem baselineCorrect : True := True.intro\ntheorem candidateCorrect : True := True.intro\nend MathKernel.TaskProof\n')
        rejected = verify_iteration(root, result["iteration"], proof_path=proof)
        self.assertEqual(rejected["verification_status"], "proof_failed")

    def test_timeout_is_not_verified(self):
        self.confirm()
        result = evaluate_iteration(self.root, self.root / "candidate.json", timeout=0.001)
        self.assertEqual(result["verification_status"], "timeout")

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Plotting environment is not installed")
    def test_matrix_and_new_fusion_kernel_export_and_replay_independently(self):
        for example in ("matmul-chain", "fusion"):
            with self.subTest(example=example):
                root = self.base / example
                initialize(root, example)
                confirm_task(root, "test", "Confirm synthetic task and approved model")
                result = evaluate_iteration(root, root / "candidate.json")
                self.assertTrue(result["model_improvement"])
                output = self.base / f"{example}-bundle"
                exported = export_iteration(root, result["iteration"], output)
                self.assertEqual(exported["acceptance_status"], "accepted", exported)
                moved = self.base / f"{example}-moved"
                output.rename(moved)
                # Removing the source workspace must not affect bundle replay.
                shutil.rmtree(root)
                replayed = accept_iteration(moved)
                self.assertEqual(replayed["acceptance_status"], "accepted", replayed)
                artifacts = Path(replayed["artifact_directory"])
                self.assertIn("pseudocode", read_json(artifacts / "scheme.json"))
                self.assertTrue((artifacts / "roofline.png").read_bytes().startswith(b"\x89PNG"))
                (artifacts / "roofline.png").write_bytes(b"\x89PNG\r\n\x1a\nwrong image")
                with self.assertRaises(InputError):
                    accept_iteration(moved)
                self.assertEqual(read_json(moved / "acceptance.json")["acceptance_status"], "rejected")


if __name__ == "__main__":
    unittest.main()
