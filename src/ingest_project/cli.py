"""Command line: ingest-project --config config.yaml --output outputs [--check-date 2026-04-01]."""

import argparse
import sys
from datetime import datetime

from . import __version__
from .config import ConfigError
from .pipeline import run
from .validation import RowError, parse_date


def date_argument(text: str) -> datetime:
    try:
        return parse_date(text, "iso")
    except RowError:
        raise argparse.ArgumentTypeError(f"'{text}' is not an ISO date, e.g. 2026-04-01") from None


def format_counts(counts: dict[str, int]) -> str:
    return f"{counts['total']} rows, {counts['clean']} clean, {counts['rejected']} rejected"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ingest-project", description="Check lab measurement files (synthetic demo)."
    )
    parser.add_argument("--config", required=True, help="path to config.yaml")
    parser.add_argument("--output", required=True, help="folder for the output files")
    parser.add_argument(
        "--check-date",
        type=date_argument,
        help=(
            "latest allowed date and time, ISO format; a date alone means 00:00 UTC "
            "(default: now). Set it to repeat a run exactly"
        ),
    )
    args = parser.parse_args(argv)

    try:
        summary = run(args.config, args.output, args.check_date)
    except (ConfigError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(f"ingest-project {__version__}, check date {summary['check_date']}")
    for lab, counts in summary["per_lab"].items():
        print(f"  {lab}: {format_counts(counts)}")
    print(f"  all labs: {format_counts(summary['counts'])}")
    for code, number in summary["per_error_code"].items():
        print(f"    {code}: {number}")
    print(f"files written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
