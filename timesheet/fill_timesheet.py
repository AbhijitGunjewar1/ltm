#!/usr/bin/env python3
"""
Fills iTime timesheet for the PREVIOUS day and regularizes attendance.

Schedule: runs daily at 11:00 AM IST (05:30 UTC) via GitHub Actions.
Can also be triggered manually (ad-hoc) via workflow_dispatch.

Rules:
  Timesheet  → 8 hr billable project + 1 hr non-project for previous day → Save
  Regularize → previous day HR capture = 0  : 9 hr WFH → Save
               previous day HR capture > 0  : 3 hr WFH → Save
               (does NOT submit)

Required env vars:
  ITIME_USERNAME      – corporate login email / employee ID
  ITIME_PASSWORD      – password

Optional env vars:
  ITIME_PROJECT_CODE  – project code to book billable hours against
  TARGET_DATE         – override date in YYYY-MM-DD (default: yesterday)
  HEADLESS            – "false" to watch browser (default: true)
  SCREENSHOTS_DIR     – where to save debug PNGs (default: timesheet/screenshots)
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────
USERNAME       = os.environ["ITIME_USERNAME"]
PASSWORD       = os.environ["ITIME_PASSWORD"]
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

CLOSE_NAMES = {"done", "closed", "close", "resolved", "resolve", "complete", "completed"}

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
    print(f"  WARNING: Could not click '{label}'. Update selectors if needed.")
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
    print(f"  WARNING: Could not fill '{label}'. Update selectors if needed.")
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


# ── Login ─────────────────────────────────────────────────────────────────────
def login(page):
    print(f"Navigating to iTime (target date: {TARGET_DATE})...")
    page.goto(BASE_URL, wait_until="networkidle")
    shot(page, "01_landing")

    try:
        page.wait_for_selector(
            "input[type='email'], input[name='loginfmt'], input[id='userNameInput']",
            timeout=TIMEOUT,
        )
        email = page.locator(
            "input[type='email'], input[name='loginfmt'], input[id='userNameInput']"
        ).first
        email.fill(USERNAME)

        # Microsoft SSO "Next" button
        next_btn = page.locator("input[type='submit'], button:has-text('Next'), #idSIButton9")
        if next_btn.count():
            next_btn.first.click()
            page.wait_for_timeout(1500)

        page.wait_for_selector(
            "input[type='password'], input[name='passwd'], input[id='passwordInput']",
            timeout=TIMEOUT,
        )
        page.locator(
            "input[type='password'], input[name='passwd'], input[id='passwordInput']"
        ).first.fill(PASSWORD)

        page.locator(
            "input[type='submit'], button:has-text('Sign in'), #idSIButton9, #signInButton"
        ).first.click()

        # "Stay signed in?" prompt
        try:
            page.wait_for_selector("#idBtn_Back, button:has-text('No')", timeout=8000)
            page.locator("#idBtn_Back, button:has-text('No')").first.click()
        except PWTimeout:
            pass

        shot(page, "02_post_login")
        print("Login successful.")
    except PWTimeout:
        shot(page, "02_login_failed")
        raise RuntimeError("Login form not found — check screenshot 02_login_failed.")


# ── Navigate to correct week ──────────────────────────────────────────────────
def navigate_to_week(page):
    """
    iTime shows the current week by default.
    If TARGET_DATE is in a previous week, click the back-arrow until the
    week containing TARGET_DATE is visible in the header.
    """
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(2000)
    shot(page, "03_timesheet_default_week")

    today = date.today()
    # How many full weeks back is TARGET_DATE?
    days_back = (today - TARGET_DATE).days
    weeks_back = days_back // 7

    if weeks_back > 0:
        print(f"  Navigating {weeks_back} week(s) back for {TARGET_DATE}...")
        prev_selectors = [
            "button[aria-label*='previous' i]",
            "button[aria-label*='prev' i]",
            "button.prev-week",
            "[class*='prev-week']",
            "button:has-text('<')",
            ".week-nav-prev",
            "mat-icon:has-text('chevron_left')",
        ]
        for _ in range(weeks_back):
            click_first_visible(page, prev_selectors, "previous week arrow")
            page.wait_for_timeout(1000)

    shot(page, "04_correct_week")
    print(f"  On week containing {TARGET_DATE}.")


# ── Fill timesheet ────────────────────────────────────────────────────────────
def fill_timesheet(page):
    print("Filling timesheet for previous day...")
    day_name = DAY_ABBR[TARGET_DATE.weekday()]          # e.g. "Mon"
    day_num  = str(TARGET_DATE.day)                     # e.g. "7"

    # Build column-specific selectors using day name / date
    project_selectors = [
        f"tr:has-text('Billable') td:has-text('{day_name}') input",
        f"tr:has-text('Billable') [data-day='{day_name}'] input",
        f"tr:has-text('Project') td:nth-child({TARGET_DATE.weekday() + 2}) input",
        "tr.project-row input[type='number']",
        "tr:has-text('Billable') input[type='text']",
        "[data-type='billable'] input",
        ".project-hours input",
    ]
    non_project_selectors = [
        f"tr:has-text('Non-Project') td:has-text('{day_name}') input",
        f"tr:has-text('Non Project') [data-day='{day_name}'] input",
        f"tr:has-text('Non') td:nth-child({TARGET_DATE.weekday() + 2}) input",
        "tr.non-project-row input[type='number']",
        "tr:has-text('Non-Project') input[type='text']",
        "[data-type='non-project'] input",
        ".non-project-hours input",
    ]

    fill_first_visible(page, project_selectors,     "8", "billable project")
    fill_first_visible(page, non_project_selectors, "1", "non-project")

    shot(page, "05_timesheet_filled")
    _save(page, "timesheet")
    shot(page, "06_timesheet_saved")


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

    # Navigate to regularization tab/page
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

    shot(page, "07_regularization_open")

    # Navigate to previous day if needed (same week-back logic)
    today = date.today()
    days_back = (today - TARGET_DATE).days
    weeks_back = days_back // 7
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

    hr_hours = get_hr_capture(page)
    wfh_hours = "9" if hr_hours == 0 else "3"
    print(f"  → Regularizing {wfh_hours} hr as WFH (HR captured {hr_hours} hr)")

    # Hours input
    hours_selectors = [
        "input[placeholder*='hour' i]",
        "input[name*='hour' i]",
        "input[id*='hour' i]",
        "[class*='reg-hours'] input",
        "input[type='number']",
    ]
    fill_first_visible(page, hours_selectors, wfh_hours, "regularization hours")

    # Reason dropdown → Work From Home
    reason_selectors = [
        "select[name*='reason' i]",
        "select[id*='reason' i]",
        "[class*='reason'] select",
        "mat-select[placeholder*='reason' i]",
        "[aria-label*='reason' i]",
    ]
    select_option_first_visible(page, reason_selectors, "Work From Home", "reason")

    # Comment field → WFH
    comment_selectors = [
        "textarea[placeholder*='comment' i]",
        "textarea[name*='comment' i]",
        "input[placeholder*='comment' i]",
        "input[name*='remark' i]",
        "textarea",
    ]
    fill_first_visible(page, comment_selectors, "WFH", "comment")

    shot(page, "08_regularization_filled")
    _save(page, "regularization")
    shot(page, "09_regularization_saved")
    print("Regularization saved (not submitted).")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"Target date: {TARGET_DATE} ({DAY_ABBR[TARGET_DATE.weekday()]})")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx  = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(TIMEOUT)

        try:
            login(page)
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
