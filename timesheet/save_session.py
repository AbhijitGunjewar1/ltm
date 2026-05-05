#!/usr/bin/env python3
"""
ONE-TIME LOCAL SETUP SCRIPT — run this on your own laptop.

Opens a real Chromium browser, navigates to iTime, and waits for you to
log in manually (SSO / MFA / whatever your org requires). Once you are
fully logged in and the Timesheet page is visible, press ENTER in this
terminal. The script saves your authenticated session to auth_state.json.

You then encode that file and store it as a GitHub secret so the automated
workflow can reuse your session without ever touching the login page.

Steps:
  1.  pip install playwright && playwright install chromium
  2.  python timesheet/save_session.py
  3.  Log in inside the browser window that opens
  4.  Press ENTER here when the Timesheet page is fully loaded
  5.  Run the command printed at the end to get your base64 secret value
  6.  Add it as GitHub secret  ITIME_SESSION
"""

import base64
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL      = "https://itime.ltimindtree.com/#/Timesheet"
SESSION_FILE  = Path("timesheet/auth_state.json")


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

    # Encode to base64 for GitHub secret
    raw     = SESSION_FILE.read_bytes()
    encoded = base64.b64encode(raw).decode()

    print("\n✓ Session saved to", SESSION_FILE)
    print("\n" + "=" * 60)
    print("NEXT STEP — add this as GitHub secret  ITIME_SESSION")
    print("=" * 60)
    print("\nEither run this command and copy the output:")
    print(f"  python -c \"import base64; print(base64.b64encode(open('{SESSION_FILE}','rb').read()).decode())\"")
    print("\nOr copy the value below (it is long — select all of it):\n")
    print(encoded)
    print("\n" + "=" * 60)
    print("Go to: https://github.com/AbhijitGunjewar1/ltm/settings/secrets/actions")
    print("Create secret  ITIME_SESSION  and paste the value above.")


if __name__ == "__main__":
    main()
