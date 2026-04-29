#!/usr/bin/env python3
"""
Automates weekly timesheet filling on https://itime.ltimindtree.com/#/Timesheet

Actions performed every Friday:
  1. Log in with SSO credentials
  2. Open current week's timesheet
  3. Enter 8 hr in project row, 1 hr in non-project row
  4. Save the timesheet
  5. Open the Regularization section
  6. If HR system captured 0 hr → regularize 9 hr as Work From Home
     If HR system captured > 0 hr → regularize 3 hr as Work From Home
  7. Save regularization (does NOT submit)

Required environment variables:
  ITIME_USERNAME   – corporate login id / email
  ITIME_PASSWORD   – password
  ITIME_PROJECT_CODE – project code / task to book 8 hr against (optional)

Optional:
  HEADLESS         – "false" to watch the browser (default: true)
  SCREENSHOTS_DIR  – directory to save debug screenshots (default: screenshots/)
"""

import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

USERNAME = os.environ["ITIME_USERNAME"]
PASSWORD = os.environ["ITIME_PASSWORD"]
PROJECT_CODE = os.environ.get("ITIME_PROJECT_CODE", "")
HEADLESS = os.environ.get("HEADLESS", "true").lower() != "false"
SCREENSHOTS_DIR = Path(os.environ.get("SCREENSHOTS_DIR", "screenshots"))
SCREENSHOTS_DIR.mkdir(exist_ok=True)

BASE_URL = "https://itime.ltimindtree.com/#/Timesheet"
TIMEOUT = 30_000  # ms


def shot(page, name: str):
    path = SCREENSHOTS_DIR / f"{name}.png"
    page.screenshot(path=str(path))
    print(f"  [screenshot] {path}")


def login(page):
    print("Navigating to iTime...")
    page.goto(BASE_URL, wait_until="networkidle")
    shot(page, "01_landing")

    # Handle SSO / username-password login form
    # Adjust selectors below if your org uses a different SSO provider
    try:
        page.wait_for_selector("input[type='email'], input[name='loginfmt'], input[id='userNameInput']", timeout=TIMEOUT)
        email_input = page.locator("input[type='email'], input[name='loginfmt'], input[id='userNameInput']").first
        email_input.fill(USERNAME)

        # Click Next if present (Microsoft login flow)
        next_btn = page.locator("input[type='submit'], button:has-text('Next'), #idSIButton9")
        if next_btn.count() > 0:
            next_btn.first.click()
            page.wait_for_timeout(1500)

        page.wait_for_selector("input[type='password'], input[name='passwd'], input[id='passwordInput']", timeout=TIMEOUT)
        page.locator("input[type='password'], input[name='passwd'], input[id='passwordInput']").first.fill(PASSWORD)

        sign_in = page.locator("input[type='submit'], button:has-text('Sign in'), #idSIButton9, #signInButton")
        sign_in.first.click()

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
        raise RuntimeError("Could not find login form. Check screenshots for the actual page.")


def navigate_to_timesheet(page):
    print("Opening Timesheet...")
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(2000)
    shot(page, "03_timesheet_home")


def fill_timesheet(page):
    """Enter 8 hr project + 1 hr non-project for Friday and save."""
    print("Filling timesheet...")

    # ── Locate Friday column ──────────────────────────────────────────────────
    # The grid header usually shows day names; find "Fri" column index
    headers = page.locator("th, .day-header, .week-header, [class*='day']")
    friday_col_index = None
    for i in range(headers.count()):
        text = headers.nth(i).inner_text().strip().lower()
        if "fri" in text:
            friday_col_index = i
            break

    if friday_col_index is None:
        print("  WARNING: Could not auto-detect Friday column — will try to fill visible input cells.")

    # ── Project row (8 hr) ────────────────────────────────────────────────────
    # Try common patterns for project time entry cells
    project_row_selectors = [
        f"tr:has-text('Project') td:nth-child({friday_col_index + 1}) input" if friday_col_index else None,
        "tr.project-row td input[type='number']",
        "tr:has-text('Project') input[type='text']",
        "[data-type='project'] input",
        ".project-hours input",
    ]
    _fill_hours(page, project_row_selectors, "8", "project")

    # ── Non-project row (1 hr) ────────────────────────────────────────────────
    non_project_selectors = [
        f"tr:has-text('Non-Project') td:nth-child({friday_col_index + 1}) input" if friday_col_index else None,
        "tr.non-project-row td input[type='number']",
        "tr:has-text('Non Project') input[type='text']",
        "tr:has-text('Non-Project') input[type='text']",
        "[data-type='non-project'] input",
        ".non-project-hours input",
    ]
    _fill_hours(page, non_project_selectors, "1", "non-project")

    shot(page, "04_timesheet_filled")

    # ── Save ──────────────────────────────────────────────────────────────────
    _click_save(page, context="timesheet")
    shot(page, "05_timesheet_saved")
    print("Timesheet saved.")


def _fill_hours(page, selectors, value, label):
    for sel in selectors:
        if sel is None:
            continue
        try:
            el = page.locator(sel).first
            if el.count() > 0 or el.is_visible():
                el.triple_click()
                el.fill(value)
                print(f"  Filled {value} hr in {label} row.")
                return
        except Exception:
            continue
    print(f"  WARNING: Could not locate {label} input. Inspect screenshots and update selectors.")


def _click_save(page, context=""):
    save_selectors = [
        "button:has-text('Save')",
        "input[value='Save']",
        "button[title='Save']",
        "[class*='save-btn']",
        "#saveButton",
        "button.save",
    ]
    for sel in save_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click()
                page.wait_for_timeout(2000)
                print(f"  Clicked Save ({context}).")
                return
        except Exception:
            continue
    print(f"  WARNING: Save button not found for {context}. Inspect screenshots.")


def get_hr_capture(page):
    """Return the number of hours HR has captured, or 0 if none found."""
    hr_selectors = [
        "[class*='hr-capture'] input",
        "[class*='hr-capture'] span",
        "td:has-text('HR Capture') + td",
        "[data-label*='HR'] input",
        ".hr-hours",
    ]
    for sel in hr_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                raw = el.input_value() if el.evaluate("e => e.tagName") == "INPUT" else el.inner_text()
                val = float(raw.strip() or "0")
                print(f"  HR capture detected: {val} hr")
                return val
        except Exception:
            continue
    print("  HR capture value not found — defaulting to 0.")
    return 0.0


def fill_regularization(page):
    """Open regularization, determine WFH hours, fill and save."""
    print("Opening Regularization...")

    # Navigate to regularization — common placements
    reg_selectors = [
        "a:has-text('Regulariz')",
        "button:has-text('Regulariz')",
        "li:has-text('Regulariz')",
        "[href*='regulariz' i]",
        "[class*='regulariz' i]",
    ]
    for sel in reg_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                el.click()
                page.wait_for_timeout(2000)
                break
        except Exception:
            continue
    else:
        # Try navigating via URL fragment
        page.goto("https://itime.ltimindtree.com/#/Regularization", wait_until="networkidle")
        page.wait_for_timeout(2000)

    shot(page, "06_regularization_open")

    hr_hours = get_hr_capture(page)
    wfh_hours = "9" if hr_hours == 0 else "3"
    print(f"  HR captured={hr_hours} hr → will regularize {wfh_hours} hr as Work From Home")

    # ── Fill regularization hours ─────────────────────────────────────────────
    hours_selectors = [
        "input[placeholder*='hour' i]",
        "input[name*='hour' i]",
        "input[id*='hour' i]",
        "[class*='reg-hours'] input",
        "input[type='number']",
    ]
    _fill_hours(page, hours_selectors, wfh_hours, "regularization hours")

    # ── Set reason to Work From Home ──────────────────────────────────────────
    reason_selectors = [
        "select[name*='reason' i]",
        "select[id*='reason' i]",
        "[class*='reason'] select",
        "mat-select[placeholder*='reason' i]",
        "[aria-label*='reason' i]",
    ]
    reason_set = False
    for sel in reason_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                tag = el.evaluate("e => e.tagName").upper()
                if tag == "SELECT":
                    # Try to select "Work From Home" option
                    el.select_option(label="Work From Home")
                else:
                    # Material / custom dropdown
                    el.click()
                    page.wait_for_timeout(500)
                    wfh_option = page.locator("mat-option:has-text('Work From Home'), li:has-text('Work From Home'), option:has-text('Work From Home')").first
                    wfh_option.click()
                print("  Set reason to 'Work From Home'.")
                reason_set = True
                break
        except Exception:
            continue

    if not reason_set:
        print("  WARNING: Could not set reason. Inspect screenshots.")

    shot(page, "07_regularization_filled")

    # ── Save (NOT submit) ─────────────────────────────────────────────────────
    _click_save(page, context="regularization")
    shot(page, "08_regularization_saved")
    print("Regularization saved (not submitted).")


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(TIMEOUT)

        try:
            login(page)
            navigate_to_timesheet(page)
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
