import time
from pathlib import Path
from typing import Optional
from playwright.sync_api import sync_playwright, BrowserContext
from src.models import ProfileUpdatePayload
from src.config import settings, DATA_DIR
from src.notifier.discord import notifier

class LinkedInProfileUpdater:
    def __init__(self, email: Optional[str] = None, password: Optional[str] = None):
        self.email = email or settings.config_data.get("linkedin", {}).get("email")
        self.password = password or settings.config_data.get("linkedin", {}).get("password")
        self.user_data_dir = DATA_DIR / "browser_sessions" / "linkedin"

    def update_profile(self, payload: ProfileUpdatePayload, dry_run: bool = False) -> bool:
        """
        Updates LinkedIn Headline and About/Summary using Playwright with persistent session.
        If dry_run is True, simply prints the optimized content.
        """
        print(f"\n[LinkedIn Profile Updater] Prepared ATS Optimized Profile Payload:")
        print(f"--- Headline ({len(payload.headline)} chars) ---\n{payload.headline}")
        print(f"--- Summary Preview ---\n{payload.summary[:200]}...\n")

        if dry_run:
            print("[LinkedIn Profile Updater] (Dry Run mode) Skipping browser submission.")
            return True

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        is_ci = os.getenv("CI", "false").lower() == "true" or os.getenv("HEADLESS", "false").lower() == "true" or not os.getenv("DISPLAY")
        headless = True if is_ci else settings.config_data.get("general", {}).get("headless_browser", False)

        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
            )
            page = browser.new_page()
            try:
                print("[LinkedIn Profile Updater] Opening LinkedIn...")
                page.goto("https://www.linkedin.com/feed/", timeout=30000)
                page.wait_for_timeout(3000)

                # Check if login is needed
                if "login" in page.url or "feed" not in page.url:
                    if self.email and self.password:
                        print("[LinkedIn] Logging in...")
                        page.goto("https://www.linkedin.com/login")
                        page.fill("#username", self.email)
                        page.fill("#password", self.password)
                        page.click("button[type='submit']")
                        page.wait_for_timeout(5000)
                    else:
                        print("[LinkedIn] Please log in to your LinkedIn account in the opened browser window.")
                        page.wait_for_url("**/feed/**", timeout=60000)

                # Navigate to profile edit
                print("[LinkedIn] Navigating to profile...")
                page.goto("https://www.linkedin.com/in/me/", timeout=30000)
                page.wait_for_timeout(4000)

                # Click Intro Edit Button
                edit_btn = page.locator("button[aria-label*='Edit intro']").first
                if edit_btn.is_visible():
                    edit_btn.click()
                    page.wait_for_timeout(2000)
                    
                    # Fill Headline
                    headline_input = page.locator("input#single-line-text-input").or_(page.locator("input[name='headline']")).first
                    if headline_input.is_visible():
                        headline_input.fill(payload.headline)
                        print("[LinkedIn] Headline updated.")

                    # Save intro
                    save_btn = page.locator("button[data-action='save']").or_(page.locator("button:has-text('Save')")).first
                    if save_btn.is_visible():
                        save_btn.click()
                        page.wait_for_timeout(3000)
                        print("[LinkedIn] Intro changes saved successfully.")
                        notifier.notify_profile_updated("LinkedIn", payload.headline, payload.summary)

                print("✅ [LinkedIn Profile Updater] Profile update finished!")
                return True
            except Exception as e:
                print(f"[LinkedIn Profile Updater] Note: {e}")
                return False
            finally:
                browser.close()
