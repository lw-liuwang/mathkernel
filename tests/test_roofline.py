"""Roofline coordinates, aggregation, and exported plot artifacts."""

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

from mathkernel.model import InputError, Plan, Task, read_json
from mathkernel.paths import scratch_directory
from mathkernel.roofline import roofline_data
from mathkernel.verification import ROOT


class RooflineTests(unittest.TestCase):
    def setUp(self):
        example = ROOT / "examples" / "matmul-chain"
        self.task = Task.parse(read_json(example / "task.json"))
        self.candidate = Plan.parse(read_json(example / "candidate.json"))

    def test_example_plans_share_positions_but_have_different_times(self):
        data = roofline_data(self.task, self.candidate)
        totals = [point for point in data["points"] if point["kind"] == "total"]
        self.assertEqual(data["ridge_intensity_flops_per_byte"], 100)
        self.assertAlmostEqual(totals[0]["intensity_flops_per_byte"], 12.641975308641975)
        self.assertEqual(totals[0]["intensity_flops_per_byte"], totals[1]["intensity_flops_per_byte"])
        self.assertEqual(totals[0]["performance_tflops"], totals[1]["performance_tflops"])
        self.assertEqual(totals[0]["estimated_microseconds"], 21.233664)
        self.assertEqual(totals[1]["estimated_microseconds"], 1.327104)
        self.assertEqual(data["model_speedup"], 16)

    def test_mixed_bottlenecks_put_aggregate_below_roof(self):
        task = replace(self.task, hardware=replace(self.task.hardware, peak_flops_per_second=12000000000000))
        data = roofline_data(task, self.candidate)
        for total in (point for point in data["points"] if point["kind"] == "total"):
            self.assertGreater(total["intensity_flops_per_byte"], 12)
            self.assertLess(total["performance_tflops"], 12)

    def test_infeasible_plan_has_no_roofline_point(self):
        task = replace(self.task, hardware=replace(self.task.hardware, fast_memory_bytes=1))
        with self.assertRaises(InputError):
            roofline_data(task, self.candidate)

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Plotting environment is not installed")
    def test_cli_exports_png_and_point_data(self):
        prefix = scratch_directory() / "roofline-test" / "plot"
        completed = subprocess.run([
            sys.executable, "tools/mathkernel.py", "roofline",
            "examples/matmul-chain/task.json", "examples/matmul-chain/candidate.json",
            "--output", str(prefix),
        ], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        result = json.loads(completed.stdout)
        paths = {name: Path(value) for name, value in result["artifacts"].items()}
        self.assertEqual(set(paths), {"png", "json"})
        self.assertEqual(paths["png"].read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(len(json.loads(paths["json"].read_text())["points"]), 6)


if __name__ == "__main__":
    unittest.main()
