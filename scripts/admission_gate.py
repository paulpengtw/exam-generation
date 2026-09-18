"""CLI for operating the generation admission gate.

Usage examples:
    python scripts/admission_gate.py pause --reason "release preparation" --by operator
    python scripts/admission_gate.py open --by operator
    python scripts/admission_gate.py status
    python scripts/admission_gate.py status --require PAUSED
"""

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path

_DEFAULT_STATE_DIR = Path(os.environ.get("GATEWAY_STATE_DIR", "/var/lib/examgen-gate"))


def _get_state_dir(args: argparse.Namespace) -> Path:
    return Path(args.state_dir)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="admission_gate.py",
        description="Operate the generation admission gate.",
    )
    parser.add_argument(
        "--state-dir",
        default=str(_DEFAULT_STATE_DIR),
        help="Path to the state directory (default: $GATEWAY_STATE_DIR or /var/lib/examgen-gate)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # pause sub-command
    pause_p = sub.add_parser("pause", help="Pause new generation.")
    pause_p.add_argument("--reason", default=None, help="Human-readable reason for the pause.")
    pause_p.add_argument("--by", default=None, dest="changed_by", help="Actor name.")

    # open sub-command
    open_p = sub.add_parser("open", help="Open the gate to allow new generation.")
    open_p.add_argument("--by", default=None, dest="changed_by", help="Actor name.")

    # status sub-command
    status_p = sub.add_parser("status", help="Print current admission state as JSON.")
    status_p.add_argument(
        "--require",
        choices=["PAUSED", "OPEN"],
        default=None,
        help="Exit 0 if the gate matches, 3 otherwise.",
    )

    args = parser.parse_args(argv)
    state_dir = _get_state_dir(args)

    from gateway.state import open_gate, pause, read_state

    if args.command == "pause":
        result = pause(state_dir, reason=args.reason, changed_by=args.changed_by)
    elif args.command == "open":
        result = open_gate(state_dir, changed_by=args.changed_by)
    elif args.command == "status":
        result = read_state(state_dir)
        if args.require is not None:
            required_state = args.require.lower()
            print(json.dumps(dataclasses.asdict(result), ensure_ascii=False))
            if result.state != required_state:
                sys.exit(3)
            return
    else:
        parser.error(f"Unknown command: {args.command}")

    print(json.dumps(dataclasses.asdict(result), ensure_ascii=False))


if __name__ == "__main__":
    main()
