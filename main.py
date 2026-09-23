"""CLI entry point for the Kyocera portal job-counter extractor.

Subcommands:
  extract   Log in, read every account's job-accounting counters plus the
            "other account" bucket and the device-wide totals, and write
            them to a CSV.

Phase 2 (monthly delta between snapshots) and Phase 3 (report generation)
are intentionally not implemented yet -- see brief.md.

Exit codes (extract):
  0  every account read successfully
  1  configuration error, fatal portal error, or at least one account
     failed (its row is still in the CSV with status=error)
  2  the safety guard blocked at least one request during the run
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from printer_monitor.config import ConfigError, load_settings
from printer_monitor.extract import run_extraction
from printer_monitor.output import write_csv
from printer_monitor.portal import KyoceraPortal, PortalError


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


def _cmd_extract(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    outdir = Path(args.outdir or settings.outdir)
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

    portal = KyoceraPortal(settings, headed=args.headed)
    try:
        with portal:
            rows = run_extraction(
                portal,
                device_ip=settings.url,
                outdir=None if dry_run else outdir,
                save_pdf=save_pdf,
            )
    except PortalError as exc:
        logger.error("Fatal portal error: %s", exc)
        return 1

    if portal.guard.has_blocked:
        logger.error(
            "SAFETY WARNING: %d request(s) were blocked by the safety guard during this run. "
            "Nothing destructive was executed, but review the log above -- the run may be incomplete.",
            len(portal.guard.blocked),
        )
        return 2

    any_errors = any(row.get("status") == "error" for row in rows)

    if dry_run:
        logger.info("Dry run complete: %d record(s) walked, no files written", len(rows))
    else:
        csv_path = write_csv(rows, outdir)
        logger.info("Wrote %s", csv_path)

    if any_errors:
        logger.warning("Run completed with errors on at least one account; see status/error columns")
        return 1
    return 0


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
    extract_parser.set_defaults(func=_cmd_extract)

    # Reserved for future phases (not implemented yet):
    #   subparsers.add_parser("delta", help="Compute the period consumption between two snapshots")
    #   subparsers.add_parser("report", help="Generate a delivery report from a delta CSV")

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
