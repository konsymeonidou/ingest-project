"""Check every row of a lab's CSV file and split the rows into clean and rejected."""

import csv
import io
import math
from dataclasses import dataclass
from datetime import UTC, datetime

from .config import ConfigError, LabSettings, Rule


@dataclass(frozen=True)
class Measurement:
    """One clean row, in the same format for every lab."""

    sample_id: str
    lab: str
    organoid_id: str
    batch: str
    measurement_type: str
    value: float
    unit: str
    collected_at: datetime  # always UTC


@dataclass(frozen=True)
class RejectedRow:
    """One row that failed a check, kept with the reason."""

    file: str
    line: int  # line number in the file, the header is line 1
    lab: str
    error_code: str
    reason: str
    row: dict[str, str] | list[str]  # a list when the field count is wrong


class RowError(Exception):
    """A row failed a check. `code` is for counting, `reason` is for people."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


# --- Reading values ---------------------------------------------------------------------


def parse_number(text: str, decimal_mark: str) -> float:
    """Read a number written with the lab's decimal mark. The other mark is rejected."""
    other_mark = "," if decimal_mark == "." else "."
    cleaned = text.strip()
    # "_" is rejected too, because Python would read "1_0" as 10.
    if other_mark in cleaned or "_" in cleaned:
        raise RowError("BAD_NUMBER", f"'{text}' is not a number with decimal mark '{decimal_mark}'")
    try:
        return float(cleaned.replace(decimal_mark, "."))
    except ValueError:
        raise RowError("BAD_NUMBER", f"'{text}' is not a number") from None


def parse_date(text: str, date_format: str) -> datetime:
    """Read a date in the lab's format ("iso" or a strptime format). No timezone means UTC."""
    cleaned = text.strip()
    try:
        if date_format == "iso":
            date = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        else:
            date = datetime.strptime(cleaned, date_format)
    except ValueError:
        raise RowError("BAD_DATE", f"'{text}' does not match date format '{date_format}'") from None
    if date.tzinfo is None:
        return date.replace(tzinfo=UTC)
    return date.astimezone(UTC)


def read_measurement(row: dict[str, str], lab: LabSettings) -> Measurement:
    """Turn a row into a Measurement using the lab's column names and formats."""

    def column(field: str) -> str:
        name = lab.columns[field]
        if name not in row:
            raise RowError("MISSING_COLUMN", f"column '{name}' not found")
        return row[name].strip()

    return Measurement(
        sample_id=column("sample_id"),
        lab=lab.name,
        organoid_id=column("organoid_id"),
        batch=column("batch"),
        measurement_type=column("measurement"),
        value=parse_number(column("value"), lab.decimal_mark),
        unit=column("unit"),
        collected_at=parse_date(column("collected_at"), lab.date_format),
    )


def check_measurement(
    measurement: Measurement, rules: dict[str, Rule], check_date: datetime
) -> None:
    """Raise RowError for the first check that fails."""
    if not measurement.organoid_id:
        raise RowError("MISSING_ORGANOID_ID", "organoid_id is empty")

    rule = rules.get(measurement.measurement_type)
    if rule is None:
        raise RowError("UNKNOWN_MEASUREMENT", f"no rule for '{measurement.measurement_type}'")
    if measurement.unit != rule.unit:
        raise RowError("WRONG_UNIT", f"unit is '{measurement.unit}', expected '{rule.unit}'")
    if not math.isfinite(measurement.value):
        raise RowError("NOT_A_NUMBER", f"value is {measurement.value}")
    if not rule.min_value <= measurement.value <= rule.max_value:
        raise RowError(
            "OUT_OF_RANGE",
            f"value {measurement.value} is outside {rule.min_value} to {rule.max_value}",
        )

    # check_date is passed in instead of reading the clock, so a rerun gives the same result.
    if measurement.collected_at > check_date:
        raise RowError(
            "DATE_IN_FUTURE",
            f"collected {measurement.collected_at.isoformat()}, after {check_date.isoformat()}",
        )


def check_file(
    lab: LabSettings, text: str, rules: dict[str, Rule], check_date: datetime
) -> tuple[list[Measurement], list[RejectedRow]]:
    """Check the text of one lab's file and return its clean measurements and rejected rows.

    Only the measurements listed for the lab count as known.
    """
    lab_rules = {name: rules[name] for name in lab.measurements}
    clean: list[Measurement] = []
    rejected: list[RejectedRow] = []

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=lab.delimiter)
    header = next(reader, [])
    duplicates = sorted({name for name in header if header.count(name) > 1})
    if duplicates:
        # The columns cannot be told apart, so stop instead of rejecting every row.
        raise ConfigError(f"{lab.file}: duplicate column names in header: {duplicates}")

    for fields in reader:
        if not fields:  # skip empty lines
            continue
        if len(fields) != len(header):
            reason = f"expected {len(header)} fields, got {len(fields)}"
            error = RowError("WRONG_FIELD_COUNT", reason)
            rejected.append(reject(lab, reader.line_num, error, fields))
            continue

        row = dict(zip(header, fields, strict=True))
        try:
            measurement = read_measurement(row, lab)
            check_measurement(measurement, lab_rules, check_date)
        except RowError as error:
            rejected.append(reject(lab, reader.line_num, error, row))
        else:
            clean.append(measurement)

    return clean, rejected


def reject(
    lab: LabSettings, line: int, error: RowError, row: dict[str, str] | list[str]
) -> RejectedRow:
    return RejectedRow(lab.file, line, lab.name, error.code, error.reason, row)
