"""Read config.yaml into simple settings objects."""

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

COLUMN_FIELDS = (
    "sample_id",
    "organoid_id",
    "batch",
    "measurement",
    "value",
    "unit",
    "collected_at",
)


class ConfigError(Exception):
    """The config file or a data file cannot be used."""


@dataclass(frozen=True)
class Rule:
    unit: str
    min_value: float
    max_value: float


@dataclass(frozen=True)
class LabSettings:
    name: str
    file: str  # as written in the config, relative to the config file
    path: Path
    delimiter: str
    decimal_mark: str
    date_format: str  # "iso" or a strptime format
    measurements: tuple[str, ...]
    columns: dict[str, str]  # our field name -> column name in the lab's file


@dataclass(frozen=True)
class Config:
    path: Path
    sha256: str  # hash of the bytes that were parsed
    labs: list[LabSettings]
    rules: dict[str, Rule]


def read_file(path: Path) -> tuple[str, str]:
    """Return (text, sha256) from a single read, so the hash matches the text that is used."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error.strerror}") from error
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ConfigError(f"{path} is not UTF-8 text") from None
    return text, hashlib.sha256(data).hexdigest()


def require(section: object, key: str, kind: type | tuple[type, ...], section_name: str) -> Any:
    """Return section[key], or raise ConfigError if it is missing or has the wrong type."""
    if not isinstance(section, dict):
        raise ConfigError(f"{section_name}: expected a mapping")
    if key not in section:
        raise ConfigError(f"{section_name}: missing '{key}'")
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, kind):
        raise ConfigError(f"{section_name}: '{key}' has the wrong type ({type(value).__name__})")
    return value


def read_rule(name: str, entry: object) -> Rule:
    section_name = f"rules.{name}"
    min_value = require(entry, "min_value", (int, float), section_name)
    max_value = require(entry, "max_value", (int, float), section_name)
    if not (math.isfinite(min_value) and math.isfinite(max_value)):
        raise ConfigError(f"{section_name}: min_value and max_value must be finite numbers")
    if min_value > max_value:
        raise ConfigError(
            f"{section_name}: min_value {min_value} is greater than max_value {max_value}"
        )
    return Rule(require(entry, "unit", str, section_name), float(min_value), float(max_value))


def read_lab(name: str, section: object, rules: dict[str, Rule], folder: Path) -> LabSettings:
    section_name = f"labs.{name}"
    delimiter = require(section, "delimiter", str, section_name)
    decimal_mark = require(section, "decimal_mark", str, section_name)
    if len(delimiter) != 1 or decimal_mark not in (".", ","):
        raise ConfigError(
            f"{section_name}: delimiter must be one character, decimal_mark '.' or ','"
        )
    if delimiter == decimal_mark:
        raise ConfigError(
            f"{section_name}: delimiter and decimal_mark cannot both be '{delimiter}'"
        )

    columns = require(section, "columns", dict, section_name)
    for field in COLUMN_FIELDS:
        require(columns, field, str, f"{section_name}.columns")

    measurements = require(section, "measurements", list, section_name)
    for measurement in measurements:
        if not isinstance(measurement, str):
            raise ConfigError(f"{section_name}: measurements must be names, got {measurement!r}")
        if measurement not in rules:
            raise ConfigError(f"{section_name}: measurement '{measurement}' has no rule")

    file = require(section, "file", str, section_name)
    if Path(file).is_absolute():
        raise ConfigError(f"{section_name}: file must be relative to the config file, got {file}")
    path = folder / file
    if not path.is_file():
        raise ConfigError(f"{section_name}: data file not found: {file}")
    return LabSettings(
        name=name,
        file=file,
        path=path,
        delimiter=delimiter,
        decimal_mark=decimal_mark,
        date_format=require(section, "date_format", str, section_name),
        measurements=tuple(measurements),
        columns={field: columns[field] for field in COLUMN_FIELDS},
    )


def load_config(path: str | Path) -> Config:
    """Read and check the config file. Raises ConfigError with a clear message."""
    path = Path(path)
    text, sha256 = read_file(path)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"{path} is not valid YAML: {str(error).splitlines()[0]}") from error

    rules = {
        str(name): read_rule(str(name), entry)
        for name, entry in require(data, "rules", dict, "config").items()
    }
    labs = [
        read_lab(str(name), section, rules, path.parent)
        for name, section in require(data, "labs", dict, "config").items()
    ]
    return Config(path=path, sha256=sha256, labs=labs, rules=rules)
