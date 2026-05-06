#!/usr/bin/env python3
"""
iTime Timesheet Automation

Flow:
  1. Navigate and wait for timesheet to fully load
  2. Fill 8 hours (project row) for yesterday
  3. Fill 1 hour (non-project row) for yesterday
  4. Save timesheet
  5. Click target date in week header
  6. Click Regularize → fill 9hr WFH, comment 'wfh' → Save

Required env vars (one of):
  ITIME_SESSION      - base64-encoded auth_state.json
  ITIME_SESSION_FILE - path to file with base64 value
                       defaults to timesheet/session.txt

Optional env vars:
  TARGET_DATE   - YYYY-MM-DD (default: yesterday)
  HEADLESS      - "false" to show browser (default: true)
  SCREENSHOTS_DIR - debug PNG folder (default: timesheet/screenshots)
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
    f = Path(os.environ.get("ITIME_SESSION_FILE", "timesheet/session.txt"))
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    raise RuntimeError(
        "Session not found. Set ITIME_SESSION env var or place "
        "the base64 value in timesheet/session.txt"
    )

SESSION_B64     = _load_session()
HEADLESS        = os.environ.get("HEADLESS", "true").lower() != "false"
SCREENSHOTS_DIR = Path(os.environ.get("SCREENSHOTS_DIR", "timesheet/screenshots"))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

_raw = os.environ.get("TARGET_DATE", "")
TARGET_DATE = date.fromisoformat(_raw) if _raw else date.today() - timedelta(days=1)

TIMESHEET_URL = "https://itime.ltimindtree.com/#/Timesheet"
DAY_NAMES     = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Column offset from Sunday (Sun=0, Mon=1, Tue=2, Wed=3, Thu=4, Fri=5, Sat=6)
COL_OFFSET = (TARGET_DATE.weekday() + 1) % 7


# ── Helpers ───────────────────────────────────────────────────────────────────
def shot(page, name: str):
    p = SCREENSHOTS_DIR / f"{name}.png"
    page.screenshot(path=str(p), full_page=True)
    print(f"  [screenshot] {p}")


def wait_for_page_ready(page):
    """Wait for network idle AND LTM spinner gone AND inputs visible."""
    print("  Waiting for page to be ready...")
    # Wait for network to settle
    page.wait_for_load_state("networkidle")
    # Wait for LTM loading spinner to disappear
    try:
        page.wait_for_selector("text=LOADING", state="hidden", timeout=30_000)
    except PWTimeout:
        pass
    # Wait for actual timesheet content (inputs) to appear
    try:
        page.wait_for_selector(
            "input:not([disabled]):not([readonly])",
            state="visible",
            timeout=30_000
        )
        print("  Page ready — inputs visible.")
    except PWTimeout:
        print("  Warning: inputs not visible after 30s")


def dismiss_popup(page):
    for sel in ["button:has-text('Ok')", "button:has-text('OK')", "button:has-text('Close')"]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2_000):
                btn.click()
                page.wait_for_load_state("networkidle")
                print("  Dismissed popup.")
                return
        except Exception:
            continue


def assert_logged_in(page):
    try:
        page.wait_for_selector("input[type='email'], input[name='loginfmt']", timeout=5_000)
        shot(page, "99_session_expired")
        raise RuntimeError("Session expired — run save_session.py to refresh.")
    except PWTimeout:
        pass


# ── Get input rows grouped by y-position, sorted by x ────────────────────────
def get_input_rows(page) -> list[list[dict]]:
    return page.evaluate("""
    () => {
        const inputs = Array.from(document.querySelectorAll('input'))
            .filter(inp => {
                if (inp.disabled || inp.readOnly || !inp.offsetParent) return false;
                const s = window.getComputedStyle(inp);
                if (s.display === 'none' || s.visibility === 'hidden') return false;
                const r = inp.getBoundingClientRect();
                return r.width > 5 && r.height > 5;
            })
            .map(inp => {
                const r = inp.getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            })
            .sort((a, b) => a.y - b.y);

        const rows = [];
        for (const inp of inputs) {
            const row = rows.find(r => Math.abs(r[0].y - inp.y) < 12);
            if (row) row.push(inp);
            else rows.push([inp]);
        }
        rows.forEach(r => r.sort((a, b) => a.x - b.x));
        return rows;
    }
    """)


def click_and_type(page, x: float, y: float, value: str, label: str):
    page.mouse.click(x, y, click_count=3)
    page.wait_for_selector("input:focus", timeout=5_000)
    page.keyboard.type(value)
    page.keyboard.press("Tab")
    # Wait for any network activity from the Tab/change event to settle
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except PWTimeout:
        pass
    print(f"  ✓ Typed {value}hr → {label}")


# ── Step 1: Navigate ──────────────────────────────────────────────────────────
def step_navigate(page):
    print(f"\nStep 1 — Navigate to Timesheet")
    page.goto(TIMESHEET_URL)
    wait_for_page_ready(page)
    assert_logged_in(page)
    shot(page, "01_timesheet_loaded")

    weeks_back = (date.today() - TARGET_DATE).days // 7
    if weeks_back > 0:
        print(f"  Going {weeks_back} week(s) back...")
        for _ in range(weeks_back):
            for sel in ["button[aria-label*='previous' i]", "button[aria-label*='prev' i]",
                        ".prev-week", "[class*='prev-week']"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=3_000):
                        btn.click()
                        wait_for_page_ready(page)
                        break
                except Exception:
                    continue

    shot(page, "02_correct_week")
    print(f"  Target: {TARGET_DATE} ({DAY_NAMES[TARGET_DATE.weekday()]}), col_offset={COL_OFFSET}")


# ── Steps 2–4: Fill hours and save ───────────────────────────────────────────
def step_fill_timesheet(page):
    rows = get_input_rows(page)
    print(f"\n  Found {len(rows)} input row(s), col_offset={COL_OFFSET}")

    if not rows:
        shot(page, "03_no_inputs")
        raise RuntimeError("No input rows found — timesheet data not loaded.")

    # Fill project row (first row)
    proj_row = rows[0]
    if COL_OFFSET < len(proj_row):
        print(f"\nStep 2 — Fill 8hr (project)")
        click_and_type(page, proj_row[COL_OFFSET]["x"], proj_row[COL_OFFSET]["y"], "8", "project")
    else:
        print(f"  ✗ col_offset {COL_OFFSET} out of range for project row (has {len(proj_row)} cols)")

    # Fill non-project row (last row)
    if len(rows) > 1:
        np_row = rows[-1]
        if COL_OFFSET < len(np_row):
            print(f"\nStep 3 — Fill 1hr (non-project)")
            click_and_type(page, np_row[COL_OFFSET]["x"], np_row[COL_OFFSET]["y"], "1", "non-project")
        else:
            print(f"  ✗ col_offset {COL_OFFSET} out of range for non-project row")

    shot(page, "03_hours_filled")

    print(f"\nStep 4 — Save timesheet")
    save_btn = page.locator("button:has-text('Save')").first
    save_btn.wait_for(state="visible")
    save_btn.click()
    page.wait_for_load_state("networkidle")
    dismiss_popup(page)
    shot(page, "04_timesheet_saved")


# ── Steps 5–6: Regularize ────────────────────────────────────────────────────
def step_regularize(page):
    day_num  = TARGET_DATE.day
    day_abbr = DAY_NAMES[TARGET_DATE.weekday()]
    print(f"\nStep 5 — Click date '{day_abbr} {day_num:02d}' in week header")

    for sel in [
        f"td:has-text('{day_abbr} {day_num:02d}')",
        f"th:has-text('{day_abbr} {day_num:02d}')",
        f"td:has-text('{day_abbr} {day_num}')",
        f"td:has-text('{day_num:02d}')",
    ]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2_000):
                el.click()
                page.wait_for_load_state("networkidle")
                print(f"  ✓ Clicked date cell")
                break
        except Exception:
            continue

    print(f"  Step 6 — Click Regularize")
    for sel in ["button:has-text('Regularize')", "a:has-text('Regularize')",
                "span:has-text('Regularize')", "button:has-text('Regulariz')"]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=5_000):
                btn.click()
                page.wait_for_load_state("networkidle")
                print("  ✓ Clicked Regularize")
                break
        except Exception:
            continue

    shot(page, "05_regularize_open")

    # Fill hours — wait for input to appear first
    for sel in ["input[placeholder*='hour' i]", "input[name*='hour' i]",
                "[class*='hour'] input", "input[type='number']"]:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=10_000)
            el.triple_click()
            el.fill("9")
            print("  ✓ Filled 9hr")
            break
        except Exception:
            continue

    # Select reason
    for sel in ["select", "mat-select", "[aria-label*='reason' i]", "[placeholder*='reason' i]"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3_000):
                tag = el.evaluate("e => e.tagName").upper()
                if tag == "SELECT":
                    el.select_option(label="Work From Home")
                else:
                    el.click()
                    page.wait_for_load_state("networkidle")
                    page.locator("mat-option:has-text('Work From Home'), "
                                 "li:has-text('Work From Home')").first.click()
                print("  ✓ Selected Work From Home")
                break
        except Exception:
            continue

    # Fill comment
    for sel in ["textarea", "input[placeholder*='comment' i]", "input[name*='remark' i]"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3_000):
                el.triple_click()
                el.fill("wfh")
                print("  ✓ Comment: wfh")
                break
        except Exception:
            continue

    shot(page, "06_regularize_filled")

    save_btn = page.locator("button:has-text('Save')").first
    save_btn.wait_for(state="visible")
    save_btn.click()
    page.wait_for_load_state("networkidle")
    dismiss_popup(page)
    shot(page, "07_regularize_saved")
    print("  ✓ Regularization saved.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print(f"iTime Timesheet — {TARGET_DATE} ({DAY_NAMES[TARGET_DATE.weekday()]})")
    print("=" * 55)

    raw = base64.b64decode(SESSION_B64.encode())
    try:
        session_json = gzip.decompress(raw)
    except OSError:
        session_json = raw
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
        page.set_default_timeout(60_000)

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
