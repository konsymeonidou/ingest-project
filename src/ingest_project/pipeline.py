"""Run the validation step for every lab and write the output files."""

import csv
import hashlib
import io
import json
import platform
from collections import Counter
from dataclasses import asdict, fields
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from . import __version__
from .config import Config, load_config, read_file
from .validation import Measurement, RejectedRow, check_file

CLEAN_FILE = "clean_rows.csv"
REJECTED_FILE = "rejected_rows.csv"
SUMMARY_FILE = "run_summary.json"


def run(
    config_path: str | Path, output_dir: str | Path, check_date: datetime | None = None
) -> dict:
    """Validate all labs in the config, write the three output files, return the summary.

    check_date (timezone-aware, default now) is the latest date a row may have.
    Pass the same value to get the same result again.
    """
    config = load_config(config_path)
    check_date = check_date or datetime.now(UTC).replace(microsecond=0)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    clean, rejected, per_lab, input_sha256 = check_all_labs(config, check_date)
    output_sha256 = write_outputs(output_dir, clean, rejected)
    summary = build_summary(config, check_date, rejected, per_lab, input_sha256, output_sha256)

    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    (output_dir / SUMMARY_FILE).write_text(text, encoding="utf-8", newline="\n")
    return summary


def check_all_labs(
    config: Config, check_date: datetime
) -> tuple[list[Measurement], list[RejectedRow], dict[str, dict[str, int]], dict[str, str]]:
    """Check every lab's file. Each file is read once and hashed from the same bytes.

    Sorting makes the order of labs in the config irrelevant.
    """
    clean: list[Measurement] = []
    rejected: list[RejectedRow] = []
    per_lab = {}
    input_sha256 = {}
    for lab in config.labs:
        text, input_sha256[lab.file] = read_file(lab.path)
        lab_clean, lab_rejected = check_file(lab, text, config.rules, check_date)
        clean += lab_clean
        rejected += lab_rejected
        per_lab[lab.name] = count(len(lab_clean), len(lab_rejected))

    clean.sort(key=lambda measurement: (measurement.lab, measurement.sample_id))
    rejected.sort(key=lambda row: (row.lab, row.line))
    return clean, rejected, per_lab, input_sha256


def write_outputs(
    output_dir: Path, clean: list[Measurement], rejected: list[RejectedRow]
) -> dict[str, str]:
    """Write the two CSV files and return their SHA-256 hashes."""
    return {
        CLEAN_FILE: write_csv(
            output_dir / CLEAN_FILE,
            [field.name for field in fields(Measurement)],
            [{**asdict(row), "collected_at": row.collected_at.isoformat()} for row in clean],
        ),
        REJECTED_FILE: write_csv(
            output_dir / REJECTED_FILE,
            [field.name for field in fields(RejectedRow)],
            [{**asdict(row), "row": json.dumps(row.row, sort_keys=True)} for row in rejected],
        ),
    }


def build_summary(
    config: Config,
    check_date: datetime,
    rejected: list[RejectedRow],
    per_lab: dict[str, dict[str, int]],
    input_sha256: dict[str, str],
    output_sha256: dict[str, str],
) -> dict:
    """Everything needed to tell whether two runs used the same inputs and gave the same result.

    created_at is the only value that changes between identical runs.
    """
    total_clean = sum(lab["clean"] for lab in per_lab.values())
    error_codes = Counter(row.error_code for row in rejected)
    return {
        "tool_version": __version__,
        "environment": {"python": platform.python_version(), "pyyaml": version("PyYAML")},
        "check_date": check_date.isoformat(),
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "config_sha256": config.sha256,
        "input_sha256": input_sha256,
        "output_sha256": output_sha256,
        "counts": count(total_clean, len(rejected)),
        "per_lab": per_lab,
        "per_error_code": dict(sorted(error_codes.items())),
    }


def count(clean: int, rejected: int) -> dict[str, int]:
    return {"total": clean + rejected, "clean": clean, "rejected": rejected}


def write_csv(path: Path, header: list[str], rows: list[dict]) -> str:
    """Write the rows and return the SHA-256 of the bytes written."""
    buffer = io.StringIO()
    # "\n" line endings so the file is byte-identical on every operating system.
    writer = csv.DictWriter(buffer, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    data = buffer.getvalue().encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()
