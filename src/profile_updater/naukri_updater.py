import time
from pathlib import Path
from typing import Optional
from playwright.sync_api import sync_playwright
from src.models import ProfileUpdatePayload
from src.config import settings, DATA_DIR

class NaukriProfileUpdater:
    def __init__(self, email: Optional[str] = None, password: Optional[str] = None):
        self.email = email or settings.config_data.get("naukri", {}).get("email")
        self.password = password or settings.config_data.get("naukri", {}).get("password")
        self.user_data_dir = DATA_DIR / "browser_sessions" / "naukri"

    def update_profile(self, payload: ProfileUpdatePayload, dry_run: bool = False) -> bool:
        """
        Updates Naukri Resume Headline and Profile Summary.
        Refreshing these fields updates the 'Last Active' timestamp which
        prioritizes the profile on recruiter searches.
        """
        print(f"\n[Naukri Profile Updater] Prepared ATS Optimized Profile Payload:")
        print(f"--- Resume Headline ({len(payload.headline)} chars / max 250) ---\n{payload.headline}")
        print(f"--- Profile Summary Preview ---\n{payload.summary[:200]}...\n")

        if dry_run:
            print("[Naukri Profile Updater] (Dry Run mode) Skipping browser submission.")
            return True

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        headless = settings.config_data.get("general", {}).get("headless_browser", False)

        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = browser.new_page()
            try:
                print("[Naukri Profile Updater] Opening Naukri...")
                page.goto("https://www.naukri.com/mnjuser/profile", timeout=35000)
                page.wait_for_timeout(3000)

                # Check if login is needed
                if "login" in page.url:
                    if self.email and self.password:
                        print("[Naukri] Logging in...")
                        page.fill("#usernameField", self.email)
                        page.fill("#passwordField", self.password)
                        page.click("button[type='submit']")
                        page.wait_for_timeout(5000)
                    else:
                        print("[Naukri] Please log in to your Naukri account in the opened browser window.")
                        page.wait_for_url("**/profile**", timeout=60000)

                # Update Resume Headline
                print("[Naukri] Locating Resume Headline section...")
                headline_edit = page.locator("span.edit.icon:right-of(:text('Resume Headline'))").or_(
                    page.locator("div.resumeHeadline span.edit")
                ).first
                if headline_edit.is_visible():
                    headline_edit.click()
                    page.wait_for_timeout(1000)
                    textarea = page.locator("textarea#resumeHeadlineTxt").or_(page.locator("textarea.resumeHeadlineTxt")).first
                    if textarea.is_visible():
                        textarea.fill(payload.headline[:250])
                        page.click("button.btn-dark-ot:has-text('Save')")
                        page.wait_for_timeout(2000)
                        print("[Naukri] Resume Headline updated and timestamp refreshed.")

                # Update Profile Summary
                summary_edit = page.locator("span.edit.icon:right-of(:text('Profile Summary'))").or_(
                    page.locator("div.profileSummary span.edit")
                ).first
                if summary_edit.is_visible():
                    summary_edit.click()
                    page.wait_for_timeout(1000)
                    summary_area = page.locator("textarea#profileSummaryTxt").or_(page.locator("textarea.profileSummaryTxt")).first
                    if summary_area.is_visible():
                        summary_area.fill(payload.summary)
                        page.click("button.btn-dark-ot:has-text('Save')")
                        page.wait_for_timeout(2000)
                        print("[Naukri] Profile Summary updated.")

                print("✅ [Naukri Profile Updater] Profile updated and refreshed!")
                return True
            except Exception as e:
                print(f"[Naukri Profile Updater] Note: {e}")
                return False
            finally:
                browser.close()
