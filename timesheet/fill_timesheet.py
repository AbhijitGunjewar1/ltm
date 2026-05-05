#!/usr/bin/env python3
"""
Fills iTime timesheet for the PREVIOUS day and regularizes attendance.
Uses a saved browser session (no SSO login needed).

Schedule: runs daily at 11:00 AM IST (05:30 UTC) via GitHub Actions.
Can also be triggered manually (ad-hoc) via workflow_dispatch.

Rules:
  Timesheet  → 8 hr billable project + 1 hr non-project for previous day → Save
  Regularize → previous day HR capture = 0  : 9 hr WFH → Save
               previous day HR capture > 0  : 3 hr WFH → Save
               (does NOT submit)

Required env vars:
  ITIME_SESSION       – base64-encoded auth_state.json (from save_session.py)
  ITIME_PROJECT_CODE  – project code to book billable hours against

Optional env vars:
  TARGET_DATE         – override date in YYYY-MM-DD (default: yesterday)
  HEADLESS            – "false" to watch browser (default: true)
  SCREENSHOTS_DIR     – where to save debug PNGs (default: timesheet/screenshots)
"""

import base64
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────
SESSION_B64    = os.environ["ITIME_SESSION"]
PROJECT_CODE   = os.environ.get("ITIME_PROJECT_CODE", "")
HEADLESS       = os.environ.get("HEADLESS", "true").lower() != "false"
SCREENSHOTS_DIR = Path(os.environ.get("SCREENSHOTS_DIR", "timesheet/screenshots"))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

_raw_date = os.environ.get("TARGET_DATE", "")
TARGET_DATE: date = (
    date.fromisoformat(_raw_date) if _raw_date
    else date.today() - timedelta(days=1)
)

BASE_URL = "https://itime.ltimindtree.com/#/Timesheet"
TIMEOUT  = 30_000  # ms

DAY_ABBR = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}


# ── Helpers ───────────────────────────────────────────────────────────────────
def shot(page, name: str):
    path = SCREENSHOTS_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  [screenshot] {path}")


def click_first_visible(page, selectors: list[str], label: str) -> bool:
    for sel in selectors:
        if not sel:
            continue
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3000):
                el.click()
                page.wait_for_timeout(1000)
                print(f"  Clicked {label}.")
                return True
        except Exception:
            continue
    print(f"  WARNING: Could not click '{label}'.")
    return False


def fill_first_visible(page, selectors: list[str], value: str, label: str) -> bool:
    for sel in selectors:
        if not sel:
            continue
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3000):
                el.triple_click()
                el.fill(value)
                print(f"  Filled {value} hr → {label}.")
                return True
        except Exception:
            continue
    print(f"  WARNING: Could not fill '{label}'.")
    return False


def select_option_first_visible(page, selectors: list[str], option_text: str, label: str) -> bool:
    for sel in selectors:
        if not sel:
            continue
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3000):
                tag = el.evaluate("e => e.tagName").upper()
                if tag == "SELECT":
                    el.select_option(label=option_text)
                else:
                    el.click()
                    page.wait_for_timeout(500)
                    opt = page.locator(
                        f"mat-option:has-text('{option_text}'), "
                        f"li:has-text('{option_text}'), "
                        f"option:has-text('{option_text}')"
                    ).first
                    opt.click()
                print(f"  Selected '{option_text}' → {label}.")
                return True
        except Exception:
            continue
    print(f"  WARNING: Could not select '{option_text}' for '{label}'.")
    return False


def is_logged_in(page) -> bool:
    """Returns True if the timesheet page loaded (not redirected to login)."""
    try:
        # Login page has an email input; if absent we are inside the app
        page.wait_for_selector("input[type='email'], input[name='loginfmt']", timeout=5000)
        return False
    except PWTimeout:
        return True


# ── Navigate to correct week ──────────────────────────────────────────────────
def navigate_to_week(page):
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(2000)
    shot(page, "01_timesheet_loaded")

    if not is_logged_in(page):
        shot(page, "99_session_expired")
        raise RuntimeError(
            "Session has expired. Run  python timesheet/save_session.py  locally "
            "to capture a fresh session and update the ITIME_SESSION secret."
        )

    today = date.today()
    days_back  = (today - TARGET_DATE).days
    weeks_back = days_back // 7

    if weeks_back > 0:
        print(f"  Navigating {weeks_back} week(s) back for {TARGET_DATE}...")
        prev_selectors = [
            "button[aria-label*='previous' i]",
            "button[aria-label*='prev' i]",
            "button.prev-week",
            "[class*='prev-week']",
            ".week-nav-prev",
            "mat-icon:has-text('chevron_left')",
        ]
        for _ in range(weeks_back):
            click_first_visible(page, prev_selectors, "previous week arrow")
            page.wait_for_timeout(1000)

    shot(page, "02_correct_week")
    print(f"  On week containing {TARGET_DATE}.")


# ── Fill timesheet ────────────────────────────────────────────────────────────
def fill_timesheet(page):
    print(f"Filling timesheet for {TARGET_DATE} ({DAY_ABBR[TARGET_DATE.weekday()]})...")
    col = TARGET_DATE.weekday() + 2  # Mon=col2, Tue=col3 … Sun=col8

    project_selectors = [
        f"tr:has-text('Billable') td:nth-child({col}) input",
        f"tr:has-text('Project') td:nth-child({col}) input",
        "tr:has-text('Billable') input[type='number']",
        "tr:has-text('Billable') input[type='text']",
        "[data-type='billable'] input",
        ".project-hours input",
    ]
    non_project_selectors = [
        f"tr:has-text('Non-Project') td:nth-child({col}) input",
        f"tr:has-text('Non Project') td:nth-child({col}) input",
        "tr:has-text('Non-Project') input[type='number']",
        "tr:has-text('Non-Project') input[type='text']",
        "[data-type='non-project'] input",
        ".non-project-hours input",
    ]

    fill_first_visible(page, project_selectors,     "8", "billable project")
    fill_first_visible(page, non_project_selectors, "1", "non-project")

    shot(page, "03_timesheet_filled")
    _save(page, "timesheet")
    shot(page, "04_timesheet_saved")


def _save(page, context=""):
    save_selectors = [
        "button:has-text('Save')",
        "input[value='Save']",
        "button[title='Save']",
        "#saveButton",
        "[class*='save-btn']",
        "button.save",
    ]
    click_first_visible(page, save_selectors, f"Save ({context})")
    page.wait_for_timeout(2000)


# ── Regularization ────────────────────────────────────────────────────────────
def get_hr_capture(page) -> float:
    selectors = [
        "[class*='hr-capture'] input",
        "[class*='hr-capture'] span",
        "td:has-text('HR Capture') + td",
        "[data-label*='HR'] input",
        ".hr-hours",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3000):
                tag = el.evaluate("e => e.tagName").upper()
                raw = el.input_value() if tag == "INPUT" else el.inner_text()
                val = float(raw.strip() or "0")
                print(f"  HR capture = {val} hr")
                return val
        except Exception:
            continue
    print("  HR capture value not detected — defaulting to 0.")
    return 0.0


def fill_regularization(page):
    print("Opening Regularization...")

    reg_selectors = [
        "a:has-text('Regulariz')",
        "button:has-text('Regulariz')",
        "li:has-text('Regulariz')",
        "[href*='regulariz' i]",
        "[class*='regulariz' i]",
    ]
    opened = click_first_visible(page, reg_selectors, "Regularization tab")
    if not opened:
        page.goto("https://itime.ltimindtree.com/#/Regularization", wait_until="networkidle")
        page.wait_for_timeout(2000)

    shot(page, "05_regularization_open")

    # Navigate back weeks if needed
    today = date.today()
    weeks_back = (today - TARGET_DATE).days // 7
    if weeks_back > 0:
        prev_selectors = [
            "button[aria-label*='previous' i]",
            "button[aria-label*='prev' i]",
            "button.prev-week",
            "[class*='prev-week']",
            ".week-nav-prev",
        ]
        for _ in range(weeks_back):
            click_first_visible(page, prev_selectors, "previous week (regularization)")
            page.wait_for_timeout(1000)

    hr_hours  = get_hr_capture(page)
    wfh_hours = "9" if hr_hours == 0 else "3"
    print(f"  → Regularizing {wfh_hours} hr as WFH (HR captured {hr_hours} hr)")

    hours_selectors = [
        "input[placeholder*='hour' i]",
        "input[name*='hour' i]",
        "input[id*='hour' i]",
        "[class*='reg-hours'] input",
        "input[type='number']",
    ]
    fill_first_visible(page, hours_selectors, wfh_hours, "regularization hours")

    reason_selectors = [
        "select[name*='reason' i]",
        "select[id*='reason' i]",
        "[class*='reason'] select",
        "mat-select[placeholder*='reason' i]",
        "[aria-label*='reason' i]",
    ]
    select_option_first_visible(page, reason_selectors, "Work From Home", "reason")

    comment_selectors = [
        "textarea[placeholder*='comment' i]",
        "textarea[name*='comment' i]",
        "input[placeholder*='comment' i]",
        "input[name*='remark' i]",
        "textarea",
    ]
    fill_first_visible(page, comment_selectors, "WFH", "comment")

    shot(page, "06_regularization_filled")
    _save(page, "regularization")
    shot(page, "07_regularization_saved")
    print("Regularization saved (not submitted).")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"Target date: {TARGET_DATE} ({DAY_ABBR[TARGET_DATE.weekday()]})")

    # Decode session from env var into a temp file
    session_json = base64.b64decode(SESSION_B64.encode())
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
            navigate_to_week(page)
            fill_timesheet(page)
            fill_regularization(page)
            print("\nAll done!")
        except Exception as exc:
            shot(page, "99_error")
            print(f"\nERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
