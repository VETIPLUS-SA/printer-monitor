"""Unit tests for printer_monitor.run (per-printer outcome -> exit code /
summary aggregation). Pure logic, exercised with fake rows -- no Playwright,
no portal, no filesystem."""
from printer_monitor.run import aggregate_exit_code, build_outcome, format_summary_table


def _rows(*statuses: str) -> list[dict]:
    return [{"status": status} for status in statuses]


def test_build_outcome_ok_when_no_error_rows():
    outcome = build_outcome("pedidos", "192.168.1.59", rows=_rows("ok", "ok"))
    assert outcome.status == "ok"
    assert not outcome.failed
    assert not outcome.blocked
    assert outcome.error_rows == 0


def test_build_outcome_counts_account_errors():
    outcome = build_outcome("pedidos", "192.168.1.59", rows=_rows("ok", "error", "error"))
    assert outcome.status == "2 account error(s)"
    assert outcome.error_rows == 2
    assert not outcome.failed


def test_build_outcome_failed_on_error():
    outcome = build_outcome("bodega", "192.168.1.162", error="login timed out")
    assert outcome.failed
    assert outcome.status == "failed: login timed out"
    assert not outcome.blocked


def test_build_outcome_blocked_on_safety_guard():
    outcome = build_outcome("cartera", "192.168.1.104", blocked=True, blocked_count=3)
    assert outcome.blocked
    assert "3 request(s)" in outcome.status
    assert not outcome.failed


def test_build_outcome_empty_rows_is_ok():
    outcome = build_outcome("pedidos", "192.168.1.59", rows=[])
    assert outcome.status == "ok"


def test_aggregate_exit_code_all_ok_is_zero():
    outcomes = [
        build_outcome("pedidos", "192.168.1.59", rows=_rows("ok")),
        build_outcome("cartera", "192.168.1.104", rows=_rows("ok")),
    ]
    assert aggregate_exit_code(outcomes) == 0


def test_aggregate_exit_code_failed_printer_is_one():
    outcomes = [
        build_outcome("pedidos", "192.168.1.59", rows=_rows("ok")),
        build_outcome("bodega", "192.168.1.162", error="unreachable"),
    ]
    assert aggregate_exit_code(outcomes) == 1


def test_aggregate_exit_code_account_error_is_one():
    outcomes = [build_outcome("pedidos", "192.168.1.59", rows=_rows("ok", "error"))]
    assert aggregate_exit_code(outcomes) == 1


def test_aggregate_exit_code_blocked_wins_over_failed():
    outcomes = [
        build_outcome("pedidos", "192.168.1.59", error="unreachable"),
        build_outcome("cartera", "192.168.1.104", blocked=True, blocked_count=1),
    ]
    assert aggregate_exit_code(outcomes) == 2


def test_aggregate_exit_code_config_error_forces_one_even_with_no_outcomes():
    assert aggregate_exit_code([], config_error=True) == 1


def test_aggregate_exit_code_empty_outcomes_is_zero():
    assert aggregate_exit_code([]) == 0


def test_format_summary_table_lists_one_line_per_printer():
    outcomes = [
        build_outcome("pedidos", "192.168.1.59", rows=_rows("ok")),
        build_outcome("bodega", "192.168.1.162", error="unreachable"),
    ]
    table = format_summary_table(outcomes)
    lines = table.splitlines()
    assert lines[0] == "Run summary:"
    assert any("pedidos" in line and "192.168.1.59" in line and "ok" in line for line in lines)
    assert any("bodega" in line and "failed: unreachable" in line for line in lines)
