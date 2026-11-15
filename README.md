# Contract payment report

The CLI reads the three CSV files in `data/` and prints a Russian-language Markdown report for the end of a specified date. It lists every work item under each signed contract and reconciles money received by the contractor with amounts assigned to that contract's work items.

## Run

Use Python 3.10 or later. The CLI uses the standard library.

```sh
python3 report.py --as-of 2026-11-10
```

Use `--data-dir` for another export and redirect stdout to save the report.

```sh
python3 report.py --data-dir /path/to/data --as-of 2026-11-10 > report.md
```

The default data directory is next to `report.py`. Invalid inputs produce an error on stderr and exit status 2. A successful run prints the report and exits with status 0.

- [Sample report for 10 November 2026](REPORT-2026-11-10.md)
- [Accounting note](ACCOUNTANT.md)
- [Decisions and assumptions](DECISIONS.md)

## Verify

```sh
python3 -m unittest discover -s tests -v
ruff format --check .
ruff check .
```
