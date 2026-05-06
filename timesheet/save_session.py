#!/usr/bin/env python3
"""
ONE-TIME LOCAL SETUP — run this on your own laptop before using the automation.

Opens a real Chromium browser and navigates to iTime. Log in manually via SSO/MFA,
then press ENTER here. Your authenticated session is saved to auth_state.json and
encoded as base64 for use as the ITIME_SESSION secret in GitHub Actions.

Steps:
  1. pip install playwright && playwright install chromium
  2. python timesheet/save_session.py
  3. Log in inside the browser that opens
  4. Press ENTER once the Timesheet page is fully loaded
  5. Copy the printed base64 value and save it as GitHub secret: ITIME_SESSION
"""

import base64
import gzip
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL     = "https://itime.ltimindtree.com/#/Timesheet"
SESSION_FILE = Path("timesheet/auth_state.json")
SESSION_TXT  = Path("timesheet/session.txt")


def main():
    print("=" * 60)
    print("iTime Session Capture")
    print("=" * 60)
    print("\nA browser window will open. Log in as you normally would.")
    print("Come back here and press ENTER once the Timesheet page is loaded.\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx  = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(BASE_URL)

        input(">>> Log in to iTime, then press ENTER here to save your session... ")

        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        ctx.storage_state(path=str(SESSION_FILE))
        browser.close()

    # Compress then base64-encode (reduces size by ~75%)
    raw       = SESSION_FILE.read_bytes()
    compressed = gzip.compress(raw, compresslevel=9)
    encoded   = base64.b64encode(compressed).decode()

    SESSION_TXT.write_text(encoded, encoding="utf-8")

    original_kb   = len(raw) / 1024
    compressed_kb = len(encoded) / 1024
    print(f"\n✓ Session saved to {SESSION_FILE}")
    print(f"  Original size : {original_kb:.1f} KB")
    print(f"  Encoded size  : {compressed_kb:.1f} KB  (compressed + base64)")
    print(f"✓ Encoded value written to {SESSION_TXT}")
    print("\n" + "=" * 60)
    print("NEXT STEP — add this as GitHub secret: ITIME_SESSION")
    print("=" * 60)
    print(f"\nOpen  {SESSION_TXT}  and copy the entire contents.")
    print("\nThen go to: https://github.com/AbhijitGunjewar1/ltm/settings/secrets/actions")
    print("Create secret  ITIME_SESSION  and paste the value.")


if __name__ == "__main__":
    main()
