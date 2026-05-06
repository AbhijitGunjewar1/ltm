#!/usr/bin/env python3
"""
iTime Timesheet Automation

Steps executed (for TARGET_DATE, default = yesterday):
  1. Navigate to iTime Timesheet page and take screenshot
  2. Identify yesterday's date column
  3. Fill 8 hours for the project entry
  4. Fill 1 hour for the non-project entry
  5. Save the timesheet
  6. Open Regularization, fill 9 hours with comment 'wfh' and Save

Required env vars (one of):
  ITIME_SESSION       - base64-encoded auth_state.json (from save_session.py)
  ITIME_SESSION_FILE  - path to a file containing the base64 value (avoids Windows env var size limits)
                        defaults to timesheet/session.txt if neither env var is set

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

SESSION_B64 = _load_session()
HEADLESS        = os.environ.get("HEADLESS", "true").lower() != "false"
SCREENSHOTS_DIR = Path(os.environ.get("SCREENSHOTS_DIR", "timesheet/screenshots"))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

_raw_date   = os.environ.get("TARGET_DATE", "")
TARGET_DATE = date.fromisoformat(_raw_date) if _raw_date else date.today() - timedelta(days=1)

TIMESHEET_URL   = "https://itime.ltimindtree.com/#/Timesheet"
REGULARIZE_URL  = "https://itime.ltimindtree.com/#/Regularization"
TIMEOUT         = 30_000
DAY_NAMES       = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ── Screenshot helper ─────────────────────────────────────────────────────────
def shot(page, step: str):
    path = SCREENSHOTS_DIR / f"{step}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  [screenshot] {path}")


# ── Try-click / try-fill helpers ──────────────────────────────────────────────
def try_click(page, selectors: list[str], label: str) -> bool:
    for sel in selectors:
        if not sel:
            continue
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3_000):
                el.click()
                page.wait_for_timeout(1_000)
                print(f"  ✓ Clicked: {label}")
                return True
        except Exception:
            continue
    print(f"  ✗ Could not click: {label}")
    return False


def try_fill(page, selectors: list[str], value: str, label: str) -> bool:
    for sel in selectors:
        if not sel:
            continue
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3_000):
                el.triple_click()
                el.fill(value)
                print(f"  ✓ Filled {value}hr → {label}")
                return True
        except Exception:
            continue
    print(f"  ✗ Could not fill: {label}")
    return False


def try_select(page, selectors: list[str], option: str, label: str) -> bool:
    for sel in selectors:
        if not sel:
            continue
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3_000):
                tag = el.evaluate("e => e.tagName").upper()
                if tag == "SELECT":
                    el.select_option(label=option)
                else:
                    el.click()
                    page.wait_for_timeout(500)
                    page.locator(
                        f"mat-option:has-text('{option}'), "
                        f"li:has-text('{option}'), "
                        f"option:has-text('{option}')"
                    ).first.click()
                print(f"  ✓ Selected '{option}' → {label}")
                return True
        except Exception:
            continue
    print(f"  ✗ Could not select '{option}' for: {label}")
    return False


def save(page, context=""):
    try_click(page, [
        "button:has-text('Save')",
        "input[value='Save']",
        "button[title='Save']",
        "#saveButton",
        "[class*='save-btn']",
        "button.save",
    ], f"Save ({context})")
    page.wait_for_timeout(2_000)


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
        pass  # no login page → still authenticated


# ── Week navigation ───────────────────────────────────────────────────────────
def go_back_weeks(page, weeks: int, label: str):
    if weeks <= 0:
        return
    prev_btns = [
        "button[aria-label*='previous' i]",
        "button[aria-label*='prev' i]",
        "button.prev-week",
        "[class*='prev-week']",
        ".week-nav-prev",
        "mat-icon:has-text('chevron_left')",
    ]
    print(f"  Navigating {weeks} week(s) back ({label})...")
    for _ in range(weeks):
        try_click(page, prev_btns, "previous week")
        page.wait_for_timeout(1_000)


# ── Wait for app to finish loading ───────────────────────────────────────────
def wait_for_app(page):
    """Wait until the LTM loading spinner is gone and content is visible."""
    print("  Waiting for app to load...")
    try:
        # Wait for loading spinner to disappear
        page.wait_for_selector(
            "text=LOADING", state="hidden", timeout=30_000
        )
    except PWTimeout:
        pass
    # Extra buffer for Angular to render
    page.wait_for_timeout(3_000)


# ── Step 1 & 2: Navigate and identify yesterday ───────────────────────────────
def step_navigate(page):
    print(f"\nStep 1 — Navigate to Timesheet page")
    page.goto(TIMESHEET_URL, wait_until="networkidle")
    wait_for_app(page)
    shot(page, "01_timesheet_loaded")
    assert_logged_in(page)

    weeks_back = (date.today() - TARGET_DATE).days // 7
    go_back_weeks(page, weeks_back, "timesheet")
    shot(page, "02_correct_week")

    day_name = DAY_NAMES[TARGET_DATE.weekday()]
    print(f"  Target date: {TARGET_DATE} ({day_name})")


# ── Step 3 & 4: Fill project and non-project hours ───────────────────────────
def step_fill_timesheet(page):
    col = TARGET_DATE.weekday() + 2  # Mon=col2 … Sun=col8

    print(f"\nStep 3 — Fill 8 hours (project)")
    try_fill(page, [
        f"tr:has-text('Billable') td:nth-child({col}) input",
        f"tr:has-text('Project') td:nth-child({col}) input",
        "tr:has-text('Billable') input[type='number']",
        "tr:has-text('Billable') input[type='text']",
        "[data-type='billable'] input",
        ".project-hours input",
    ], "8", "project hours")

    print(f"\nStep 4 — Fill 1 hour (non-project)")
    try_fill(page, [
        f"tr:has-text('Non-Project') td:nth-child({col}) input",
        f"tr:has-text('Non Project') td:nth-child({col}) input",
        "tr:has-text('Non-Project') input[type='number']",
        "tr:has-text('Non-Project') input[type='text']",
        "[data-type='non-project'] input",
        ".non-project-hours input",
    ], "1", "non-project hours")

    shot(page, "03_hours_filled")

    print(f"\nStep 5 — Save timesheet")
    save(page, "timesheet")
    shot(page, "04_timesheet_saved")


# ── Step 5: Regularization ────────────────────────────────────────────────────
def step_regularize(page):
    print(f"\nStep 6 — Open Regularization")
    opened = try_click(page, [
        "a:has-text('Regulariz')",
        "button:has-text('Regulariz')",
        "li:has-text('Regulariz')",
        "[href*='regulariz' i]",
        "[class*='regulariz' i]",
    ], "Regularization tab")

    if not opened:
        page.goto(REGULARIZE_URL, wait_until="networkidle")

    wait_for_app(page)
    shot(page, "05_regularization_open")

    weeks_back = (date.today() - TARGET_DATE).days // 7
    go_back_weeks(page, weeks_back, "regularization")

    print("  Filling 9 hours WFH...")
    try_fill(page, [
        "input[placeholder*='hour' i]",
        "input[name*='hour' i]",
        "input[id*='hour' i]",
        "[class*='reg-hours'] input",
        "input[type='number']",
    ], "9", "regularization hours")

    try_select(page, [
        "select[name*='reason' i]",
        "select[id*='reason' i]",
        "[class*='reason'] select",
        "mat-select[placeholder*='reason' i]",
        "[aria-label*='reason' i]",
    ], "Work From Home", "reason")

    try_fill(page, [
        "textarea[placeholder*='comment' i]",
        "textarea[name*='comment' i]",
        "input[placeholder*='comment' i]",
        "input[name*='remark' i]",
        "textarea",
    ], "wfh", "comment")

    shot(page, "06_regularization_filled")
    save(page, "regularization")
    shot(page, "07_regularization_saved")
    print("  Regularization saved.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print(f"iTime Timesheet — {TARGET_DATE} ({DAY_NAMES[TARGET_DATE.weekday()]})")
    print("=" * 55)

    decoded = base64.b64decode(SESSION_B64.encode())
    # Support both compressed (gzip) and plain JSON sessions
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
