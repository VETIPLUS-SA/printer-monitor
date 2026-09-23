"""CSV output for the extractor: one row per account, fixed base columns
in a stable order, plus any unexpected portal-reported extra columns
appended deterministically at the end.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

BASE_COLUMNS = [
    "captured_at",
    "device_ip",
    "account_id",
    "account_private_id",
    "account_name",
    "copier_total",
    "printer_total",
    "duplex_1sided",
    "duplex_2sided",
    "duplex_total",
    "combine_none",
    "combine_2in1",
    "combine_4in1",
    "combine_total",
    "scan_copy",
    "scan_fax",
    "scan_other",
    "scan_total",
    "fax_tx_pages",
    "fax_tx_time",
    "status",
    "error",
]


def build_fieldnames(rows: list[dict]) -> list[str]:
    """Base columns, in the fixed order, followed by any extra (unexpected
    portal label) columns found across all rows, sorted for determinism."""
    extra: set[str] = set()
    for row in rows:
        extra.update(key for key in row.keys() if key not in BASE_COLUMNS)
    return BASE_COLUMNS + sorted(extra)


def write_csv(rows: list[dict], outdir: Path, timestamp: datetime | None = None) -> Path:
    """Write `rows` to `{outdir}/counters_{YYYYmmdd_HHMMSS}.csv`.

    UTF-8 with a BOM so Excel on Windows opens accented characters (á, é,
    ñ, ...) correctly. Every value is written as-is (as a string), so
    account IDs with leading zeros are preserved.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ts = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
    path = outdir / f"counters_{ts}.csv"

    fieldnames = build_fieldnames(rows)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, restval="")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

    return path
