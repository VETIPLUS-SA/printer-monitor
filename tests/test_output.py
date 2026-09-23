"""Unit tests for printer_monitor.output (CSV writer)."""
import csv
from datetime import datetime

from printer_monitor.output import BASE_COLUMNS, build_fieldnames, write_csv


def _ok_row(account_id: str, private_id: str = "1", name: str = "Fake User"):
    return {
        "captured_at": "2026-09-01T08:00:00-05:00",
        "device_ip": "192.168.1.59",
        "printer_name": "default",
        "account_id": account_id,
        "account_private_id": private_id,
        "account_name": name,
        "copier_total": "10",
        "printer_total": "20",
        "duplex_1sided": "1",
        "duplex_2sided": "2",
        "duplex_total": "3",
        "combine_none": "4",
        "combine_2in1": "5",
        "combine_4in1": "6",
        "combine_total": "7",
        "scan_copy": "8",
        "scan_fax": "9",
        "scan_other": "10",
        "scan_total": "11",
        "fax_tx_pages": "0",
        "fax_tx_time": "0:00:00",
        "status": "ok",
        "error": "",
    }


def test_column_order_matches_spec():
    expected = [
        "captured_at", "device_ip", "printer_name", "account_id", "account_private_id", "account_name",
        "copier_total", "printer_total",
        "duplex_1sided", "duplex_2sided", "duplex_total",
        "combine_none", "combine_2in1", "combine_4in1", "combine_total",
        "scan_copy", "scan_fax", "scan_other", "scan_total",
        "fax_tx_pages", "fax_tx_time",
        "status", "error",
    ]
    assert BASE_COLUMNS == expected


def test_extra_columns_appended_sorted_after_base_columns():
    rows = [
        {**_ok_row("0001"), "zzz_future": "1"},
        {**_ok_row("0002"), "aaa_future": "2"},
    ]
    fieldnames = build_fieldnames(rows)
    assert fieldnames[: len(BASE_COLUMNS)] == BASE_COLUMNS
    assert fieldnames[len(BASE_COLUMNS):] == ["aaa_future", "zzz_future"]


def test_write_csv_keeps_leading_zeros_in_account_id(tmp_path):
    rows = [_ok_row("0007")]
    path = write_csv(rows, tmp_path, "192.168.1.59", timestamp=datetime(2026, 9, 1, 8, 30, 0))
    assert path.name == "counters_192.168.1.59_20260901_083000.csv"

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        written = list(reader)
    assert written[0]["account_id"] == "0007"
    assert written[0]["printer_name"] == "default"


def test_write_csv_includes_error_rows_without_dropping_them(tmp_path):
    error_row = {
        "captured_at": "2026-09-01T08:00:00-05:00",
        "device_ip": "192.168.1.59",
        "printer_name": "default",
        "account_id": "0099",
        "account_private_id": "42",
        "account_name": "Broken User",
        "status": "error",
        "error": "timeout reading detail page",
    }
    rows = [_ok_row("0001"), error_row]
    path = write_csv(rows, tmp_path, "192.168.1.59", timestamp=datetime(2026, 9, 1, 8, 30, 0))

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        written = list(reader)

    assert len(written) == 2
    err = next(r for r in written if r["account_id"] == "0099")
    assert err["status"] == "error"
    assert err["error"] == "timeout reading detail page"
    # Missing counter columns for the failed account must be empty, not absent.
    assert err["copier_total"] == ""


def test_write_csv_uses_utf8_bom_for_excel(tmp_path):
    rows = [_ok_row("0001", name="Ñandú Pérez")]
    path = write_csv(rows, tmp_path, "192.168.1.59", timestamp=datetime(2026, 9, 1, 8, 30, 0))
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "Ñandú Pérez".encode("utf-8") in raw


def test_write_csv_filename_includes_device_ip_to_avoid_collisions(tmp_path):
    ts = datetime(2026, 9, 1, 8, 30, 0)
    path_a = write_csv([_ok_row("0001")], tmp_path, "192.168.1.59", timestamp=ts)
    path_b = write_csv([_ok_row("0001")], tmp_path, "192.168.1.104", timestamp=ts)
    assert path_a != path_b
    assert "192.168.1.59" in path_a.name
    assert "192.168.1.104" in path_b.name
