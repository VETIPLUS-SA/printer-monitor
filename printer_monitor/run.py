"""Pure sequencing/aggregation logic for running `extract` across several
printers: turning one printer's raw run result into a summary status, and
combining every printer's status into one exit code and one summary table.

No Playwright and no I/O here -- this module is fully unit testable with
fake rows/flags, independently of printer_monitor.portal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PrinterOutcome:
    name: str
    ip: str
    status: str  # one-line human-readable status for the summary table
    failed: bool = False
    blocked: bool = False
    error_rows: int = 0


def build_outcome(
    name: str,
    ip: str,
    rows: Optional[list[dict]] = None,
    blocked: bool = False,
    blocked_count: int = 0,
    error: Optional[str] = None,
) -> PrinterOutcome:
    """Turn one printer's raw run result into a PrinterOutcome.

    Exactly one of these describes a given call:
      * `error` set: the printer run raised (PortalError or any other
        exception, e.g. a Playwright TimeoutError when the printer is
        off/unreachable) -- status "failed: <error>".
      * `blocked=True`: the safety guard blocked at least one request
        during this printer's run, so nothing was written for it --
        status "skipped: safety guard blocked N request(s)".
      * `rows` given: the run completed; status is "ok" or
        "N account error(s)" depending on how many rows have
        status="error".
    """
    if error is not None:
        return PrinterOutcome(name=name, ip=ip, status=f"failed: {error}", failed=True)

    if blocked:
        return PrinterOutcome(
            name=name,
            ip=ip,
            status=f"skipped: safety guard blocked {blocked_count} request(s)",
            blocked=True,
        )

    rows = rows or []
    error_count = sum(1 for row in rows if row.get("status") == "error")
    if error_count:
        return PrinterOutcome(
            name=name, ip=ip, status=f"{error_count} account error(s)", error_rows=error_count
        )

    return PrinterOutcome(name=name, ip=ip, status="ok")


def aggregate_exit_code(outcomes: list[PrinterOutcome], config_error: bool = False) -> int:
    """2 if any printer's SafetyGuard blocked something; else 1 if any
    printer failed, had at least one account error, or a config error
    occurred; else 0."""
    if any(outcome.blocked for outcome in outcomes):
        return 2
    if config_error or any(outcome.failed or outcome.error_rows > 0 for outcome in outcomes):
        return 1
    return 0


def format_summary_table(outcomes: list[PrinterOutcome]) -> str:
    """One line per printer: name, ip, status. Meant to be logged (or
    printed) as a single multi-line message at the end of a run."""
    lines = ["Run summary:"]
    for outcome in outcomes:
        lines.append(f"  {outcome.name} ({outcome.ip}): {outcome.status}")
    return "\n".join(lines)
