"""Public CLI boundaries and the Lean proof trust checks."""

import json
import subprocess
import sys
import unittest

from mathkernel.inputs import Hardware, InputError, fields, positive
from mathkernel.paths import ROOT
from mathkernel.verification import checked_axioms


class ToolTests(unittest.TestCase):
    def test_axiom_check_rejects_unproved_or_additional_assumptions(self):
        for axiom in ("sorryAx", "Lean.trustCompiler", "invented_cost"):
            with self.subTest(axiom=axiom), self.assertRaises(ValueError):
                checked_axioms(f"'MathKernel.Instance.verified' depends on axioms: [{axiom}]")

    def test_ambiguous_axiom_output_cannot_hide_an_untrusted_proof(self):
        output = "'MathKernel.Instance.verified' depends on axioms: []\n'MathKernel.Instance.verified' depends on axioms: [sorryAx]"
        with self.assertRaises(ValueError):
            checked_axioms(output)

    def test_old_top_level_commands_are_not_available(self):
        for command in ("inspect", "evaluate", "verify", "report", "roofline"):
            with self.subTest(command=command):
                completed = subprocess.run([sys.executable, "tools/mathkernel.py", command], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 2)
                self.assertIn("invalid choice", completed.stderr)

    def test_cli_invalid_input_is_json_and_nonzero(self):
        completed = subprocess.run([sys.executable, "tools/mathkernel.py", "task", "verify", "/nonexistent-mathkernel-task", "abc"],
                                   cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["verification_status"], "invalid_input")

    def test_resource_inputs_reject_booleans_and_unknown_fields(self):
        for value in (True, 0, -1, 1.5):
            with self.subTest(value=value), self.assertRaises(InputError):
                positive(value, "resource")
        with self.assertRaises(InputError):
            fields({"bandwith": 1}, ("bandwidth",))
        with self.assertRaises(InputError):
            Hardware.parse({"name": "test"})


if __name__ == "__main__":
    unittest.main()
