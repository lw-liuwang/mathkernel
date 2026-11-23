"""Task-local rules, composed proofs, replay diagnostics, and portable derivations."""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from mathkernel.inputs import InputError, read_json
from mathkernel.paths import ROOT, scratch_directory
from mathkernel.verification import lake_environment
from mathkernel.workflow import (accept_iteration, evaluate_iteration, export_iteration,
                                 list_rules, verify_iteration)
from mathkernel.workspace import (check_task, confirm_task, digest, load_task, session_status,
                                  write_json)


def lean_available():
    try:
        return Path(lake_environment()[0]).is_file()
    except FileNotFoundError:
        return False


class TransformationCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=scratch_directory())
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "task"
        shutil.copytree(ROOT / "tests" / "fixtures" / "transformations", self.root)

    def confirm(self):
        return confirm_task(self.root, "integration fixture", "Confirm synthetic rules, semantics, counts and task inputs for this test")

    def candidate(self, passes):
        path = self.root / "candidate.json"
        write_json(path, {"derivation": [{"rule": "set_passes", "arguments": {"passes": count}}
                                         for count in passes], "proof": "BaselineProof.lean"})
        return path

    def edit_task(self, change):
        task = read_json(self.root / "task.json")
        change(task)
        write_json(self.root / "task.json", task)

    def edit_model(self, old, new):
        path = self.root / "Model.lean"
        source = path.read_text()
        self.assertIn(old, source)
        path.write_text(source.replace(old, new))

    def state(self):
        task, _, revision = load_task(self.root)
        return session_status(self.root, revision, task["budget"])


class TransformationInputTests(TransformationCase):
    def test_invalid_candidate_shapes_do_not_start_exploration(self):
        self.confirm()
        invalid = [None, {}, {"plan": {}, "derivation": []}, {"derivation": []},
                   {"derivation": {}}, {"derivation": [None]},
                   {"derivation": [{"rule": " ", "arguments": {}}]},
                   {"derivation": [{"rule": "set_passes", "arguments": []}]},
                   {"derivation": [{"rule": "set_passes", "arguments": {}, "extra": 1}]},
                   {"derivation": [{"rule": "set_passes", "arguments": {"passes": 1.5}}]},
                   {"plan": {"passes": 2}, "proof": False},
                   {"plan": {"passes": 2}, "unknown": True}]
        path = self.root / "candidate.json"
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                write_json(path, candidate)
                with self.assertRaises(InputError):
                    evaluate_iteration(self.root, path)
        self.assertEqual(self.state()["iterations"], 0)
        self.assertIsNone(self.state()["started_at"])

    def test_changing_a_rule_invalidates_confirmation(self):
        self.confirm()
        self.edit_model('name := "set_passes"', 'name := "revised_rule"')
        self.assertEqual(check_task(self.root)["status"], "needs_confirmation")
        with self.assertRaises(InputError):
            evaluate_iteration(self.root, self.candidate([2]))


@unittest.skipUnless(lean_available(), "Pinned Lean is not installed")
class TransformationLeanTests(TransformationCase):
    def test_rules_cli_is_available_before_confirmation_without_spending_budget(self):
        completed = subprocess.run([sys.executable, "tools/mathkernel.py", "task", "rules", str(self.root)],
                                   cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual([rule["name"] for rule in result["rules"]], ["set_passes"])
        self.assertIn("passes", result["rules"][0]["description"])
        self.assertEqual(result["verification_status"], "not_run")
        self.assertEqual(check_task(self.root)["status"], "needs_confirmation")
        self.assertFalse((self.root / "session.json").exists())
        legacy = self.base / "direct"
        shutil.copytree(ROOT / "tests" / "fixtures" / "experiment", legacy)
        self.assertEqual(list_rules(legacy)["rules"], [])

    def test_duplicate_and_blank_rule_names_are_rejected(self):
        path = self.root / "Model.lean"
        original = path.read_text()
        for replacement in ('[setPassesRule, setPassesRule]', '[{ setPassesRule with name := " " }]'):
            with self.subTest(replacement=replacement):
                path.write_text(original.replace('[setPassesRule]', replacement))
                self.assertEqual(list_rules(self.root)["verification_status"], "invalid_rules")
                self.confirm()
                result = evaluate_iteration(self.root, self.candidate([2]))
                self.assertEqual(result["verification_status"], "invalid_rules")

    def test_multistep_composition_and_baseline_proof_reuse(self):
        self.confirm()
        proof = (self.root / "BaselineProof.lean").read_text()
        first = evaluate_iteration(self.root, self.candidate([8, 2]))
        self.assertEqual(first["verification_status"], "not_run")
        self.assertEqual(first["candidate_plan"], {"passes": 2, "strategy": "scheduled"})
        self.assertEqual(first["candidate"]["flops"], 2048)
        trace = first["derivation"]["trace"]
        self.assertEqual(trace[0]["before"]["passes"], 6)
        self.assertEqual(trace[0]["after"]["passes"], 8)
        self.assertEqual(trace[1]["before"], trace[0]["after"])
        self.assertEqual(trace[1]["after"], first["candidate_plan"])
        verified = verify_iteration(self.root, first["iteration"])
        self.assertEqual(verified["verification_status"], "verified", verified)
        second = evaluate_iteration(self.root, self.candidate([3]))
        verified = verify_iteration(self.root, second["iteration"])
        self.assertEqual(verified["verification_status"], "verified", verified)
        self.assertEqual((self.root / "BaselineProof.lean").read_text(), proof)
        self.assertNotIn("candidateCorrect", proof)
        self.assertEqual(self.state()["best_verified_iteration"], first["iteration"])

    def test_chain_selects_different_registered_rules(self):
        self.edit_model('[setPassesRule]',
                        '[{ setPassesRule with name := "first" }, { setPassesRule with name := "second" }]')
        self.confirm()
        path = self.candidate([8, 2])
        candidate = read_json(path)
        candidate["derivation"][0]["rule"] = "first"
        candidate["derivation"][1]["rule"] = "second"
        write_json(path, candidate)
        result = evaluate_iteration(self.root, path)
        self.assertEqual(result["candidate_plan"]["passes"], 2, result)
        self.assertEqual([entry["rule"] for entry in result["derivation"]["trace"]], ["first", "second"])
        verified = verify_iteration(self.root, result["iteration"])
        self.assertEqual(verified["verification_status"], "verified", verified)

    def test_derived_plan_preserves_nested_values(self):
        self.edit_model('("passes", .int count)])',
                        '("passes", .int count), ("metadata", .array [.null, .bool true, .int (-3), '
                        '.str "text", .object [("nested", .array [])]])])')
        self.confirm()
        result = evaluate_iteration(self.root, self.candidate([8, 2]))
        self.assertEqual(result["candidate_plan"]["metadata"], [None, True, -3, "text", {"nested": []}], result)
        verified = verify_iteration(self.root, result["iteration"])
        self.assertEqual(verified["verification_status"], "verified", verified)

    def test_rule_failures_retain_partial_trace_and_consume_attempts(self):
        self.confirm()
        cases = [("missing_rule", {}, "Unknown rule"),
                 ("set_passes", {"passes": 0}, "positive integer"),
                 ("set_passes", {"passes": "two"}, "integer argument"),
                 ("set_passes", {"passes": True}, "integer argument")]
        for rule, arguments, message in cases:
            with self.subTest(rule=rule, arguments=arguments):
                path = self.candidate([8, 2])
                candidate = read_json(path)
                candidate["derivation"][1] = {"rule": rule, "arguments": arguments}
                write_json(path, candidate)
                result = evaluate_iteration(self.root, path)
                self.assertEqual(result["verification_status"], "rule_failed", result)
                self.assertEqual(result["failed_step"], 2)
                self.assertIn(message, result["diagnostic"])
                saved = read_json(Path(result["iteration_directory"]) / "derivation.json")
                self.assertEqual(len(saved["trace"]), 1)
                self.assertEqual(saved["trace"][0]["after"]["passes"], 8)
        self.assertEqual(self.state()["iterations"], len(cases))

    def test_rule_input_preconditions_are_enforced(self):
        self.edit_task(lambda task: task["baseline"].update(passes=0))
        self.confirm()
        result = evaluate_iteration(self.root, self.candidate([2]))
        self.assertEqual(result["verification_status"], "rule_failed")
        self.assertEqual(result["failed_step"], 1)
        self.assertIn("input plan", result["diagnostic"])
        self.assertEqual(result["trace"], [])

    def test_invalid_rule_proof_fails_before_it_can_be_used(self):
        self.edit_model("def executePlan (_ : Value) (x : Nat) : Nat := x + 2",
                        'def executePlan (plan : Value) (x : Nat) : Nat := x + (plan.get "passes").nat')
        self.confirm()
        result = evaluate_iteration(self.root, self.candidate([2]))
        self.assertEqual(result["verification_status"], "proof_failed", result)
        self.assertEqual(self.state()["iterations"], 1)

    def test_composed_proof_rejects_sorry_and_additional_axioms(self):
        path = self.root / "Model.lean"
        original = path.read_text()
        for body, declaration in (("sorry", ""), ("exact False.elim inventedRule", "axiom inventedRule : False\n\n")):
            with self.subTest(body=body):
                path.write_text(original.replace("def setPassesRule", declaration + "def setPassesRule").replace("    rfl", "    " + body))
                self.confirm()
                result = evaluate_iteration(self.root, self.candidate([2]))
                if body == "sorry":
                    self.assertEqual(result["verification_status"], "proof_failed", result)
                    self.assertIn("sorry", result["diagnostic"])
                else:
                    self.assertEqual(result["verification_status"], "not_run", result)
                    verified = verify_iteration(self.root, result["iteration"])
                    self.assertEqual(verified["verification_status"], "untrusted_proof", verified)
                self.assertIsNone(self.state()["best_verified_iteration"])

    def test_composition_still_requires_a_baseline_correctness_proof(self):
        self.confirm()
        result = evaluate_iteration(self.root, self.candidate([2]))
        path = self.root / "BaselineProof.lean"
        path.write_text('import TaskInstance\nnamespace MathKernel.TaskProof\ntheorem baselineCorrect : True := True.intro\nend MathKernel.TaskProof\n')
        verified = verify_iteration(self.root, result["iteration"], proof_path=path)
        self.assertEqual(verified["verification_status"], "proof_failed", verified)

    def test_equivalence_does_not_bypass_cost_or_capacity_checks(self):
        self.confirm()
        for passes, expected_feasible in ((6, True), (1, False)):
            with self.subTest(passes=passes):
                result = evaluate_iteration(self.root, self.candidate([passes]))
                self.assertEqual(result["candidate"]["feasible"], expected_feasible)
                self.assertFalse(result["model_improvement"])
                verified = verify_iteration(self.root, result["iteration"])
                self.assertEqual(verified["verification_status"], "proof_failed", verified)
                self.assertEqual(accept_iteration(self.root, result["iteration"])["acceptance_status"], "rejected")

    def test_changed_chain_trace_and_final_plan_cannot_reuse_evidence(self):
        self.confirm()
        result = evaluate_iteration(self.root, self.candidate([8, 2]))
        directory = Path(result["iteration_directory"])
        for name, change in (("derivation.json", lambda data: data["steps"][0]["arguments"].update(passes=7)),
                             ("derivation.json", lambda data: data["trace"][0]["after"].update(passes=7)),
                             ("plan.json", lambda data: data.update(passes=3))):
            with self.subTest(name=name):
                path = directory / name
                original = path.read_text()
                data = read_json(path)
                change(data)
                write_json(path, data)
                with self.assertRaises(InputError):
                    accept_iteration(self.root, result["iteration"])
                self.assertEqual(read_json(self.root / "acceptance.json")["acceptance_status"], "rejected")
                path.write_text(original)
        comparison_path = directory / "comparison.json"
        comparison = read_json(comparison_path)
        comparison["derivation"]["trace"][0]["after_formula"] = "forged formula"
        write_json(comparison_path, comparison)
        accepted = accept_iteration(self.root, result["iteration"])
        self.assertEqual(accepted["verification_status"], "stale_evaluation")
        self.assertEqual(accepted["acceptance_status"], "rejected")

    def test_failed_rule_exhausts_iteration_budget(self):
        self.edit_task(lambda task: task["budget"].update(max_iterations=1))
        self.confirm()
        result = evaluate_iteration(self.root, self.candidate([0]))
        self.assertEqual(result["verification_status"], "rule_failed")
        result = evaluate_iteration(self.root, self.candidate([2]))
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertEqual(self.state()["iterations"], 1)

    def test_replay_checks_saved_plan_and_trace_beyond_digests(self):
        self.confirm()
        result = evaluate_iteration(self.root, self.candidate([8, 2]))
        directory = Path(result["iteration_directory"])
        record_path = directory / "iteration.json"
        original_record = record_path.read_text()
        cases = [("derivation.json", "derivation_digest", "saved derivation",
                  lambda data: data["trace"][0]["after"].update(passes=7)),
                 ("plan.json", "plan_digest", "saved plan", lambda data: data.update(passes=3))]
        for name, digest_key, message, change in cases:
            with self.subTest(name=name):
                path = directory / name
                original = path.read_text()
                data = read_json(path)
                change(data)
                write_json(path, data)
                record = read_json(record_path)
                record[digest_key] = digest(data)
                write_json(record_path, record)
                accepted = accept_iteration(self.root, result["iteration"])
                self.assertEqual(accepted["verification_status"], "stale_evaluation")
                self.assertEqual(accepted["acceptance_status"], "rejected")
                self.assertIn(message, accepted["diagnostic"])
                path.write_text(original)
                record_path.write_text(original_record)
        verified = verify_iteration(self.root, result["iteration"])
        self.assertEqual(verified["verification_status"], "verified", verified)

    def test_timeout_retains_derivation_and_consumes_attempt(self):
        self.confirm()
        result = evaluate_iteration(self.root, self.candidate([2]), timeout=0.001)
        self.assertEqual(result["verification_status"], "timeout")
        self.assertTrue((Path(result["iteration_directory"]) / "derivation.json").is_file())
        self.assertEqual(self.state()["iterations"], 1)

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Plotting environment is not installed")
    def test_final_acceptance_is_allowed_after_exploration_time_expires(self):
        self.confirm()
        result = evaluate_iteration(self.root, self.candidate([2]))
        session = read_json(self.root / "session.json")
        session["started_at"] = (datetime.now(timezone.utc) - timedelta(seconds=601)).isoformat()
        write_json(self.root / "session.json", session)
        verified = verify_iteration(self.root, result["iteration"])
        self.assertEqual(verified["verification_status"], "timeout", verified)
        accepted = accept_iteration(self.root, result["iteration"], stop_reason="budget_exhausted")
        self.assertEqual(accepted["acceptance_status"], "accepted", accepted)

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Plotting environment is not installed")
    def test_chain_export_and_replay_without_source_workspace(self):
        self.confirm()
        result = evaluate_iteration(self.root, self.candidate([8, 2]))
        output = self.base / "bundle"
        exported = export_iteration(self.root, result["iteration"], output)
        self.assertEqual(exported["acceptance_status"], "accepted", exported)
        moved = self.base / "moved"
        output.rename(moved)
        shutil.rmtree(self.root)
        replayed = accept_iteration(moved)
        self.assertEqual(replayed["acceptance_status"], "accepted", replayed)
        artifacts = Path(replayed["artifact_directory"])
        scheme = read_json(artifacts / "scheme.json")
        self.assertEqual(len(scheme["derivation"]["trace"]), 2)
        self.assertEqual(scheme["derivation"]["trace"][-1]["after"], scheme["candidate"])
        self.assertIn("set_passes", (artifacts / "report.md").read_text())
        self.assertTrue((artifacts / "roofline.png").read_bytes().startswith(b"\x89PNG"))
        derivation_path = moved / "iterations" / result["iteration"] / "derivation.json"
        derivation_path.write_text("{}\n")
        with self.assertRaises(InputError):
            accept_iteration(moved)
        self.assertEqual(read_json(moved / "acceptance.json")["acceptance_status"], "rejected")


if __name__ == "__main__":
    unittest.main()
