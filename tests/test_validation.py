import csv
import hashlib
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ingest_project.cli import main
from ingest_project.config import ConfigError, load_config
from ingest_project.pipeline import run
from ingest_project.validation import (
    Measurement,
    RowError,
    check_file,
    check_measurement,
    read_measurement,
)

CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"
EXPECTED = Path(__file__).resolve().parent / "expected"
CHECK_DATE = datetime(2026, 4, 1, tzinfo=UTC)

GOOD = Measurement(
    sample_id="A-001",
    lab="lab_A",
    organoid_id="ORG-A01",
    batch="BATCH-A1",
    measurement_type="viability_pct",
    value=87.5,
    unit="%",
    collected_at=datetime(2026, 3, 15, tzinfo=UTC),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


# One row at a time


def test_reading_a_row() -> None:
    lab = load_config(CONFIG).labs[0]
    row = {"SampleID": "A-1", "OrganoidID": "O", "Batch": "B", "Type": "viability_pct"}
    row |= {"Value": "90", "Unit": "%", "Date": "15/03/2026"}
    assert read_measurement(row, lab).collected_at == datetime(2026, 3, 15, tzinfo=UTC)
    without_date = {name: text for name, text in row.items() if name != "Date"}
    for broken, code in [
        ({**row, "Value": "12,5"}, "BAD_NUMBER"),  # lab_A uses "." so this is not read as 125
        ({**row, "Date": "2026-03-15"}, "BAD_DATE"),
        (without_date, "MISSING_COLUMN"),
    ]:
        with pytest.raises(RowError) as error:
            read_measurement(broken, lab)
        assert error.value.code == code


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"value": 100.0, "collected_at": CHECK_DATE}, None),
        ({"value": 100.1}, "OUT_OF_RANGE"),
        ({"value": float("inf")}, "NOT_A_NUMBER"),
        ({"collected_at": datetime(2026, 4, 1, 0, 0, 1, tzinfo=UTC)}, "DATE_IN_FUTURE"),
    ],
)
def test_limits_are_exact(changes: dict, code: str | None) -> None:
    config = load_config(CONFIG)
    rules = {name: config.rules[name] for name in config.labs[0].measurements}
    if code is None:
        check_measurement(replace(GOOD, **changes), rules, CHECK_DATE)
        return
    with pytest.raises(RowError) as error:
        check_measurement(replace(GOOD, **changes), rules, CHECK_DATE)
    assert error.value.code == code


# Whole run on the sample data


def test_sample_data(tmp_path: Path) -> None:
    summary = run(CONFIG, tmp_path, CHECK_DATE)
    assert summary["counts"] == {"total": 21, "clean": 12, "rejected": 9}
    assert len(summary["per_error_code"]) == 9
    assert set(summary["per_error_code"].values()) == {1}
    rejected = read_csv(tmp_path / "rejected_rows.csv")
    # B-107 has a missing field: it is rejected, not padded with an empty value
    assert any(r["error_code"] == "WRONG_FIELD_COUNT" and "B-107" in r["row"] for r in rejected)


def test_outputs_match_the_expected_files(tmp_path: Path) -> None:
    """Two runs agree with each other and with the files committed in tests/expected."""
    first = run(CONFIG, tmp_path / "one", CHECK_DATE)
    second = run(CONFIG, tmp_path / "two", CHECK_DATE)
    for name in ("clean_rows.csv", "rejected_rows.csv"):
        expected = (EXPECTED / name).read_bytes()
        assert (tmp_path / "one" / name).read_bytes() == expected
        assert (tmp_path / "two" / name).read_bytes() == expected
        assert first["output_sha256"][name] == hashlib.sha256(expected).hexdigest()
    first.pop("created_at")
    second.pop("created_at")
    assert first == second


def test_row_dated_2030_depends_on_check_date(tmp_path: Path) -> None:
    run(CONFIG, tmp_path / "now", CHECK_DATE)
    run(CONFIG, tmp_path / "later", datetime(2031, 1, 1, tzinfo=UTC))
    now_ids = {r["sample_id"] for r in read_csv(tmp_path / "now" / "clean_rows.csv")}
    later_ids = {r["sample_id"] for r in read_csv(tmp_path / "later" / "clean_rows.csv")}
    assert "B-105" not in now_ids
    assert "B-105" in later_ids


# Errors that stop the run


def test_duplicate_column_names_stop_the_run() -> None:
    config = load_config(CONFIG)
    with pytest.raises(ConfigError, match="duplicate column names"):
        check_file(config.labs[0], "SampleID,Batch,Batch\nA-1,x,y\n", config.rules, CHECK_DATE)


@pytest.mark.parametrize(
    ("file_name", "old", "new", "message"),
    [
        ("config.yaml", b"[viability_pct]", b"[made_up]", "made_up"),
        ("sample_data/lab_A.csv", b"SampleID", b"Sample\xe9", "not UTF-8"),
    ],
)
def test_bad_input_gives_exit_code_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    file_name: str,
    old: bytes,
    new: bytes,
    message: str,
) -> None:
    shutil.copy(CONFIG, tmp_path / "config.yaml")
    shutil.copytree(CONFIG.parent / "sample_data", tmp_path / "sample_data")
    broken = tmp_path / file_name
    broken.write_bytes(broken.read_bytes().replace(old, new))
    assert main(["--config", str(tmp_path / "config.yaml"), "--output", str(tmp_path / "out")]) == 2
    error_text = capsys.readouterr().err
    assert error_text.startswith("error: ") and message in error_text
    assert "Traceback" not in error_text
