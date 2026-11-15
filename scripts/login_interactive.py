#!/usr/bin/env python3
"""
Interactive Session Authenticator for LinkedIn & Naukri
Opens a visible browser on your machine, allowing you to log in once.
Saves session cookies and localStorage to data/browser_sessions/ so
automated runners can operate directly without triggering Cloudflare Turnstile.
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = PROJECT_ROOT / "data" / "browser_sessions"

def login_linkedin():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    state_file = SESSIONS_DIR / "linkedin_state.json"
    print("\n=======================================================")
    print("  [1/2] Authenticating LinkedIn in Visible Browser")
    print("=======================================================")
    print("Opening browser... Log in to your LinkedIn account.")
    print("Once logged in and viewing your feed, close the browser or press Enter.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        try:
            page.wait_for_url("**/feed/**", timeout=120000)
            print("✓ Login detected!")
            context.storage_state(path=str(state_file))
            print(f"✓ Saved authenticated LinkedIn state to: {state_file}")
        except Exception as e:
            print(f"Timed out or closed before feed reached: {e}")
            context.storage_state(path=str(state_file))
        finally:
            browser.close()

def login_naukri():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    state_file = SESSIONS_DIR / "naukri_state.json"
    print("\n=======================================================")
    print("  [2/2] Authenticating Naukri in Visible Browser")
    print("=======================================================")
    print("Opening browser... Log in to your Naukri account.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.naukri.com/nlogin/login")

        try:
            page.wait_for_url("**/mnjuser/**", timeout=120000)
            print("✓ Naukri Login detected!")
            context.storage_state(path=str(state_file))
            print(f"✓ Saved authenticated Naukri state to: {state_file}")
        except Exception as e:
            print(f"Timed out or closed: {e}")
            context.storage_state(path=str(state_file))
        finally:
            browser.close()

if __name__ == "__main__":
    choice = sys.argv[1] if len(sys.argv) > 1 else "both"
    if choice in ["linkedin", "both"]:
        login_linkedin()
    if choice in ["naukri", "both"]:
        login_naukri()
    print("\n🎉 Authentication complete! Sessions saved.")
