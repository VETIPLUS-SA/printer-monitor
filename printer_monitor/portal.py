"""Playwright automation for the Kyocera Command Center RX portal.

Read-only by construction:
  * Every request goes through printer_monitor.safety.SafetyGuard, which
    aborts anything that isn't an explicitly allowlisted GET or the
    login/logout form POST.
  * After login, the only click this module performs is on #Logout. Every
    other navigation is frame.goto() to a URL built entirely by this
    module's own code (see docs/fase0-hallazgos.md for the confirmed URL
    shapes) -- there is no select_option, no checkbox, no form submit, no
    keyboard input anywhere else in this file.

The portal's embedded web server is fragile (bursts of requests can cause
a "socket hang up"), so every navigation is spaced out by
Settings.delay_ms and retried with backoff on network errors/timeouts/5xx.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import (
    Browser,
    Error as PlaywrightError,
    Frame,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .config import Settings
from .parsing import map_rows, validate_title
from .safety import SafetyGuard

logger = logging.getLogger(__name__)

# Backoff delays (seconds) between retry attempts for a failed navigation.
RETRY_DELAYS_S = (2, 4, 8)

# Query string shared by every per-account/detail URL (arg7=1 means "page 1
# of the detail view itself", not the account list page).
DETAIL_Q = "arg2=0&arg3=&arg4=0&arg5=&arg6=&arg7=1&arg8=0&arg9=&arg10="

ACCOUNTS_PER_PAGE = 10

# The "other account" bucket the portal keeps for jobs not tied to a named
# account. It has a fixed, well-known private id.
OTHER_ACCOUNT_PRIVATE_ID = "101"
OTHER_ACCOUNT_ID = "OTHER"
OTHER_ACCOUNT_NAME = "Otra cuenta"

# Synthetic account_id used for the device-wide totals row (no arg11).
TOTAL_ACCOUNT_ID = "TOTAL"

# Rows whose first cell is one of these are table headers, not data. The
# browser-side extraction below already filters these out; map_rows() in
# parsing.py also skips them defensively.
_HEADER_LABELS = {"Función", "Uso/MÁX.", "Contador"}

_ROW_EXTRACT_JS = """() => {
    function isVisible(el) {
        return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    }
    // document.title is an internal page code (e.g. "P163_..."); the visible
    // heading is the first body line shaped "<account name> - <section>".
    const lines = (document.body.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
    const title = lines.find(l => l.includes(' - ')) || '';
    const rows = [];
    for (const tr of document.querySelectorAll('tr')) {
        if (!isVisible(tr)) continue;
        // Layout rows wrap nested tables; only leaf rows hold one counter each.
        if (tr.querySelector('tr, select, input')) continue;
        const cells = Array.from(tr.children)
            .filter(cell => cell.matches('td, th'))
            .map(cell => (cell.innerText || '').trim())
            .filter(text => text !== '');
        if (cells.length < 3) continue;
        rows.push(cells);
    }
    return { title, rows };
}"""

_ACCOUNT_LIST_EXTRACT_JS = """() => ({
    total: MngSet_JobAcc_JobAccLstModel.get('searchResult'),
    privateIds: MngSet_JobAcc_JobAccLstModel.get('sDeptPrivateID'),
    publicIds: MngSet_JobAcc_JobAccLstModel.get('sDeptPublicID'),
    names: MngSet_JobAcc_JobAccLstModel.get('sDeptName'),
})"""


class PortalError(Exception):
    """Raised for unrecoverable portal errors: login failure, a 404 where
    a page was expected, an account-count mismatch, etc."""


@dataclass(frozen=True)
class Account:
    private_id: str
    public_id: str
    name: str


class KyoceraPortal:
    """Context manager: launches the browser and logs in on enter, logs
    out and closes the browser on exit (even if the body of the `with`
    block raises)."""

    def __init__(self, settings: Settings, headed: bool = False):
        self.settings = settings
        self.headed = headed
        self.guard = SafetyGuard()
        self.base_url = settings.url.rstrip("/")
        self.login_url = f"{self.base_url}/startwlm/login.cgi"

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    # -- lifecycle --------------------------------------------------------
    def __enter__(self) -> "KyoceraPortal":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=not self.headed)
        context = self._browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1400, "height": 1000},
        )
        self.page = context.new_page()
        self.page.set_default_timeout(self.settings.timeout_ms)
        self.page.route("**/*", self.guard.handle_route)
        try:
            self._login()
        except BaseException:
            # __exit__ is not called when __enter__ raises: close the session here.
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self.page is not None:
                self._logout()
        finally:
            if self._browser is not None:
                self._browser.close()
            if self._playwright is not None:
                self._playwright.stop()

    # -- login / logout -----------------------------------------------------
    def _login(self) -> None:
        logger.info("Navigating to %s", self.base_url)
        self.page.goto(self.base_url + "/", wait_until="networkidle")

        wlm = self.page.frame(name="wlmframe")
        if wlm is None:
            raise PortalError("wlmframe not found on the home page")

        wlm.click("#aadminloginid")
        wlm.locator("#arg01_UserName").wait_for(state="visible")
        wlm.fill("#arg01_UserName", self.settings.user)
        wlm.fill("#arg02_Password", self.settings.password)
        wlm.click("input[name=Login]")
        self.page.wait_for_load_state("networkidle")

        # wlmframe reloads from login.cgi after the POST; wait for the logged-in menu.
        try:
            self.page.frame(name="wlmframe").locator("#Logout").wait_for(state="visible")
        except PlaywrightError as exc:
            raise PortalError(
                "Login failed: #Logout did not appear in wlmframe after the login attempt "
                "(check KYOCERA_USER/KYOCERA_PASSWORD)"
            ) from exc
        logger.info("Login successful")

    def _logout(self) -> None:
        wlm = self.page.frame(name="wlmframe")
        if wlm is None:
            logger.warning("wlmframe not found during logout; skipping explicit logout")
            return
        logout_locator = wlm.locator("#Logout")
        if logout_locator.count() == 0:
            logger.warning("#Logout not present during logout; session may already be closed")
            return
        try:
            logout_locator.first.click()
            self.page.wait_for_load_state("networkidle")
            logger.info("Logout successful")
        except PlaywrightError as exc:
            logger.warning("Logout click failed (continuing to close the browser): %s", exc)

    # -- navigation with retry ----------------------------------------------
    def _goto_with_retry(self, frame: Frame, url: str, *, referer: Optional[str] = None) -> None:
        attempts = len(RETRY_DELAYS_S) + 1
        last_exc: Optional[BaseException] = None

        for attempt in range(1, attempts + 1):
            try:
                response = frame.goto(url, wait_until="networkidle", referer=referer)
            except PlaywrightTimeoutError as exc:
                last_exc = exc
                logger.warning("Timeout navigating to %s (attempt %d/%d): %s", url, attempt, attempts, exc)
            except PlaywrightError as exc:
                last_exc = exc
                logger.warning("Network error navigating to %s (attempt %d/%d): %s", url, attempt, attempts, exc)
            else:
                if response is not None and response.status == 404:
                    # Not retryable: this means the request is missing the
                    # required Referer header, or the URL itself is wrong.
                    raise PortalError(
                        f"404 Not Found: {url} (missing Referer to {self.login_url}?)"
                    )
                if response is not None and response.status >= 500:
                    last_exc = PortalError(f"HTTP {response.status}: {url}")
                    logger.warning("Server error navigating to %s (attempt %d/%d): %s", url, attempt, attempts, last_exc)
                else:
                    if self.settings.delay_ms:
                        self.page.wait_for_timeout(self.settings.delay_ms)
                    return

            if attempt < attempts:
                delay = RETRY_DELAYS_S[attempt - 1]
                logger.info("Retrying navigation to %s in %ss", url, delay)
                time.sleep(delay)

        raise PortalError(f"Navigation to {url} failed after {attempts} attempts: {last_exc}")

    # -- table extraction -----------------------------------------------------
    def _read_table(self, frame: Frame) -> tuple[list[list[str]], str]:
        data = frame.evaluate(_ROW_EXTRACT_JS)
        title = data.get("title", "") or ""
        raw_rows = data.get("rows", []) or []
        rows = [row for row in raw_rows if not (row and row[0] in _HEADER_LABELS)]
        return rows, title

    # -- accounts -------------------------------------------------------------
    def list_accounts(self) -> list[Account]:
        """Walk every page of the job-accounting account list and return
        the full, deduplicated set of accounts. Raises PortalError if the
        collected count doesn't match the portal-reported total."""
        frame = self.page.frame(name="panelusage")
        if frame is None:
            raise PortalError("panelusage frame not found; is the portal logged in?")

        accounts: dict[str, Account] = {}
        total: Optional[int] = None
        page_num = 1

        while True:
            url = (
                f"{self.base_url}/mngset/jobset/MngSet_JobAcc_JobAccLst.htm"
                f"?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=&arg7={page_num}&arg8=0&arg9="
            )
            self._goto_with_retry(frame, url, referer=self.login_url)
            data = frame.evaluate(_ACCOUNT_LIST_EXTRACT_JS)

            if total is None:
                total = int(data["total"])
                logger.info("Account list reports %d account(s) total", total)

            private_ids = data.get("privateIds") or []
            public_ids = data.get("publicIds") or []
            names = data.get("names") or []

            if not private_ids:
                break

            for priv, pub, name in zip(private_ids, public_ids, names):
                accounts[str(priv)] = Account(private_id=str(priv), public_id=str(pub), name=str(name))

            logger.info("Page %d: %d/%d account(s) collected so far", page_num, len(accounts), total)

            if len(accounts) >= total:
                break
            page_num += 1

        if total is not None and len(accounts) != total:
            raise PortalError(
                f"Account count mismatch: collected {len(accounts)} account(s), "
                f"portal reports searchResult={total}"
            )

        return sorted(accounts.values(), key=lambda a: a.public_id)

    # -- counters ---------------------------------------------------------------
    def read_counters(self, account: Account, check_title: bool = True) -> dict[str, str]:
        """Read every counter for one account (print by function, print by
        layout, scan, fax) and return them merged into a single dict of
        output-column -> value."""
        device = self.page.frame(name="device")
        panelusage = self.page.frame(name="panelusage")
        paper = self.page.frame(name="paper")
        if device is None or panelusage is None or paper is None:
            raise PortalError("device/panelusage/paper frame not found; is the portal logged in?")

        expected_name = account.name if check_title else None
        result: dict[str, str] = {}

        # Layout view first so the device frame ends on the by-function view (used by --pdf).
        url = f"{self.base_url}/mngset/jobset/MngSet_JobAcc_EchJobPrnCnt.htm?arg1=2&{DETAIL_Q}&arg11={account.private_id}"
        self._goto_with_retry(device, url, referer=self.login_url)
        rows, title = self._read_table(device)
        validate_title(title, expected_name)
        result.update(map_rows("print_layout", rows))

        url = f"{self.base_url}/mngset/jobset/MngSet_JobAcc_EchJobPrnCnt.htm?arg1=0&{DETAIL_Q}&arg11={account.private_id}"
        self._goto_with_retry(device, url, referer=self.login_url)
        rows, title = self._read_table(device)
        validate_title(title, expected_name)
        result.update(map_rows("print_function", rows))

        url = f"{self.base_url}/mngset/jobset/MngSet_JobAcc_EchJobScnCnt.htm?arg1=1&{DETAIL_Q}&arg11={account.private_id}"
        self._goto_with_retry(panelusage, url, referer=self.login_url)
        rows, title = self._read_table(panelusage)
        validate_title(title, expected_name)
        result.update(map_rows("scan", rows))

        url = f"{self.base_url}/mngset/jobset/MngSet_JobAcc_EchJobFaxCnt.htm?arg1=1&{DETAIL_Q}&arg11={account.private_id}"
        self._goto_with_retry(paper, url, referer=self.login_url)
        rows, title = self._read_table(paper)
        validate_title(title, expected_name)
        result.update(map_rows("fax", rows))

        return result

    def read_totals(self) -> dict[str, str]:
        """Read the device-wide totals (no arg11), across all accounts."""
        device = self.page.frame(name="device")
        panelusage = self.page.frame(name="panelusage")
        paper = self.page.frame(name="paper")
        if device is None or panelusage is None or paper is None:
            raise PortalError("device/panelusage/paper frame not found; is the portal logged in?")

        result: dict[str, str] = {}

        # Layout view first so the device frame ends on the by-function view (used by --pdf).
        url = f"{self.base_url}/mngset/jobset/MngSet_JobAcc_TotPrnCnt.htm?arg1=2&{DETAIL_Q}"
        self._goto_with_retry(device, url, referer=self.login_url)
        rows, title = self._read_table(device)
        validate_title(title, None)
        result.update(map_rows("print_layout", rows))

        url = f"{self.base_url}/mngset/jobset/MngSet_JobAcc_TotPrnCnt.htm?arg1=0&{DETAIL_Q}"
        self._goto_with_retry(device, url, referer=self.login_url)
        rows, title = self._read_table(device)
        validate_title(title, None)
        result.update(map_rows("print_function", rows))

        url = f"{self.base_url}/mngset/jobset/MngSet_JobAcc_TotScnCnt.htm?arg1=1&{DETAIL_Q}"
        self._goto_with_retry(panelusage, url, referer=self.login_url)
        rows, title = self._read_table(panelusage)
        validate_title(title, None)
        result.update(map_rows("scan", rows))

        url = f"{self.base_url}/mngset/jobset/MngSet_JobAcc_TotFaxCnt.htm?arg1=1&{DETAIL_Q}"
        self._goto_with_retry(paper, url, referer=self.login_url)
        rows, title = self._read_table(paper)
        validate_title(title, None)
        result.update(map_rows("fax", rows))

        return result

    # -- pdf / diagnostics --------------------------------------------------------
    def save_pdf(self, path: Path) -> None:
        """Save the current page as a PDF. Only works in headless
        Chromium; the caller is responsible for not calling this in
        --headed mode."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.pdf(path=str(path))

    def capture_diagnostics(self, outdir: Path, account_id: str) -> Path:
        """Save a screenshot and the HTML of every frame, for post-mortem
        debugging of a failed account. Never raises: failures here are
        logged and swallowed so they don't mask the original error."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        diag_dir = Path(outdir) / "diagnostics" / timestamp
        diag_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.page.screenshot(path=str(diag_dir / f"{account_id}_screenshot.png"), full_page=True)
        except PlaywrightError as exc:
            logger.warning("Could not capture screenshot for %s: %s", account_id, exc)

        for frame in self.page.frames:
            name = frame.name or "main"
            try:
                html = frame.content()
                (diag_dir / f"{account_id}_{name}.html").write_text(html, encoding="utf-8")
            except PlaywrightError as exc:
                logger.warning("Could not capture frame %r content for %s: %s", name, account_id, exc)

        return diag_dir
