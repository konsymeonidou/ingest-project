# ingest-project

## Summary

This is the validation step of a lab data flow. Three labs export measurements of brain
organoids as CSV files, each in its own format. The tool reads each file with that lab's
settings, checks every row against the rules in `config.yaml`, and splits the rows into clean
and rejected. Each rejected row gets an error code and a reason. The data is synthetic and the
ranges are placeholders, not biological reference values.

I wrote it for my application to the FRESCI position in the VISI-ON-BRAIN network. A "digital
lab supervisor" can only be as good as the data it reads, so this is the first step to get right.

The same config, input files and check date always give byte-identical results:

- The check date is passed in (`--check-date`), not read from the clock.
- `requirements.txt` pins every dependency with hashes, and the Docker image is pinned by digest.
- `tests/expected/` holds the correct output for the sample data. The tests and CI compare every
  run with it.
- `run_summary.json` records the SHA-256 of the config, inputs and outputs, and the Python and
  PyYAML versions.

## How to run

### Option A: Docker Compose

```bash
docker compose up --build                          # check the sample data, write ./outputs
docker compose run --rm ingest-project pytest -q   # run the tests
```

On Linux, run `mkdir outputs` first so the folder belongs to your user.

### Option B: Python 3.13+ with a virtual environment

```bash
python3 -m venv .venv                 # Windows: py -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install --no-deps -e .
pytest -q
ingest-project --config config.yaml --output outputs --check-date 2026-04-01
```

### What you should see

```text
ingest-project 0.1.0, check date 2026-04-01T00:00:00+00:00
  lab_A: 7 rows, 4 clean, 3 rejected
  lab_B: 7 rows, 4 clean, 3 rejected
  lab_C: 7 rows, 4 clean, 3 rejected
  all labs: 21 rows, 12 clean, 9 rejected
    BAD_DATE: 1
    BAD_NUMBER: 1
    DATE_IN_FUTURE: 1
    MISSING_ORGANOID_ID: 1
    NOT_A_NUMBER: 1
    OUT_OF_RANGE: 1
    UNKNOWN_MEASUREMENT: 1
    WRONG_FIELD_COUNT: 1
    WRONG_UNIT: 1
files written to outputs
```

Each bad row in the sample breaks one rule, so every error code appears once. The run writes
three files to `outputs/`:

| File | Content |
| --- | --- |
| `clean_rows.csv` | `sample_id`, `lab`, `organoid_id`, `batch`, `measurement_type`, `value`, `unit`, `collected_at` (UTC) |
| `rejected_rows.csv` | `file`, `line`, `lab`, `error_code`, `reason`, and the original row as JSON |
| `run_summary.json` | tool version, Python and PyYAML versions, check date, SHA-256 of the config, inputs and outputs, counts |

To confirm the results match the expected ones:

```bash
diff outputs/clean_rows.csv tests/expected/clean_rows.csv
diff outputs/rejected_rows.csv tests/expected/rejected_rows.csv
```

### Making changes

- **A new lab:** add a block under `labs` in `config.yaml`. No code change is needed.
- **A rule change that changes the results:** copy the two new CSV files into `tests/expected/`
  in the same commit.
- **A dependency update:** edit `pyproject.toml`, then run the `uv pip compile` command at the
  top of `requirements.txt`.

## Project structure

```text
ingest-project/
├── config.yaml                 rules per measurement, and how to read each lab's file
├── sample_data/                three synthetic lab files, 7 rows each (4 good, 3 bad)
├── src/ingest_project/
│   ├── config.py               reads and checks config.yaml; reads each file once and hashes it
│   ├── validation.py           parses numbers and dates, checks each row, splits clean/rejected
│   ├── pipeline.py             runs every lab, writes the three output files and the summary
│   └── cli.py                  the ingest-project command; exit code 2 on errors
├── tests/
│   ├── test_validation.py      edge cases, plus a full run compared with tests/expected/
│   └── expected/               the correct clean_rows.csv and rejected_rows.csv
├── pyproject.toml              package, Python version, dependency ranges, command, lint settings
├── requirements.txt            exact dependency versions with hashes
├── Dockerfile                  pinned base image, installs from requirements.txt, non-root user
├── compose.yaml                docker compose up: build, run the sample, write ./outputs
└── .github/workflows/ci.yml    lint, tests and expected-output check on Python 3.13, 3.14, 3.15
```
