"""JSON command interface for shell-capable agents."""

import argparse
import json
from .inputs import InputError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Check Python, Lean, the proof contract and PNG export")
    doctor.add_argument("--timeout", type=int, default=120)
    workflow = commands.add_parser("task", help="Prepare, iterate, accept and export a mathematical experiment")
    actions = workflow.add_subparsers(dest="action", required=True)
    for name in ("init", "check", "confirm", "status", "evaluate", "verify", "accept", "export"):
        action = actions.add_parser(name)
        action.add_argument("directory")
        if name == "confirm":
            action.add_argument("--by", required=True, dest="confirmed_by")
            action.add_argument("--note", required=True)
        if name == "evaluate":
            action.add_argument("candidate")
        if name in ("verify", "export"):
            action.add_argument("iteration")
        if name == "accept":
            action.add_argument("iteration", nargs="?")
        if name == "verify":
            action.add_argument("--proof")
        if name == "export":
            action.add_argument("--output", required=True)
        if name in ("evaluate", "verify", "accept", "export"):
            action.add_argument("--timeout", type=int, default=120)
        if name in ("accept", "export"):
            action.add_argument("--stop-reason", choices=("target_met", "budget_exhausted", "user_stopped"), default="target_met")
    args = parser.parse_args(argv)
    try:
        if hasattr(args, "timeout") and args.timeout <= 0:
            raise InputError("timeout must be positive")
        if args.command == "doctor":
            from .doctor import doctor as check_installation
            result = check_installation(args.timeout)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["ready"] else 1
        return task_command(args)
    except (InputError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"error": str(error), "verification_status": "invalid_input"}, ensure_ascii=False))
        return 2


def task_command(args):
    from .workflow import accept_iteration, evaluate_iteration, export_iteration, verify_iteration
    from .workspace import check_task, confirm_task, initialize, require_ready, session_status
    if args.action == "init":
        result = initialize(args.directory)
    elif args.action == "check":
        result = check_task(args.directory)
    elif args.action == "confirm":
        result = confirm_task(args.directory, args.confirmed_by, args.note)
    elif args.action == "status":
        task, definition, revision = require_ready(args.directory)
        result = session_status(args.directory, revision, task["budget"])
    elif args.action == "evaluate":
        result = evaluate_iteration(args.directory, args.candidate, args.timeout)
    elif args.action == "verify":
        result = verify_iteration(args.directory, args.iteration, args.timeout, args.proof)
    elif args.action == "accept":
        result = accept_iteration(args.directory, args.iteration, args.timeout, args.stop_reason)
    else:
        result = export_iteration(args.directory, args.iteration, args.output, args.timeout, args.stop_reason)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.action == "init":
        return 0
    if "acceptance_status" in result:
        return 0 if result["acceptance_status"] == "accepted" else 1
    if "ready" in result:
        return 0 if result["ready"] else 1
    if result.get("status") == "budget_exhausted":
        return 1
    return 0 if result.get("verification_status", "not_run") in ("not_run", "verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
