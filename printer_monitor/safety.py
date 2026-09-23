"""Read-only safety guard for the Kyocera Command Center RX automation.

This module is the single source of truth for which network requests the
automation is allowed to make against the production printer. Its purpose
is to make it structurally impossible for the script to reset job
counters, delete accounts, or otherwise mutate printer state -- even if a
bug elsewhere in the code tries to build a destructive URL.

Design:
  * check_request() is a pure function (no I/O, no Playwright types) so it
    can be unit tested exhaustively against every URL the extractor
    builds, plus every known destructive URL, without a browser or a
    network connection.
  * SafetyGuard wraps check_request() into a Playwright route handler that
    aborts blocked requests, logs them, and records them so the caller can
    fail the run loudly if the guard ever had to intervene.

See docs/fase0-hallazgos.md for the confirmed portal URLs this guard is
built against.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# Non-GET requests are allowed only for the admin login form post, and only
# with one of these exact `func` values.
ALLOWED_POST_PATH = "/startwlm/login.cgi"
ALLOWED_POST_FUNCS = {"authLogin", "authLogout"}

# Belt-and-braces deny list: any path matching this, on ANY method, is
# blocked regardless of every other rule below. This intentionally overlaps
# with the mngset allowlist (e.g. it also catches MngSet_JobAcc_ResetCnt and
# MngSet_Acc_DeleteRslt), and is kept broad on purpose: it also protects
# paths that are not under /mngset/ at all, such as a hypothetical direct
# reset endpoint elsewhere on the portal.
DENY_PATTERN = re.compile(
    r"reset|delete|del_|clear|restor|init|newacc|rslt|_err",
    re.IGNORECASE,
)

# GET-only static assets (no query-driven server logic behind them).
STATIC_ASSET_PATTERN = re.compile(r"\.(png|gif|jpe?g|ico|svg|css)$", re.IGNORECASE)

# Under /mngset/ (both the pages themselves and their Knockout model /
# view_model JS files), only these exact base names are allowed. Anything
# else under mngset is blocked -- this is the primary defense; DENY_PATTERN
# above is the secondary one.
MNGSET_ALLOWED_BASENAMES = {
    "MngSet_JobAcc_JobAccLst",
    "MngSet_JobAcc_JobAccSet",
    "MngSet_JobAcc_EchJobPrnCnt",
    "MngSet_JobAcc_EchJobScnCnt",
    "MngSet_JobAcc_EchJobFaxCnt",
    "MngSet_JobAcc_TotPrnCnt",
    "MngSet_JobAcc_TotScnCnt",
    "MngSet_JobAcc_TotFaxCnt",
}
_MNGSET_ALLOWED_LOWER = {name.lower() for name in MNGSET_ALLOWED_BASENAMES}

# Used to redact credentials from logged request bodies.
_PASSWORD_PATTERN = re.compile(r"(arg02_Password=)[^&]*")


def _basename(path: str) -> str:
    """Return the last path segment without any dotted suffix.

    This treats plain pages (`Foo.htm`) and Knockout model / view_model
    files (`Foo.model.htm`, `Foo.view_model.htm`) the same way, since both
    share the same first token before the first dot.
    """
    last_segment = path.rsplit("/", 1)[-1]
    return last_segment.split(".", 1)[0]


def _is_under_mngset(path: str) -> bool:
    return any(segment.lower() == "mngset" for segment in path.split("/"))


def check_request(method: str, url: str, post_data: str | None) -> tuple[bool, str]:
    """Decide whether a request is allowed to proceed.

    Pure function: no I/O, no Playwright objects, so every rule can be
    unit tested directly against literal URLs and bodies.

    Returns (allowed, reason).
    """
    parsed = urlparse(url)
    path = parsed.path
    method_upper = (method or "GET").upper()

    # Static images/styles cannot change printer state; the portal names some
    # icons after actions (e.g. /images/btn_del_common.png), which would
    # otherwise trip DENY_PATTERN.
    if method_upper == "GET" and STATIC_ASSET_PATTERN.search(path):
        return True, f"static asset: {path}"

    deny_match = DENY_PATTERN.search(path)
    if deny_match:
        return False, f"path matches deny pattern {deny_match.group(0)!r}: {path}"

    if method_upper != "GET":
        if method_upper != "POST":
            return False, f"non-GET/POST method {method_upper}: {path}"
        if path != ALLOWED_POST_PATH:
            return False, f"POST to non-login path: {path}"
        func = parse_qs(post_data or "").get("func", [""])[0]
        if func not in ALLOWED_POST_FUNCS:
            return False, f"POST to login.cgi with disallowed func={func!r}"
        return True, f"login form POST func={func}"

    if _is_under_mngset(path):
        base = _basename(path)
        if base.lower() not in _MNGSET_ALLOWED_LOWER:
            return False, f"mngset path not in read-only allowlist: {path}"
        return True, f"mngset allowlisted page: {base}"

    return True, "default allow (GET, not under mngset)"


def redact(body: str | None) -> str:
    """Mask the admin password in a request body before logging it."""
    if not body:
        return ""
    return _PASSWORD_PATTERN.sub(r"\1***", body)


@dataclass
class SafetyGuard:
    """Playwright route handler backed by check_request().

    Install with `page.route("**/*", guard.handle_route)`. Tracks every
    blocked request in `blocked` so the caller can detect at the end of a
    run whether the guard ever had to intervene (and exit non-zero if so).
    """

    blocked: list[tuple[str, str, str]] = field(default_factory=list)

    def handle_route(self, route, request) -> None:
        allowed, reason = check_request(request.method, request.url, request.post_data)
        if allowed:
            route.continue_()
            return
        redacted_body = redact(request.post_data)
        logger.error(
            "SAFETY BLOCK %s %s reason=%s body=%s",
            request.method,
            request.url,
            reason,
            redacted_body,
        )
        self.blocked.append((request.method, request.url, reason))
        route.abort()

    @property
    def has_blocked(self) -> bool:
        return bool(self.blocked)
