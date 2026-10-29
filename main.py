"""CLI entry point for the Kyocera portal job-counter extractor.

Subcommands:
  extract   Log in to one or more printers, read every account's
            job-accounting counters plus the "other account" bucket and
            the device-wide totals, write them to a CSV per printer, and
            (unless --dry-run) update each printer's running monthly
            consumption history. Printers run sequentially, each with its
            own browser session; one printer failing never stops the
            others (see the run summary printed at the end).

Exit codes (extract), computed across all configured/selected printers:
  0  every printer ran with no account errors
  1  configuration error, or at least one printer had a fatal portal
     error / unexpected failure / an account with status=error
  2  the safety guard blocked at least one request on at least one
     printer during the run
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from printer_monitor.config import ConfigError, Settings, load_printers
from printer_monitor.consumption import format_summary, is_valid_month, previous_month, update_consumption
from printer_monitor.extract import run_extraction
from printer_monitor.output import write_csv
from printer_monitor.portal import KyoceraPortal, PortalError, TOTAL_ACCOUNT_ID
from printer_monitor.run import PrinterOutcome, aggregate_exit_code, build_outcome, format_summary_table


def _setup_logging(log_dir: Path | None) -> None:
    """Log to the console always, and additionally to
    {outdir}/logs/extract_{timestamp}.log unless log_dir is None (dry-run)."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        handlers.append(logging.FileHandler(log_dir / f"extract_{ts}.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _select_printers(printers: list[Settings], requested: list[str] | None) -> list[Settings] | str:
    """Filter `printers` to the names in `requested` (case-insensitive,
    order of `requested` is not preserved -- `printers`' order is kept).
    Returns the filtered list, or an error message (str) if a requested
    name doesn't match any configured printer."""
    if not requested:
        return printers

    by_lower = {p.name.lower(): p for p in printers}
    unknown = [name for name in requested if name.lower() not in by_lower]
    if unknown:
        configured = ", ".join(p.name for p in printers)
        return (
            f"Unknown printer name(s): {', '.join(unknown)}. "
            f"Configured printer(s): {configured}."
        )

    wanted_lower = {name.lower() for name in requested}
    return [p for p in printers if p.name.lower() in wanted_lower]


def _run_one_printer(
    settings: Settings,
    device_ip: str,
    outdir: Path,
    dry_run: bool,
    save_pdf: bool,
    month: str,
    headed: bool,
    logger: logging.Logger,
) -> PrinterOutcome:
    """Open a fresh KyoceraPortal for `settings`, run the extraction, and
    (unless dry-run or safety-blocked) write its CSV and update its
    monthly consumption row. Never raises: any PortalError or other
    exception (e.g. a Playwright TimeoutError when the printer is
    unreachable) is caught here and turned into a "failed" outcome so one
    printer never stops the others."""
    portal = KyoceraPortal(settings, headed=headed)
    try:
        with portal:
            rows = run_extraction(
                portal,
                device_ip=device_ip,
                outdir=None if dry_run else outdir,
                save_pdf=save_pdf,
                month=month,
                printer_name=settings.name,
            )
    except PortalError as exc:
        logger.error("Printer %s: fatal portal error: %s", settings.name, exc)
        return build_outcome(settings.name, device_ip, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - one printer's failure must never stop the others
        # Playwright errors append a multi-line call log; the first line is the useful part.
        message = (str(exc).splitlines() or [repr(exc)])[0]
        logger.error("Printer %s: unexpected error: %s", settings.name, message)
        return build_outcome(settings.name, device_ip, error=message)

    if portal.guard.has_blocked:
        blocked_count = len(portal.guard.blocked)
        logger.error(
            "SAFETY WARNING (printer %s): %d request(s) were blocked by the safety guard during "
            "this run. Nothing destructive was executed, but review the log above -- the run may "
            "be incomplete.",
            settings.name, blocked_count,
        )
        return build_outcome(settings.name, device_ip, blocked=True, blocked_count=blocked_count)

    if dry_run:
        logger.info(
            "Printer %s: dry run complete: %d record(s) walked, no files written",
            settings.name, len(rows),
        )
        return build_outcome(settings.name, device_ip, rows=rows)

    csv_path = write_csv(rows, outdir, device_ip)
    logger.info("Printer %s: wrote %s", settings.name, csv_path)

    totals_row = next((row for row in rows if row.get("account_id") == TOTAL_ACCOUNT_ID), None)
    if totals_row is None:
        logger.error(
            "Printer %s: no device-totals row found; monthly consumption was not updated",
            settings.name,
        )
    else:
        consumption_row = update_consumption(
            outdir=outdir,
            month=month,
            device_ip=device_ip,
            captured_at=totals_row.get("captured_at", ""),
            totals_row=totals_row,
            printer_name=settings.name,
        )
        if consumption_row is not None:
            logger.info(format_summary(consumption_row))

    return build_outcome(settings.name, device_ip, rows=rows)


def _cmd_extract(args: argparse.Namespace) -> int:
    try:
        printers = load_printers()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    selected = _select_printers(printers, args.printer)
    if isinstance(selected, str):
        print(selected, file=sys.stderr)
        return 1
    printers = selected

    if args.month is not None and not is_valid_month(args.month):
        print(f"Invalid --month value: {args.month!r} (expected YYYY-MM)", file=sys.stderr)
        return 1
    if args.previous_month:
        month = previous_month(datetime.now().date())
    else:
        month = args.month or datetime.now().strftime("%Y-%m")

    outdir = Path(args.outdir or printers[0].outdir)
    dry_run = args.dry_run

    _setup_logging(None if dry_run else (outdir / "logs"))
    logger = logging.getLogger("printer_monitor.main")

    save_pdf = args.pdf
    if args.pdf and args.headed:
        logger.warning("--pdf requires headless Chromium; PDFs will be skipped because --headed was given")
        save_pdf = False
    if args.pdf and dry_run:
        logger.warning("--dry-run writes no files at all; --pdf has no effect")
        save_pdf = False

    outcomes: list[PrinterOutcome] = []
    total = len(printers)
    for index, settings in enumerate(printers, start=1):
        device_ip = urlparse(settings.url).hostname or settings.url
        logger.info("Printer %d of %d: %s (%s)", index, total, settings.name, device_ip)
        outcomes.append(
            _run_one_printer(settings, device_ip, outdir, dry_run, save_pdf, month, args.headed, logger)
        )

    logger.info(format_summary_table(outcomes))

    return aggregate_exit_code(outcomes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Kyocera Command Center RX job-counter extractor (read-only).",
    )
    subparsers = parser.add_subparsers(dest="command")

    extract_parser = subparsers.add_parser(
        "extract",
        help="Log in and extract job-accounting counters for every account",
    )
    extract_parser.add_argument(
        "--headed", action="store_true",
        help="Run Chromium with a visible window (for debugging; disables --pdf)",
    )
    extract_parser.add_argument(
        "--dry-run", action="store_true",
        help="Walk every account and read counters, but write no files at all (no CSV, no PDF, no diagnostics, no log file)",
    )
    extract_parser.add_argument(
        "--outdir", metavar="DIR",
        help="Output directory (default: KYOCERA_OUTDIR env var, or 'output')",
    )
    extract_parser.add_argument(
        "--pdf", action="store_true",
        help="Also save each account's detail page as a PDF (headless only)",
    )
    month_group = extract_parser.add_mutually_exclusive_group()
    month_group.add_argument(
        "--month", metavar="YYYY-MM",
        help=(
            "Report month for the PDF folder and the monthly consumption row "
            "(default: the current local month). Use it e.g. when running on "
            "the 1st of the month to record the previous month's closing."
        ),
    )
    month_group.add_argument(
        "-p", "--previous-month", action="store_true",
        help="Use the month before the current local month as the report month (e.g. September when run in October)",
    )
    extract_parser.add_argument(
        "--printer", metavar="NAME", action="append",
        help=(
            "Run only this printer (by its KYOCERA_PRINTERS name, case-insensitive). "
            "Repeatable to run several specific printers. Default: run every configured printer."
        ),
    )
    extract_parser.set_defaults(func=_cmd_extract)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not getattr(args, "command", None):
        parser.print_help()
        sys.exit(0)

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
