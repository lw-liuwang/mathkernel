"""JSON command interface for shell-capable agents."""

import argparse
import json
from .model import MODEL, InputError, Plan, Task, compare, evaluate, read_json
from .verification import ROOT, render_report, verify


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Read a task and evaluate its baseline")
    inspect.add_argument("task")
    for name in ("evaluate", "verify", "roofline"):
        command = commands.add_parser(name)
        command.add_argument("task")
        command.add_argument("candidate")
        if name == "verify":
            command.add_argument("--timeout", type=int, default=120, help="Timeout in seconds for each Lean command")
        if name == "roofline":
            command.add_argument("--output", required=True, help="Output prefix for a PNG image and JSON point data")
    report = commands.add_parser("report", help="Render a saved verification result as Markdown")
    report.add_argument("result")
    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            result = read_json(args.result)
            print(render_report(result), end="")
            return 0
        raw_task = read_json(args.task)
        task = Task.parse(raw_task)
        if args.command == "inspect":
            result = {
                "task": raw_task, "baseline": evaluate(task, task.baseline),
                "supported_model": MODEL, "semantics": "exact real matrices",
                "supported_plans": ["(AB)C", "A(BC)"],
                "constraints": ["positive dimensions and tile sizes", "exactly divisible tiles", "three tile buffers fit fast memory"],
                "skill": str(ROOT / "skills" / "optimize-mathkernel" / "SKILL.md"),
            }
        else:
            candidate = Plan.parse(read_json(args.candidate))
            if args.command == "verify":
                if args.timeout <= 0:
                    raise InputError("timeout must be positive")
                result = verify(task, candidate, args.timeout)
            elif args.command == "roofline":
                from .roofline import plot_roofline
                result = plot_roofline(task, candidate, args.output)
            else:
                result = compare(task, candidate)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if args.command == "verify":
            return 0 if result["verification_status"] == "verified" else 1
        return 0
    except (InputError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error), "verification_status": "invalid_input"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
