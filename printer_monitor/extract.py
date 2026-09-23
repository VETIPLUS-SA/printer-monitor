"""Orchestration for the `extract` subcommand.

Collects the full account list first (all pages), then walks: every named
account, the "other account" bucket (private id 101), and finally the
device-wide totals. Each of those three kinds of record is read inside its
own try/except so a single failure is logged and skipped instead of
aborting the whole run -- every account still gets a CSV row, with
status="error" and a message if something went wrong.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

from .parsing import ParseError
from .portal import (
    Account,
    KyoceraPortal,
    OTHER_ACCOUNT_NAME,
    OTHER_ACCOUNT_PRIVATE_ID,
    OTHER_ACCOUNT_ID,
    PortalError,
    TOTAL_ACCOUNT_ID,
)

logger = logging.getLogger(__name__)

# The "other account" bucket, always read explicitly via its well-known
# private id, regardless of whether the paginated account list happens to
# also surface it. This guarantees the row is always present.
_OTHER_ACCOUNT = Account(
    private_id=OTHER_ACCOUNT_PRIVATE_ID,
    public_id=OTHER_ACCOUNT_ID,
    name=OTHER_ACCOUNT_NAME,
)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# Characters Windows does not allow in file names.
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


_N_WITH_TILDE = ("ñ", "Ñ")


def _pdf_filename(name: str) -> str:
    """Account name as a Windows-safe, upper-cased file stem: accents are
    removed, except the letter ñ/Ñ, which is kept as-is.

    NFKD splits "i" (accented) into "i" + combining accent, which is then
    dropped; "n" (tilde) would decompose the same way ("n" + combining
    tilde), so it is special-cased character by character instead of being
    stripped.
    """
    kept = []
    for char in name:
        if char in _N_WITH_TILDE:
            kept.append(char)
            continue
        decomposed = unicodedata.normalize("NFKD", char)
        kept.append(decomposed.encode("ascii", "ignore").decode("ascii"))
    cleaned = "".join(kept)
    cleaned = _INVALID_FILENAME_CHARS.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .").upper()
    return cleaned or "SIN NOMBRE"


def _base_row(account_id: str, private_id: str, name: str, device_ip: str, printer_name: str) -> dict:
    return {
        "captured_at": _now_iso(),
        "device_ip": device_ip,
        "printer_name": printer_name,
        "account_id": account_id,
        "account_private_id": private_id,
        "account_name": name,
    }


def _pdf_path(outdir: Path, device_ip: str, month: str, account_id: str, name: str, taken: set[str]) -> Path:
    """PDFs go to <outdir>/pdf/<device ip>/<YYYY-MM>/<NAME>.pdf; the month
    is the report month (see --month), and the account id is only appended
    when two accounts share a name within that month's folder."""
    stem = _pdf_filename(name)
    if stem in taken:
        stem = f"{stem} ({account_id})"
    taken.add(stem)
    return outdir / "pdf" / device_ip / month / f"{stem}.pdf"


def _read_account_row(
    portal: KyoceraPortal,
    account: Account,
    device_ip: str,
    printer_name: str,
    month: str,
    outdir: Optional[Path],
    save_pdf: bool,
    pdf_names: set[str],
    check_title: bool = True,
) -> dict:
    row = _base_row(account.public_id, account.private_id, account.name, device_ip, printer_name)
    try:
        counters = portal.read_counters(account, check_title=check_title)
        row.update(counters)
        row["status"] = "ok"
        row["error"] = ""
    except (PortalError, ParseError) as exc:
        logger.error("Failed to read account %s (%s): %s", account.public_id, account.name, exc)
        row["status"] = "error"
        row["error"] = str(exc)
        if outdir is not None:
            try:
                portal.capture_diagnostics(outdir, account.public_id)
            except Exception as diag_exc:  # noqa: BLE001 - diagnostics must never mask the original error
                logger.warning("Diagnostics capture also failed for %s: %s", account.public_id, diag_exc)
        return row

    if save_pdf and outdir is not None:
        try:
            portal.save_pdf(_pdf_path(outdir, device_ip, month, account.public_id, account.name, pdf_names))
        except Exception as pdf_exc:  # noqa: BLE001 - a PDF failure must not fail the account's CSV data
            logger.warning("PDF save failed for %s (CSV data kept): %s", account.public_id, pdf_exc)

    return row


def _read_totals_row(
    portal: KyoceraPortal,
    device_ip: str,
    printer_name: str,
    month: str,
    outdir: Optional[Path],
    save_pdf: bool,
    pdf_names: set[str],
) -> dict:
    row = _base_row(TOTAL_ACCOUNT_ID, "", "Contabilidad total de trabajos", device_ip, printer_name)
    try:
        totals = portal.read_totals()
        row.update(totals)
        row["status"] = "ok"
        row["error"] = ""
    except (PortalError, ParseError) as exc:
        logger.error("Failed to read device totals: %s", exc)
        row["status"] = "error"
        row["error"] = str(exc)
        if outdir is not None:
            try:
                portal.capture_diagnostics(outdir, TOTAL_ACCOUNT_ID)
            except Exception as diag_exc:  # noqa: BLE001
                logger.warning("Diagnostics capture also failed for totals: %s", diag_exc)
        return row

    if save_pdf and outdir is not None:
        try:
            portal.save_pdf(_pdf_path(outdir, device_ip, month, TOTAL_ACCOUNT_ID, row["account_name"], pdf_names))
        except Exception as pdf_exc:  # noqa: BLE001
            logger.warning("PDF save failed for device totals (CSV data kept): %s", pdf_exc)

    return row


def run_extraction(
    portal: KyoceraPortal,
    device_ip: str,
    outdir: Optional[Path],
    save_pdf: bool = False,
    month: Optional[str] = None,
    printer_name: str = "default",
) -> list[dict]:
    """Walk every account plus the "other account" and device totals,
    returning one row dict per record.

    `outdir=None` means dry-run: no diagnostics and no PDFs are written
    (the CSV itself is written by the caller, also skipped in dry-run).

    `month` (YYYY-MM) is the report month used for the PDF folder; it
    defaults to the current local month when not given.

    `printer_name` identifies this printer (Settings.name) and is stamped
    onto every row.
    """
    if month is None:
        month = datetime.now().strftime("%Y-%m")
    accounts = portal.list_accounts()
    # The "other account" bucket is always read explicitly (see
    # _OTHER_ACCOUNT above); exclude it here to avoid a duplicate row if
    # it also happens to appear in the paginated list.
    regular_accounts = [a for a in accounts if a.private_id != OTHER_ACCOUNT_PRIVATE_ID]

    rows: list[dict] = []
    pdf_names: set[str] = set()
    total = len(regular_accounts)

    for index, account in enumerate(regular_accounts, start=1):
        logger.info("Account %d of %d: %s (%s)", index, total, account.name, account.public_id)
        rows.append(
            _read_account_row(portal, account, device_ip, printer_name, month, outdir, save_pdf, pdf_names)
        )

    logger.info("Reading 'other account' totals (private id %s)", OTHER_ACCOUNT_PRIVATE_ID)
    rows.append(
        _read_account_row(
            portal, _OTHER_ACCOUNT, device_ip, printer_name, month, outdir, save_pdf, pdf_names, check_title=False
        )
    )

    logger.info("Reading device-wide totals")
    rows.append(_read_totals_row(portal, device_ip, printer_name, month, outdir, save_pdf, pdf_names))

    return rows
