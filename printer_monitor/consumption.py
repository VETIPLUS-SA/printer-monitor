"""Monthly consumption per printer.

Maintains a single running history CSV (`consumo_mensual.csv`) with one row
per (month, device_ip). Each run's device-wide TOTAL row carries cumulative
counters; this module upserts that month's cumulative snapshot and derives
this month's consumption by diffing against the most recent earlier month
for the same device.

Pure logic plus CSV I/O -- no Playwright, no network -- so it is fully unit
testable with synthetic data.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

FIELDNAMES = [
    "month",
    "device_ip",
    "captured_at",
    "printer_total",
    "copier_total",
    "scan_total",
    "fax_tx_pages",
    "printer_pages",
    "copier_pages",
    "printed_pages",
    "scanned_pages",
    "fax_pages",
    "note",
]

# Cumulative device-wide counters copied as-is from the TOTAL row.
_CUMULATIVE_COLUMNS = ["printer_total", "copier_total", "scan_total", "fax_tx_pages"]

# Cumulative column -> this month's consumption (delta) column.
_DELTA_MAP = {
    "printer_total": "printer_pages",
    "copier_total": "copier_pages",
    "scan_total": "scanned_pages",
    "fax_tx_pages": "fax_pages",
}

BASELINE_NOTE = "baseline: no previous month to compare"

FILENAME = "consumo_mensual.csv"


def is_valid_month(value: str) -> bool:
    """True when `value` is a well-formed "YYYY-MM" string."""
    return bool(_MONTH_RE.match(value))


def _to_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _empty_row(month: str, device_ip: str) -> dict:
    row = {name: "" for name in FIELDNAMES}
    row["month"] = month
    row["device_ip"] = device_ip
    return row


def _read_existing(path: Path) -> dict[tuple[str, str], dict]:
    """Read the existing history CSV into {(device_ip, month): row}."""
    rows: dict[tuple[str, str], dict] = {}
    if not path.exists():
        return rows
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            device_ip = raw.get("device_ip", "")
            month = raw.get("month", "")
            rows[(device_ip, month)] = {name: raw.get(name, "") for name in FIELDNAMES}
    return rows


def _write_atomic(path: Path, rows: list[dict]) -> None:
    """Write `rows` to `path`, UTF-8 with BOM, via a temp file + os.replace
    so a crash mid-write never corrupts the existing history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".consumo_mensual_", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, restval="")
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in FIELDNAMES})
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _recompute_device_rows(device_rows: list[dict]) -> list[dict]:
    """Recompute the consumption columns for every row of one device, in
    month order: each month's delta is against the most recent earlier
    month's cumulative counters. The first (earliest) row becomes the
    baseline (empty consumption columns)."""
    ordered = sorted(device_rows, key=lambda r: r["month"])
    previous: Optional[dict] = None
    result: list[dict] = []

    for row in ordered:
        new_row = dict(row)
        if previous is None:
            for delta_col in _DELTA_MAP.values():
                new_row[delta_col] = ""
            new_row["printed_pages"] = ""
            new_row["note"] = BASELINE_NOTE
        else:
            reset_metrics: list[str] = []
            for cumulative_col, delta_col in _DELTA_MAP.items():
                current = _to_int(new_row.get(cumulative_col))
                prior = _to_int(previous.get(cumulative_col))
                if current is None or prior is None:
                    new_row[delta_col] = ""
                    continue
                diff = current - prior
                if diff < 0:
                    reset_metrics.append(delta_col)
                    new_row[delta_col] = ""
                else:
                    new_row[delta_col] = str(diff)

            printer_pages = new_row.get("printer_pages", "")
            copier_pages = new_row.get("copier_pages", "")
            if printer_pages != "" and copier_pages != "":
                new_row["printed_pages"] = str(int(printer_pages) + int(copier_pages))
            else:
                new_row["printed_pages"] = ""

            new_row["note"] = ("counter reset detected: " + ", ".join(reset_metrics)) if reset_metrics else ""

        result.append(new_row)
        previous = new_row

    return result


def update_consumption(
    outdir: Path, month: str, device_ip: str, captured_at: str, totals_row: dict
) -> Optional[dict]:
    """Upsert this run's device-wide totals into
    `{outdir}/consumo_mensual.csv` for (month, device_ip), recompute the
    consumption columns for every row of this device in month order, and
    write the file atomically.

    Re-running for the same (month, device_ip) replaces that month's row
    (latest capture wins) before recomputing, so a corrected month also
    fixes the delta of the month after it.

    If `totals_row["status"]` is not "ok", the file is left untouched, an
    ERROR is logged, and None is returned -- the caller (main.py) already
    treats any row with status="error" as a failed run (exit code 1).

    Returns the recomputed row for (month, device_ip), or None when nothing
    was written.
    """
    if not is_valid_month(month):
        raise ValueError(f"Invalid month {month!r}, expected YYYY-MM")

    if totals_row.get("status") != "ok":
        logger.error(
            "Device totals not ok (status=%s) for %s @ %s; monthly consumption was not updated",
            totals_row.get("status"), month, device_ip,
        )
        return None

    path = Path(outdir) / FILENAME
    existing = _read_existing(path)

    new_row = _empty_row(month, device_ip)
    new_row["captured_at"] = captured_at
    for col in _CUMULATIVE_COLUMNS:
        new_row[col] = totals_row.get(col, "")

    existing[(device_ip, month)] = new_row

    by_device: dict[str, list[dict]] = {}
    for (dev, _month), row in existing.items():
        by_device.setdefault(dev, []).append(row)

    all_rows: list[dict] = []
    for dev in sorted(by_device):
        all_rows.extend(_recompute_device_rows(by_device[dev]))
    all_rows.sort(key=lambda r: (r["device_ip"], r["month"]))

    _write_atomic(path, all_rows)

    for row in all_rows:
        if row["device_ip"] == device_ip and row["month"] == month:
            return row
    raise AssertionError("updated consumption row not found after write")  # pragma: no cover


def format_summary(row: dict) -> str:
    """One-line human-readable summary of a recomputed consumption row, for
    logging after a run."""
    month = row["month"]
    device_ip = row["device_ip"]
    if row.get("note") == BASELINE_NOTE:
        return f"Monthly consumption {month} @ {device_ip}: {BASELINE_NOTE}"
    if row.get("note", "").startswith("counter reset detected"):
        return f"Monthly consumption {month} @ {device_ip}: {row['note']}"
    return (
        f"Monthly consumption {month} @ {device_ip}: "
        f"printed_pages={row.get('printed_pages', '')}, "
        f"scanned_pages={row.get('scanned_pages', '')}, "
        f"fax_pages={row.get('fax_pages', '')}"
    )
