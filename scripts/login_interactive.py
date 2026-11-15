#!/usr/bin/env python3
"""
Interactive Session Authenticator for LinkedIn & Naukri
Opens a visible browser on your machine, allowing you to log in once.
Saves session cookies and localStorage to data/browser_sessions/ so
automated runners can operate directly without triggering Cloudflare Turnstile.
"""
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = PROJECT_ROOT / "data" / "browser_sessions"

# Load .env if present
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

def login_linkedin():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    state_file = SESSIONS_DIR / "linkedin_state.json"
    print("\n=======================================================")
    print("  [1/2] Authenticating LinkedIn in Visible Browser")
    print("=======================================================")
    print("Opening browser on your screen...")
    print("Log in to your LinkedIn account (solve any captcha or 2FA if prompted).")
    print("Once logged in and viewing your feed, session will be saved automatically.\n")

    email = os.getenv("LINKEDIN_EMAIL", "")
    password = os.getenv("LINKEDIN_PASSWORD", "")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")
        page.wait_for_timeout(2000)

        try:
            if email and page.locator("#username").is_visible():
                page.fill("#username", email)
            if password and page.locator("#password").is_visible():
                page.fill("#password", password)
        except Exception:
            pass

        print("Waiting for login completion (up to 3 minutes)...")
        try:
            # Wait for feed or navigation bar
            page.wait_for_function(
                "() => window.location.href.includes('feed') || window.location.href.includes('mynetwork') || !!document.querySelector('.global-nav__me')",
                timeout=180000
            )
            page.wait_for_timeout(3000)
            print("✓ LinkedIn Login successfully detected!")
            context.storage_state(path=str(state_file))
            print(f"✓ Saved authenticated LinkedIn state to: {state_file}")
        except Exception as e:
            print(f"Saving current state (browser may have been closed or timed out): {e}")
            try:
                context.storage_state(path=str(state_file))
            except Exception:
                pass
        finally:
            try:
                browser.close()
            except Exception:
                pass

def login_naukri():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    state_file = SESSIONS_DIR / "naukri_state.json"
    print("\n=======================================================")
    print("  [2/2] Authenticating Naukri in Visible Browser")
    print("=======================================================")
    print("Opening browser on your screen...")
    print("Log in to your Naukri account.")
    print("Once logged in and viewing your dashboard, session will be saved automatically.\n")

    email = os.getenv("NAUKRI_EMAIL", "")
    password = os.getenv("NAUKRI_PASSWORD", "")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.naukri.com/nlogin/login")
        page.wait_for_timeout(3000)

        try:
            u_input = page.locator("input[placeholder*='Username'], input[placeholder*='Email'], #usernameField").first
            p_input = page.locator("input[type='password'], #passwordField").first
            if email and u_input.is_visible():
                u_input.fill(email)
            if password and p_input.is_visible():
                p_input.fill(password)
        except Exception:
            pass

        print("Waiting for login completion (up to 3 minutes)...")
        try:
            page.wait_for_function(
                "() => window.location.href.includes('mnjuser') || window.location.href.includes('my-naukri') || !!document.querySelector('.nI-gNb-drawer')",
                timeout=180000
            )
            page.wait_for_timeout(3000)
            print("✓ Naukri Login successfully detected!")
            context.storage_state(path=str(state_file))
            print(f"✓ Saved authenticated Naukri state to: {state_file}")
        except Exception as e:
            print(f"Saving current state (browser may have been closed or timed out): {e}")
            try:
                context.storage_state(path=str(state_file))
            except Exception:
                pass
        finally:
            try:
                browser.close()
            except Exception:
                pass

if __name__ == "__main__":
    choice = sys.argv[1] if len(sys.argv) > 1 else "both"
    if choice in ["linkedin", "both"]:
        login_linkedin()
    if choice in ["naukri", "both"]:
        login_naukri()
    print("\n🎉 Authentication complete! Sessions saved.")
