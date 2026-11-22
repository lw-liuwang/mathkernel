"""Render experiment resource reports without a kernel-specific model."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from mathkernel.inputs import read_json
from mathkernel.paths import ROOT, scratch_directory
from mathkernel.roofline import plot_roofline_data
from mathkernel.workflow import compare_evaluation, roofline_points


class RooflineTests(unittest.TestCase):
    def setUp(self):
        self.task = read_json(ROOT / "tests" / "fixtures" / "experiment" / "task.json")
        self.before = {"operations": [{"flops": 16, "hbm_bytes": 16, "peak_fast_memory_bytes": 8}],
                       "feasible": True, "formula": "before", "pseudocode": "reference"}
        self.after = {"operations": [{"flops": 8, "hbm_bytes": 8, "peak_fast_memory_bytes": 8}],
                      "feasible": True, "formula": "after", "pseudocode": "candidate"}

    def data(self):
        return roofline_points(compare_evaluation({"baseline": self.before, "candidate": self.after}, self.task, {"strategy": "candidate"}))

    def test_proportional_costs_keep_positions_while_time_improves(self):
        data = self.data()
        totals = [point for point in data["points"] if point["kind"] == "total"]
        self.assertEqual(totals[0]["intensity_flops_per_byte"], totals[1]["intensity_flops_per_byte"])
        self.assertEqual(totals[0]["performance_tflops"], totals[1]["performance_tflops"])
        self.assertEqual(totals[0]["estimated_microseconds"], 2 * totals[1]["estimated_microseconds"])
        self.assertEqual(data["model_speedup"], 2)

    def test_sequential_mixed_bottlenecks_keep_aggregate_below_roof(self):
        self.task["hardware"]["peak_flops_per_second"] = 1000
        self.before["operations"] = [{"flops": 100, "hbm_bytes": 1, "peak_fast_memory_bytes": 8},
                                     {"flops": 1, "hbm_bytes": 100, "peak_fast_memory_bytes": 8}]
        data = self.data()
        total = next(point for point in data["points"] if point["plan"] == "baseline" and point["kind"] == "total")
        self.assertEqual(total["intensity_flops_per_byte"], 1)
        self.assertLess(total["performance_tflops"], 1000 / 10**12)

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Plotting environment is not installed")
    def test_memory_only_scheme_keeps_time_comparison_without_log_zero(self):
        self.before["operations"][0]["flops"] = 0
        self.after["operations"][0]["flops"] = 0
        data = self.data()
        self.assertTrue(all(point["intensity_flops_per_byte"] is None for point in data["points"]))
        with tempfile.TemporaryDirectory(dir=scratch_directory()) as scratch:
            result = plot_roofline_data(data, Path(scratch) / "copy")
            self.assertTrue(Path(result["artifacts"]["png"]).read_bytes().startswith(b"\x89PNG"))

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Plotting environment is not installed")
    def test_exported_png_and_points_match_the_experiment(self):
        data = self.data()
        with tempfile.TemporaryDirectory(dir=scratch_directory()) as scratch:
            result = plot_roofline_data(data, Path(scratch) / "plot")
            paths = {name: Path(value) for name, value in result["artifacts"].items()}
            self.assertEqual(set(paths), {"png", "json"})
            self.assertEqual(paths["png"].read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(json.loads(paths["json"].read_text()), data)


if __name__ == "__main__":
    unittest.main()
