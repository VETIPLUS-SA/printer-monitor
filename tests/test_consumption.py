"""Unit tests for printer_monitor.consumption (monthly consumption history)."""
import csv
from datetime import date

import pytest

from printer_monitor.consumption import (
    BASELINE_NOTE,
    FILENAME,
    is_valid_month,
    previous_month,
    update_consumption,
)


def _totals(printer_total, copier_total, scan_total, fax_tx_pages, status="ok"):
    return {
        "printer_total": str(printer_total),
        "copier_total": str(copier_total),
        "scan_total": str(scan_total),
        "fax_tx_pages": str(fax_tx_pages),
        "status": status,
        "error": "",
    }


def _read_rows(tmp_path):
    path = tmp_path / FILENAME
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def test_is_valid_month():
    assert is_valid_month("2026-09")
    assert is_valid_month("2026-01")
    assert is_valid_month("2026-12")
    assert not is_valid_month("2026-13")
    assert not is_valid_month("2026-00")
    assert not is_valid_month("26-09")
    assert not is_valid_month("2026/09")
    assert not is_valid_month("")


def test_previous_month():
    assert previous_month(date(2026, 10, 29)) == "2026-09"
    assert previous_month(date(2026, 10, 1)) == "2026-09"
    assert previous_month(date(2026, 3, 31)) == "2026-02"
    assert previous_month(date(2027, 1, 1)) == "2026-12"


def test_first_month_for_a_device_is_a_baseline(tmp_path):
    row = update_consumption(
        tmp_path, "2026-08", "192.168.1.59", "2026-08-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10),
    )
    assert row["note"] == BASELINE_NOTE
    assert row["printer_name"] == ""
    assert row["printer_pages"] == ""
    assert row["copier_pages"] == ""
    assert row["printed_pages"] == ""
    assert row["scanned_pages"] == ""
    assert row["fax_pages"] == ""
    assert row["printer_total"] == "1000"


def test_normal_delta_and_printed_pages_is_printer_plus_copier(tmp_path):
    update_consumption(
        tmp_path, "2026-08", "192.168.1.59", "2026-08-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10),
    )
    row = update_consumption(
        tmp_path, "2026-09", "192.168.1.59", "2026-09-01T08:00:00-05:00",
        _totals(1300, 620, 260, 15),
    )
    assert row["printer_pages"] == "300"
    assert row["copier_pages"] == "120"
    assert row["printed_pages"] == "420"
    assert row["scanned_pages"] == "60"
    assert row["fax_pages"] == "5"
    assert row["note"] == ""


def test_counter_reset_leaves_metric_empty_never_negative(tmp_path):
    update_consumption(
        tmp_path, "2026-08", "192.168.1.59", "2026-08-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10),
    )
    row = update_consumption(
        tmp_path, "2026-09", "192.168.1.59", "2026-09-01T08:00:00-05:00",
        _totals(50, 620, 260, 15),  # printer_total dropped: counter reset
    )
    assert row["printer_pages"] == ""
    assert row["copier_pages"] == "120"
    assert row["printed_pages"] == ""  # depends on printer_pages, which is empty
    assert "counter reset detected" in row["note"]
    assert "printer_pages" in row["note"]
    assert "copier_pages" not in row["note"]


def test_multiple_metrics_reset_listed_in_note(tmp_path):
    update_consumption(
        tmp_path, "2026-08", "192.168.1.59", "2026-08-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10),
    )
    row = update_consumption(
        tmp_path, "2026-09", "192.168.1.59", "2026-09-01T08:00:00-05:00",
        _totals(50, 60, 260, 15),
    )
    assert row["printer_pages"] == ""
    assert row["copier_pages"] == ""
    assert row["note"] == "counter reset detected: printer_pages, copier_pages"


def test_upsert_same_month_replaces_row_and_recomputes_following_month(tmp_path):
    update_consumption(
        tmp_path, "2026-08", "192.168.1.59", "2026-08-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10),
    )
    update_consumption(
        tmp_path, "2026-09", "192.168.1.59", "2026-09-01T08:00:00-05:00",
        _totals(1300, 620, 260, 15),
    )
    # Re-run August with a corrected (higher) value: latest capture wins,
    # and September's delta must be recomputed against the corrected value.
    update_consumption(
        tmp_path, "2026-08", "192.168.1.59", "2026-08-01T09:30:00-05:00",
        _totals(1050, 520, 210, 11),
    )

    rows = {r["month"]: r for r in _read_rows(tmp_path)}
    assert len(rows) == 2
    assert rows["2026-08"]["printer_total"] == "1050"
    assert rows["2026-08"]["captured_at"] == "2026-08-01T09:30:00-05:00"
    assert rows["2026-09"]["printer_pages"] == str(1300 - 1050)
    assert rows["2026-09"]["copier_pages"] == str(620 - 520)
    assert rows["2026-09"]["fax_pages"] == str(15 - 11)


def test_multiple_devices_are_independent(tmp_path):
    update_consumption(
        tmp_path, "2026-08", "192.168.1.59", "2026-08-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10),
    )
    update_consumption(
        tmp_path, "2026-08", "192.168.1.60", "2026-08-01T08:00:00-05:00",
        _totals(50, 20, 5, 0),
    )
    row_59 = update_consumption(
        tmp_path, "2026-09", "192.168.1.59", "2026-09-01T08:00:00-05:00",
        _totals(1300, 620, 260, 15),
    )
    row_60 = update_consumption(
        tmp_path, "2026-09", "192.168.1.60", "2026-09-01T08:00:00-05:00",
        _totals(80, 40, 9, 0),
    )
    assert row_59["printer_pages"] == "300"
    assert row_60["printer_pages"] == "30"

    rows = _read_rows(tmp_path)
    assert {(r["device_ip"], r["month"]) for r in rows} == {
        ("192.168.1.59", "2026-08"),
        ("192.168.1.59", "2026-09"),
        ("192.168.1.60", "2026-08"),
        ("192.168.1.60", "2026-09"),
    }


def test_gap_months_compare_to_most_recent_earlier_month(tmp_path):
    update_consumption(
        tmp_path, "2026-06", "192.168.1.59", "2026-06-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10),
    )
    # July is missing entirely; September should diff against June.
    row = update_consumption(
        tmp_path, "2026-09", "192.168.1.59", "2026-09-01T08:00:00-05:00",
        _totals(1600, 800, 350, 22),
    )
    assert row["printer_pages"] == "600"
    assert row["copier_pages"] == "300"
    assert row["scanned_pages"] == "150"
    assert row["fax_pages"] == "12"


def test_rows_are_sorted_by_device_then_month(tmp_path):
    update_consumption(tmp_path, "2026-09", "192.168.1.60", "t", _totals(1, 1, 1, 1))
    update_consumption(tmp_path, "2026-08", "192.168.1.59", "t", _totals(1, 1, 1, 1))
    update_consumption(tmp_path, "2026-09", "192.168.1.59", "t", _totals(2, 2, 2, 2))

    rows = _read_rows(tmp_path)
    keys = [(r["device_ip"], r["month"]) for r in rows]
    assert keys == sorted(keys)


def test_csv_round_trip_keeps_month_as_yyyy_mm_string(tmp_path):
    update_consumption(
        tmp_path, "2026-09", "192.168.1.59", "2026-09-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10),
    )
    rows = _read_rows(tmp_path)
    assert rows[0]["month"] == "2026-09"
    assert isinstance(rows[0]["month"], str)


def test_invalid_month_raises():
    with pytest.raises(ValueError):
        update_consumption("ignored", "2026-13", "192.168.1.59", "t", _totals(1, 1, 1, 1))


def test_total_row_with_error_status_does_not_write(tmp_path):
    result = update_consumption(
        tmp_path, "2026-09", "192.168.1.59", "2026-09-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10, status="error"),
    )
    assert result is None
    assert not (tmp_path / FILENAME).exists()


def test_printer_name_column_is_stamped_and_stored(tmp_path):
    row = update_consumption(
        tmp_path, "2026-08", "192.168.1.59", "2026-08-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10), printer_name="pedidos",
    )
    assert row["printer_name"] == "pedidos"

    rows = _read_rows(tmp_path)
    assert rows[0]["printer_name"] == "pedidos"


def test_printer_name_defaults_to_empty_string_when_not_given(tmp_path):
    row = update_consumption(
        tmp_path, "2026-08", "192.168.1.59", "2026-08-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10),
    )
    assert row["printer_name"] == ""


def test_old_history_file_without_printer_name_column_still_loads(tmp_path):
    path = tmp_path / FILENAME
    path.write_text(
        "month,device_ip,captured_at,printer_total,copier_total,scan_total,fax_tx_pages,"
        "printer_pages,copier_pages,printed_pages,scanned_pages,fax_pages,note\r\n"
        "2026-08,192.168.1.59,2026-08-01T08:00:00-05:00,1000,500,200,10,,,,,,"
        + BASELINE_NOTE + "\r\n",
        encoding="utf-8-sig",
    )

    row = update_consumption(
        tmp_path, "2026-09", "192.168.1.59", "2026-09-01T08:00:00-05:00",
        _totals(1300, 620, 260, 15), printer_name="pedidos",
    )
    assert row["printer_pages"] == "300"

    rows = {r["month"]: r for r in _read_rows(tmp_path)}
    # The old row's missing column loads as an empty string, not an error.
    assert rows["2026-08"]["printer_name"] == ""
    assert rows["2026-09"]["printer_name"] == "pedidos"


def test_total_row_with_error_status_leaves_existing_file_untouched(tmp_path):
    update_consumption(
        tmp_path, "2026-08", "192.168.1.59", "2026-08-01T08:00:00-05:00",
        _totals(1000, 500, 200, 10),
    )
    before = (tmp_path / FILENAME).read_bytes()

    result = update_consumption(
        tmp_path, "2026-09", "192.168.1.59", "2026-09-01T08:00:00-05:00",
        _totals(1300, 620, 260, 15, status="error"),
    )

    assert result is None
    after = (tmp_path / FILENAME).read_bytes()
    assert before == after
    rows = _read_rows(tmp_path)
    assert len(rows) == 1
