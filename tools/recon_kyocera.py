"""Phase 0 reconnaissance for the Kyocera Command Center RX portal.

Read-only: every non-GET request is aborted unless it is the login/logout
form post. Dumps HTML + screenshots of every frame at each step into
recon/<timestamp>/ so selectors can be confirmed against the real portal.

Env vars: KYOCERA_URL, KYOCERA_USER, KYOCERA_PASSWORD (a .env file is read too).
"""
import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ALLOWED_POST_FUNCS = {"authLogin", "authLogout"}
DESTRUCTIVE = re.compile(
    r"restablec|reinici|borrar|elimin|guardar|aplicar|enviar|reset|clear|delete|save|submit",
    re.IGNORECASE,
)


class Recon:
    def __init__(self, page, outdir: Path):
        self.page = page
        self.outdir = outdir
        self.step = 0
        self.blocked = []
        self.posts = []

    # -- safety -------------------------------------------------------------
    def guard(self, route, request):
        if request.method == "GET":
            return route.continue_()
        body = request.post_data or ""
        func = parse_qs(body).get("func", [""])[0]
        redacted = re.sub(r"(arg02_Password=)[^&]*", r"\1***", body)
        if func in ALLOWED_POST_FUNCS or "logout" in (request.url + body).lower():
            self.posts.append((request.url, redacted))
            return route.continue_()
        self.blocked.append((request.method, request.url, redacted))
        print(f"  !! BLOCKED {request.method} {request.url} body={redacted[:200]}")
        return route.abort()

    # -- helpers ------------------------------------------------------------
    def dump(self, label: str):
        self.step += 1
        prefix = f"{self.step:02d}_{label}"
        self.page.wait_for_timeout(1500)
        self.page.screenshot(path=self.outdir / f"{prefix}.png", full_page=True)
        lines = []
        for i, frame in enumerate(self.page.frames):
            lines.append(f"[{i}] name={frame.name!r} url={frame.url}")
            try:
                (self.outdir / f"{prefix}_frame{i}_{frame.name or 'main'}.html").write_text(
                    frame.content(), encoding="utf-8"
                )
            except Exception as exc:  # detached frame
                lines.append(f"    (content unavailable: {exc})")
            for el in frame.query_selector_all("a, button, input:not([type=hidden]), select"):
                try:
                    if not el.is_visible():
                        continue
                    text = (el.inner_text() or el.get_attribute("value") or "").strip()[:60]
                    attrs = {k: el.get_attribute(k) for k in ("id", "name", "type", "href", "onclick")}
                    attrs = {k: v for k, v in attrs.items() if v}
                    lines.append(f"    {el.evaluate('e => e.tagName')} {text!r} {attrs}")
                except Exception:
                    pass
        (self.outdir / f"{prefix}_controls.txt").write_text("\n".join(lines), encoding="utf-8")
        print(f"-- step {prefix}: {len(self.page.frames)} frames")
        for line in lines:
            if line.startswith("["):
                print("   ", line)

    def click_text(self, text: str, exact: bool = True):
        """Click the single visible element with this text in any frame; abort if ambiguous."""
        if DESTRUCTIVE.search(text):
            sys.exit(f"Refusing to click potentially destructive control: {text!r}")
        matches = []
        for frame in self.page.frames:
            loc = frame.get_by_text(text, exact=exact)
            for i in range(loc.count()):
                if loc.nth(i).is_visible():
                    matches.append((frame, loc.nth(i)))
        if len(matches) != 1:
            self.dump(f"ambiguous_{re.sub(r'\\W+', '_', text)}")
            sys.exit(f"Expected exactly one visible {text!r}, found {len(matches)}; aborting.")
        frame, target = matches[0]
        print(f"   click {text!r} in frame {frame.name!r}")
        target.click()
        self.page.wait_for_load_state("networkidle")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--open-first-counter", action="store_true",
                        help="Also click the first 'Contador' button to inspect the detail page")
    args = parser.parse_args()

    load_dotenv()
    url = os.environ.get("KYOCERA_URL")
    user = os.environ.get("KYOCERA_USER")
    password = os.environ.get("KYOCERA_PASSWORD")
    if not (url and user and password):
        sys.exit("Set KYOCERA_URL, KYOCERA_USER and KYOCERA_PASSWORD")

    outdir = Path("recon") / datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, slow_mo=300 if args.headed else 0)
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1400, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(20000)
        recon = Recon(page, outdir)
        page.route("**/*", recon.guard)
        page.on("framenavigated", lambda f: print(f"   nav frame={f.name!r} -> {f.url}"))
        jsdir = outdir / "js"
        jsdir.mkdir()

        def save_js(response):
            if "/js/jssrc/" in response.url and response.ok:
                name = re.sub(r"\W+", "_", response.url.split("/js/jssrc/")[1])[:150]
                try:
                    (jsdir / name).write_bytes(response.body())
                except Exception:
                    pass

        page.on("response", save_js)

        try:
            page.goto(url, wait_until="networkidle")
            recon.dump("home")

            recon.click_text("Inicio de sesión de administrador")
            wlm = page.frame(name="wlmframe")
            wlm.fill("#arg01_UserName", user)
            wlm.fill("#arg02_Password", password)
            wlm.click("input[name=Login]")
            page.wait_for_load_state("networkidle")
            recon.dump("after_login")

            recon.click_text("Configuración de administración")
            recon.dump("admin_settings")

            recon.click_text("Contabilidad de trabajos")
            recon.dump("job_accounting")

            listing = page.frame(name="panelusage")
            list_url = listing.url
            if args.open_first_counter:
                # Per-account "Contador" buttons live in the list frame; the first in DOM is row 0.
                button = listing.locator("input[name=btnCounter]").first
                print(f"   {listing.locator('input[name=btnCounter]').count()} btnCounter in list frame")
                button.click()
                page.wait_for_load_state("networkidle")
                recon.dump("counter_detail")

                # Page 2 of the list via URL (pagination is driven by arg7).
                listing = page.frame(name="panelusage")
                # The portal answers 404 to direct URLs unless the Referer is login.cgi.
                listing.goto(re.sub(r"arg7=\d+", "arg7=2", list_url), wait_until="networkidle",
                             referer=url.rstrip("/") + "/startwlm/login.cgi")
                recon.dump("job_accounting_page2")
        finally:
            print("\nCookies:", [c["name"] for c in context.cookies()])
            try:
                logout = page.frame(name="wlmframe").locator("#Logout")
                logout.click()
                page.wait_for_load_state("networkidle")
                recon.dump("after_logout")
            except BaseException as exc:
                print(f"   logout not confirmed: {exc}")
            print("Allowed POSTs:", *recon.posts, sep="\n  ")
            print("Blocked requests:", *recon.blocked, sep="\n  ")
            print(f"\nArtifacts in {outdir.resolve()}")
            browser.close()


if __name__ == "__main__":
    main()
