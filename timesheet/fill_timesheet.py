#!/usr/bin/env python3
"""
iTime Timesheet Automation

Steps executed (for TARGET_DATE, default = yesterday):
  1. Navigate to iTime Timesheet page and take screenshot
  2. Identify yesterday's date column
  3. Fill 8 hours for the project entry
  4. Fill 1 hour for the non-project entry
  5. Save the timesheet
  6. Click Regularize, fill 9 hours with comment 'wfh' and Save

Required env vars (one of):
  ITIME_SESSION       - base64-encoded auth_state.json (from save_session.py)
  ITIME_SESSION_FILE  - path to a file containing the base64 value
                        defaults to timesheet/session.txt if neither is set

Optional env vars:
  TARGET_DATE         - date to fill in YYYY-MM-DD (default: yesterday)
  HEADLESS            - "false" to watch browser (default: true)
  SCREENSHOTS_DIR     - where to save debug PNGs (default: timesheet/screenshots)
"""

import base64
import gzip
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────
def _load_session() -> str:
    if os.environ.get("ITIME_SESSION"):
        return os.environ["ITIME_SESSION"]
    session_file = Path(os.environ.get("ITIME_SESSION_FILE", "timesheet/session.txt"))
    if session_file.exists():
        return session_file.read_text(encoding="utf-8").strip()
    raise RuntimeError(
        "Session not found. Either set ITIME_SESSION env var, "
        "set ITIME_SESSION_FILE to your session file path, "
        "or place the base64 value in timesheet/session.txt"
    )

SESSION_B64     = _load_session()
HEADLESS        = os.environ.get("HEADLESS", "true").lower() != "false"
SCREENSHOTS_DIR = Path(os.environ.get("SCREENSHOTS_DIR", "timesheet/screenshots"))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

_raw_date   = os.environ.get("TARGET_DATE", "")
TARGET_DATE = date.fromisoformat(_raw_date) if _raw_date else date.today() - timedelta(days=1)

TIMESHEET_URL = "https://itime.ltimindtree.com/#/Timesheet"
TIMEOUT       = 30_000
DAY_NAMES     = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ── Screenshot helper ─────────────────────────────────────────────────────────
def shot(page, step: str):
    path = SCREENSHOTS_DIR / f"{step}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  [screenshot] {path}")


# ── Wait for app to load ──────────────────────────────────────────────────────
def wait_for_app(page):
    print("  Waiting for app to load...")
    try:
        page.wait_for_selector("text=LOADING", state="hidden", timeout=30_000)
    except PWTimeout:
        pass
    page.wait_for_timeout(3_000)


# ── Dismiss any popup/dialog ──────────────────────────────────────────────────
def dismiss_popup(page):
    for sel in ["button:has-text('Ok')", "button:has-text('OK')", "button:has-text('Close')"]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2_000):
                btn.click()
                page.wait_for_timeout(1_000)
                print("  Dismissed popup.")
                return
        except Exception:
            continue


# ── Session check ─────────────────────────────────────────────────────────────
def assert_logged_in(page):
    try:
        page.wait_for_selector("input[type='email'], input[name='loginfmt']", timeout=5_000)
        shot(page, "99_session_expired")
        raise RuntimeError(
            "Session expired. Run  python timesheet/save_session.py  locally "
            "to capture a fresh session and update the ITIME_SESSION secret."
        )
    except PWTimeout:
        pass


# ── Column index for target date (grid is Sunday-first) ───────────────────────
def day_column() -> int:
    # Grid columns: Sun=2, Mon=3, Tue=4, Wed=5, Thu=6, Fri=7, Sat=8
    # Python weekday(): Mon=0 … Sun=6
    return (TARGET_DATE.weekday() + 1) % 7 + 2


# ── Fill a specific input cell by row index and column ───────────────────────
def fill_cell(page, row_nth: int, col: int, value: str, label: str) -> bool:
    try:
        row = page.locator("tr:has(input)").nth(row_nth)
        cell = row.locator(f"td:nth-child({col})").first
        inp  = cell.locator("input").first
        if inp.is_visible(timeout=5_000):
            inp.triple_click()
            inp.fill(value)
            inp.press("Tab")
            page.wait_for_timeout(500)
            print(f"  ✓ Filled {value}hr → {label}")
            return True
    except Exception as e:
        print(f"  ✗ Could not fill {label}: {e}")
    return False


# ── Step 1: Navigate ──────────────────────────────────────────────────────────
def step_navigate(page):
    print(f"\nStep 1 — Navigate to Timesheet page")
    page.goto(TIMESHEET_URL, wait_until="networkidle")
    wait_for_app(page)
    shot(page, "01_timesheet_loaded")
    assert_logged_in(page)

    weeks_back = (date.today() - TARGET_DATE).days // 7
    if weeks_back > 0:
        print(f"  Navigating {weeks_back} week(s) back...")
        for _ in range(weeks_back):
            for sel in ["button[aria-label*='previous' i]", "button[aria-label*='prev' i]",
                        ".prev-week", "[class*='prev-week']"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2_000):
                        btn.click()
                        page.wait_for_timeout(1_500)
                        break
                except Exception:
                    continue

    shot(page, "02_correct_week")
    print(f"  Target date: {TARGET_DATE} ({DAY_NAMES[TARGET_DATE.weekday()]})")


# ── Step 2 & 3: Fill hours ────────────────────────────────────────────────────
def step_fill_timesheet(page):
    col = day_column()
    print(f"\nStep 3 — Fill 8 hours (project) at column {col}")
    fill_cell(page, 0, col, "8", "project row")

    print(f"\nStep 4 — Fill 1 hour (non-project) at column {col}")
    fill_cell(page, -1, col, "1", "non-project row")

    shot(page, "03_hours_filled")

    print(f"\nStep 5 — Save timesheet")
    page.locator("button:has-text('Save')").first.click()
    page.wait_for_timeout(2_000)
    dismiss_popup(page)
    shot(page, "04_timesheet_saved")


# ── Step 4: Regularize ────────────────────────────────────────────────────────
def step_regularize(page):
    print(f"\nStep 6 — Open Regularize")

    # The Regularize button is in the Attendance section header on the same page
    clicked = False
    for sel in [
        "button:has-text('Regularize')",
        "a:has-text('Regularize')",
        "span:has-text('Regularize')",
        "[class*='regularize' i]",
        "button:has-text('Regulariz')",
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=3_000):
                btn.click()
                page.wait_for_timeout(2_000)
                clicked = True
                print("  ✓ Clicked Regularize button")
                break
        except Exception:
            continue

    if not clicked:
        print("  ✗ Could not find Regularize button")

    shot(page, "05_regularize_open")

    # Fill hours, reason, comment in the regularization form/modal
    print("  Filling 9 hours WFH...")
    for sel in ["input[placeholder*='hour' i]", "input[name*='hour' i]",
                "[class*='hour'] input", "input[type='number']"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3_000):
                el.triple_click()
                el.fill("9")
                print("  ✓ Filled 9hr")
                break
        except Exception:
            continue

    for sel in ["select[name*='reason' i]", "select", "mat-select",
                "[aria-label*='reason' i]", "[placeholder*='reason' i]"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3_000):
                tag = el.evaluate("e => e.tagName").upper()
                if tag == "SELECT":
                    el.select_option(label="Work From Home")
                else:
                    el.click()
                    page.wait_for_timeout(500)
                    page.locator("mat-option:has-text('Work From Home'), "
                                 "li:has-text('Work From Home'), "
                                 "option:has-text('Work From Home')").first.click()
                print("  ✓ Selected Work From Home")
                break
        except Exception:
            continue

    for sel in ["textarea", "input[placeholder*='comment' i]",
                "input[name*='remark' i]", "input[placeholder*='remark' i]"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3_000):
                el.triple_click()
                el.fill("wfh")
                print("  ✓ Filled comment: wfh")
                break
        except Exception:
            continue

    shot(page, "06_regularize_filled")

    page.locator("button:has-text('Save')").first.click()
    page.wait_for_timeout(2_000)
    dismiss_popup(page)
    shot(page, "07_regularize_saved")
    print("  Regularization saved.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print(f"iTime Timesheet — {TARGET_DATE} ({DAY_NAMES[TARGET_DATE.weekday()]})")
    print("=" * 55)

    decoded = base64.b64decode(SESSION_B64.encode())
    try:
        session_json = gzip.decompress(decoded)
    except OSError:
        session_json = decoded
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="wb") as f:
        f.write(session_json)
        session_path = f.name

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(
            storage_state=session_path,
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()
        page.set_default_timeout(TIMEOUT)

        try:
            step_navigate(page)
            step_fill_timesheet(page)
            step_regularize(page)
            print("\n✓ All done!")
        except Exception as exc:
            shot(page, "99_error")
            print(f"\n✗ ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
