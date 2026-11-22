"""Observable CLI, model, and real Lean verification behavior."""

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from mathkernel.model import InputError, Plan, Task, Tile, compare, evaluate, read_json
from mathkernel.paths import scratch_directory
from mathkernel.verification import ROOT, checked_axioms, lake_environment, verify


EXAMPLE = ROOT / "examples" / "matmul-chain"


class ExampleCase(unittest.TestCase):
    def setUp(self):
        self.raw = read_json(EXAMPLE / "task.json")
        self.task = Task.parse(self.raw)
        self.candidate = Plan.parse(read_json(EXAMPLE / "candidate.json"))


class ModelTests(ExampleCase):
    def test_example_has_lower_time_and_known_resource_counts(self):
        result = compare(self.task, self.candidate)
        self.assertTrue(result["model_improvement"])
        self.assertEqual(result["baseline"]["flops"], 268435456)
        self.assertEqual(result["candidate"]["flops"], 16777216)
        self.assertEqual(result["baseline"]["hbm_bytes"], 21233664)
        self.assertEqual(result["candidate"]["hbm_bytes"], 1327104)
        self.assertEqual(result["model_speedup"], 16)
        self.assertEqual(result["verification_status"], "not_run")

    def test_schedule_reads_and_writes_for_one_scalar_output(self):
        raw = deepcopy(self.raw)
        raw["matrices"] = [{"name": name, "rows": 1, "cols": 1} for name in ("A", "B", "C")]
        raw["baseline"]["tile"] = {"m": 1, "n": 1, "k": 1}
        task = Task.parse(raw)
        result = evaluate(task, task.baseline)
        self.assertEqual(result["flops"], 4)
        self.assertEqual(result["hbm_bytes"], 24)
        self.assertEqual(result["peak_fast_memory_bytes"], 12)

    def test_capacity_is_a_constraint(self):
        task = replace(self.task, hardware=replace(self.task.hardware, fast_memory_bytes=49151))
        result = compare(task, self.candidate)
        self.assertFalse(result["model_improvement"])
        self.assertFalse(result["candidate"]["feasible"])

    def test_nondivisible_tiles_have_no_time_estimate(self):
        result = evaluate(self.task, Plan("right", Tile(3, 64, 64)))
        self.assertFalse(result["feasible"])
        self.assertIsNone(result["estimated_seconds"])

    def test_same_plan_is_not_a_strict_improvement(self):
        self.assertFalse(compare(self.task, self.task.baseline)["model_improvement"])

    def test_hardware_changes_preference_between_two_tiles(self):
        baseline = Plan("right", Tile(64, 64, 64))
        alternative = Plan("right", Tile(32, 32, 32))
        result = compare(replace(self.task, baseline=baseline), alternative)
        self.assertFalse(result["model_improvement"])
        constrained = replace(self.task, hardware=replace(self.task.hardware, fast_memory_bytes=12288), baseline=alternative)
        self.assertTrue(evaluate(constrained, alternative)["feasible"])
        self.assertFalse(evaluate(constrained, baseline)["feasible"])

    def test_compute_bandwidth_balance_changes_preferred_plan(self):
        candidate = Plan("right", Tile(1, 1, 1))
        fast_compute = compare(self.task, candidate)
        slow_hardware = replace(self.task.hardware, peak_flops_per_second=1000000000)
        slow_compute = compare(replace(self.task, hardware=slow_hardware), candidate)
        self.assertFalse(fast_compute["model_improvement"])
        self.assertTrue(slow_compute["model_improvement"])
        self.assertLess(slow_compute["candidate"]["flops"], slow_compute["baseline"]["flops"])
        self.assertGreater(slow_compute["candidate"]["hbm_bytes"], slow_compute["baseline"]["hbm_bytes"])

    def test_rejects_incompatible_dimensions_unknown_fields_and_booleans(self):
        changes = (("dimensions", 7), ("unknown", 1), ("boolean", True))
        for kind, value in changes:
            with self.subTest(kind=kind):
                raw = deepcopy(self.raw)
                if kind == "dimensions":
                    raw["matrices"][1]["rows"] = value
                elif kind == "unknown":
                    raw["hardware"]["bandwith"] = value
                else:
                    raw["hardware"]["fast_memory_bytes"] = value
                with self.assertRaises(InputError):
                    Task.parse(raw)

    def test_task_snapshot_can_be_replayed(self):
        self.assertEqual(Task.parse(self.task.to_json()), self.task)

    def test_axiom_check_rejects_unproved_or_additional_assumptions(self):
        for axiom in ("sorryAx", "Lean.trustCompiler", "invented_cost"):
            with self.subTest(axiom=axiom), self.assertRaises(ValueError):
                checked_axioms(f"'MathKernel.Instance.verified' depends on axioms: [{axiom}]")

    def test_cli_invalid_input_is_json_and_nonzero(self):
        completed = subprocess.run(
            [sys.executable, "tools/mathkernel.py", "inspect", "/nonexistent-mathkernel-task.json"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["verification_status"], "invalid_input")

    def test_missing_lean_is_reported_with_artifacts(self):
        completed = subprocess.run(
            [sys.executable, "tools/mathkernel.py", "verify", str(EXAMPLE / "task.json"), str(EXAMPLE / "candidate.json")],
            cwd=ROOT, env={**os.environ, "MATHKERNEL_LAKE": "/nonexistent-mathkernel-lake"},
            capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 1)
        result = json.loads(completed.stdout)
        self.assertEqual(result["verification_status"], "unavailable")
        self.assertTrue((Path(result["run_directory"]) / "result.json").is_file())


def lean_available():
    try:
        lake_environment()
        return True
    except FileNotFoundError:
        return False


@unittest.skipUnless(lean_available(), "Pinned Lean environment has not been installed")
class LeanIntegrationTests(ExampleCase):
    def test_real_lean_verifies_and_reports_can_be_replayed(self):
        result = verify(self.task, self.candidate)
        self.assertEqual(result["verification_status"], "verified", result.get("diagnostic"))
        run = Path(result["run_directory"])
        self.assertEqual(Task.parse(read_json(run / "task.json")), self.task)
        self.assertEqual(Plan.parse(read_json(run / "candidate.json")), self.candidate)
        self.assertTrue((run / "lean.log").read_text())

    def test_real_lean_rejects_equal_cost_and_infeasible_plan(self):
        for task, candidate in ((self.task, self.task.baseline), (replace(self.task, hardware=replace(self.task.hardware, fast_memory_bytes=49151)), self.candidate)):
            with self.subTest(candidate=candidate):
                result = verify(task, candidate)
                self.assertEqual(result["verification_status"], "proof_failed")

    def test_lean_rejects_semantically_wrong_reassociation_claim(self):
        lake, environment = lake_environment()
        scratch = scratch_directory()
        path = scratch / "WrongSemantics.lean"
        path.write_text("import MathKernel.Semantics\nexample (a b c : Matrix (Fin 2) (Fin 2) ℝ) : (a * b) * c = a * (c * b) := by\n  exact Matrix.mul_assoc a b c\n")
        completed = subprocess.run([lake, "env", "lean", str(path)], cwd=ROOT / "lean", env=environment, capture_output=True, text=True, timeout=120)
        self.assertNotEqual(completed.returncode, 0)

    def test_actual_lean_sorry_is_rejected_by_axiom_check(self):
        lake, environment = lake_environment()
        scratch = scratch_directory()
        path = scratch / "Unproved.lean"
        path.write_text("import MathKernel.Verification\nnamespace MathKernel.Instance\ntheorem verified : False := by sorry\n#print axioms verified\nend MathKernel.Instance\n")
        completed = subprocess.run([lake, "env", "lean", str(path)], cwd=ROOT / "lean", env=environment, capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0)
        with self.assertRaises(ValueError):
            checked_axioms(completed.stdout)


if __name__ == "__main__":
    unittest.main()
