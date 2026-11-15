import os
import time
import urllib.parse
from typing import List, Optional
from playwright.sync_api import sync_playwright, Page
from src.engines.base import BaseJobEngine
from src.models import JobPost, Platform, ApplyType, ApplicationRecord, ApplicationStatus
from src.engines.external_handler import ExternalRedirectHandler
from src.config import settings, DATA_DIR
from src.notifier.discord import notifier

class LinkedInEasyApplyEngine(BaseJobEngine):
    def __init__(self, profile, vector_store, generator, tracker, external_handler: ExternalRedirectHandler):
        super().__init__(profile, vector_store, generator, tracker)
        self.external_handler = external_handler
        self.email = settings.config_data.get("linkedin", {}).get("email")
        self.password = settings.config_data.get("linkedin", {}).get("password")
        self.user_data_dir = DATA_DIR / "browser_sessions" / "linkedin"

    def search_jobs(self, keywords: List[str], locations: List[str], limit: int = 15) -> List[JobPost]:
        """Search LinkedIn jobs using resilient HTTP parsing with Easy Apply filter enabled."""
        import requests
        from bs4 import BeautifulSoup

        jobs: List[JobPost] = []
        target_kw = keywords[0] if keywords else "Cloud Engineer"
        kw = urllib.parse.quote(target_kw)
        loc = urllib.parse.quote(locations[0] if locations else "Pune")
        search_url = f"https://www.linkedin.com/jobs/search/?keywords={kw}&location={loc}&f_AL=true"
        print(f"[LinkedIn Engine] Fetching jobs via endpoint: {search_url}")

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
            }
            resp = requests.get(search_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.select("div.base-card, li div.base-search-card")
                print(f"[LinkedIn Engine] Found {len(cards)} live job postings on page.")

                for idx, card in enumerate(cards[:limit]):
                    try:
                        title_el = card.select_one("h3.base-search-card__title, a.base-card__full-link")
                        link_el = card.select_one("a.base-card__full-link, a")
                        comp_el = card.select_one("h4.base-search-card__subtitle, a.job-card-container__primary-description")
                        loc_el = card.select_one("span.job-search-card__location")

                        if not title_el or not link_el:
                            continue

                        title = title_el.get_text(strip=True)
                        job_url = link_el.get("href", "")
                        if "?" in job_url:
                            job_url = job_url.split("?")[0]
                        job_url = job_url.replace("in.linkedin.com", "www.linkedin.com")
                        if not job_url.startswith("http"):
                            continue

                        company = comp_el.get_text(strip=True) if comp_el else "Company"
                        location = loc_el.get_text(strip=True) if loc_el else "Pune"

                        job_id = f"li_{idx}_{int(time.time())}"
                        if "view/" in job_url:
                            job_id = "li_" + job_url.split("view/")[1].split("/")[0].split("?")[0]

                        # Calculate RAG match score
                        score, matched_skills, _ = self.vector_store.match_job(title, f"{title} {company}", self.profile.skills)

                        job_post = JobPost(
                            platform=Platform.LINKEDIN,
                            job_id=job_id,
                            title=title,
                            company=company,
                            location=location,
                            job_url=job_url,
                            description=f"{title} at {company}",
                            apply_type=ApplyType.EASY_APPLY,
                            match_score=score,
                            skills_matched=matched_skills
                        )
                        jobs.append(job_post)
                        print(f"  [LinkedIn Match] {title} @ {company} (Score: {int(score*100)}%)")
                    except Exception as e:
                        continue
                return jobs
        except Exception as e:
            print(f"[LinkedIn Search Warning via HTTP] {e}")

        return jobs

    def apply_to_job(self, job: JobPost) -> bool:
        """Applies to a LinkedIn job or delegates to external handler if redirected."""
        if self.tracker.is_already_applied(job.job_id):
            print(f"[LinkedIn] Job '{job.title}' at {job.company} already applied. Skipping.")
            return False

        if job.apply_type == ApplyType.EXTERNAL_REDIRECT and job.external_url:
            print(f"[LinkedIn] Job redirects to external website. Delegating to Antigravity CLI...")
            return self.external_handler.handle_redirect(job, interactive=False)

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        is_ci = os.getenv("CI", "false").lower() == "true" or os.getenv("HEADLESS", "false").lower() == "true" or not os.getenv("DISPLAY")
        headless = True if is_ci else settings.config_data.get("general", {}).get("headless_browser", False)

        state_file = DATA_DIR / "browser_sessions" / "linkedin_state.json"
        
        with sync_playwright() as p:
            if state_file.exists():
                browser = p.chromium.launch(
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
                )
                context = browser.new_context(
                    storage_state=str(state_file),
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                )
                page = context.new_page()
            else:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=str(self.user_data_dir),
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
                )
                page = browser.new_page()

            try:
                # 1. Ensure authenticated session if credentials exist and not restored
                if not state_file.exists():
                    self._ensure_login(page)

                # 2. Navigate to Job URL (normalizing to www.linkedin.com)
                target_url = job.job_url.replace("in.linkedin.com", "www.linkedin.com")
                print(f"[LinkedIn] Navigating to job: {target_url}")
                page.goto(target_url, timeout=35000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                # 3. Locate visible Apply Button
                candidates = page.locator(".top-card-layout__cta-container button, .top-card-layout__cta-container a, button.apply-button, button.jobs-apply-button, button:has-text('Apply'), a:has-text('Apply')").all()
                visible_apply = [b for b in candidates if b.is_visible() and "apply" in b.inner_text().lower()]

                if not visible_apply:
                    print(f"[LinkedIn] No direct apply button visible for {job.title}. Checking external portal links...")
                    ext_link = page.locator("a[href*='workday'], a[href*='greenhouse'], a[href*='lever.co'], a[href*='taleo'], a[href*='ashby']").first
                    if ext_link.is_visible():
                        job.external_url = ext_link.get_attribute("href")
                        job.apply_type = ApplyType.EXTERNAL_REDIRECT
                        return self.external_handler.handle_redirect(job, page=page, interactive=False)
                    return False

                apply_btn = visible_apply[0]
                btn_text = apply_btn.inner_text().lower()
                href = apply_btn.get_attribute("href") or ""
                
                # Check for External redirect link
                if "easy apply" not in btn_text and (href.startswith("http") or "external" in btn_text):
                    print(f"[LinkedIn] External portal redirect detected: '{btn_text}' -> {href or 'popup'}")
                    if href.startswith("http") and "linkedin.com" not in href:
                        job.external_url = href
                    else:
                        try:
                            with page.expect_popup(timeout=8000) as popup_info:
                                apply_btn.click(force=True)
                            ext_page = popup_info.value
                            job.external_url = ext_page.url
                            ext_page.close()
                        except Exception:
                            job.external_url = job.job_url
                    job.apply_type = ApplyType.EXTERNAL_REDIRECT
                    return self.external_handler.handle_redirect(job, page=page, interactive=False)

                # Click Apply button
                print(f"[LinkedIn] Clicking apply button for {job.title}...")
                popup_url = None
                try:
                    with page.expect_popup(timeout=2500) as popup_info:
                        apply_btn.click(force=True)
                    popup = popup_info.value
                    popup_url = popup.url
                    popup.close()
                except Exception:
                    # No popup window opened; clicked in-page
                    pass

                if popup_url and "linkedin.com" not in popup_url:
                    print(f"[LinkedIn] External career portal opened: {popup_url}")
                    job.external_url = popup_url
                    job.apply_type = ApplyType.EXTERNAL_REDIRECT
                    return self.external_handler.handle_redirect(job, page=page, interactive=False)

                page.wait_for_timeout(2000)

                # Check if Easy Apply modal appeared
                modal = page.locator("div.jobs-easy-apply-modal, div[role='dialog']").first
                if not modal.is_visible():
                    print(f"[LinkedIn] Easy Apply modal did not appear (guest session or sign-in required).")
                    print(f"Preparing application dossier for Antigravity CLI assist...")
                    job.apply_type = ApplyType.EXTERNAL_REDIRECT
                    return self.external_handler.handle_redirect(job, page=page, interactive=False)

                # Iterate through multi-step dialog
                max_steps = 10
                for step in range(max_steps):
                    # Answer inputs on current step
                    self._answer_form_inputs(page, job.title)

                    # Check for Submit button
                    submit_btn = page.locator("button[aria-label*='Submit application']").or_(
                        page.locator("button:has-text('Submit application')")
                    ).first
                    if submit_btn.is_visible():
                        submit_btn.click(force=True)
                        page.wait_for_timeout(3000)
                        print(f"🎉 [LinkedIn] Successfully submitted Easy Apply for {job.title} at {job.company}!")
                        
                        record = ApplicationRecord(
                            job_id=job.job_id,
                            platform=Platform.LINKEDIN.value,
                            company=job.company,
                            title=job.title,
                            job_url=job.job_url,
                            apply_type="easy_apply",
                            status=ApplicationStatus.APPLIED,
                            match_score=job.match_score,
                            notes="Applied via automated Easy Apply with RAG answers."
                        )
                        self.tracker.record_job(record)
                        notifier.notify_job_applied(
                            title=job.title,
                            company=job.company,
                            platform="LinkedIn Easy Apply",
                            match_score=job.match_score,
                            job_url=job.job_url,
                            location=job.location
                        )
                        return True

                    # Check for Next / Review button
                    next_btn = page.locator("button[aria-label*='Continue to next step']").or_(
                        page.locator("button:has-text('Next')")
                    ).or_(page.locator("button:has-text('Review')")).first

                    if next_btn.is_visible():
                        next_btn.click(force=True)
                        page.wait_for_timeout(1500)
                    else:
                        break

                print(f"[LinkedIn] Completed form steps for {job.title}.")
                return True
            except Exception as e:
                print(f"[LinkedIn Apply Error] {e}")
                return False
            finally:
                browser.close()

    def _ensure_login(self, page):
        """Ensure LinkedIn session is authenticated."""
        try:
            if not self.email or not self.password:
                return
            page.goto("https://www.linkedin.com/feed/", timeout=25000)
            page.wait_for_timeout(3000)
            if "login" in page.url or "feed" not in page.url:
                print("[LinkedIn] Authenticating account session...")
                page.goto("https://www.linkedin.com/login", timeout=25000)
                page.fill("#username", self.email)
                page.fill("#password", self.password)
                page.click("button[type='submit']")
                page.wait_for_timeout(4000)
        except Exception as e:
            print(f"[LinkedIn Auth Note] {e}")

    def _answer_form_inputs(self, page: Page, job_title: str):
        """Fills text inputs, selects, and radios using RAG generator."""
        # Fill standard text inputs
        inputs = page.locator("div.jobs-easy-apply-modal input[type='text'], div.jobs-easy-apply-modal input[type='number']").all()
        for inp in inputs:
            try:
                if not inp.is_visible():
                    continue
                val = inp.input_value()
                if not val:
                    # Find label
                    input_id = inp.get_attribute("id") or ""
                    label = page.locator(f"label[for='{input_id}']").first
                    label_text = label.inner_text() if label.is_visible() else "Question"
                    answer = self.generator.answer_screening_question(label_text, job_title)
                    inp.fill(answer)
            except Exception:
                continue

        # Fill dropdown selects
        selects = page.locator("div.jobs-easy-apply-modal select").all()
        for sel in selects:
            try:
                if not sel.is_visible():
                    continue
                # Select Yes or first positive option
                options = sel.locator("option").all_inner_texts()
                for opt in options:
                    if opt.lower() in ["yes", "authorized", "1", "2", "3"]:
                        sel.select_option(label=opt)
                        break
            except Exception:
                continue

        # Radios
        radios = page.locator("div.jobs-easy-apply-modal input[type='radio'][value='Yes']").all()
        for r in radios:
            try:
                if r.is_visible() and not r.is_checked():
                    r.check()
            except Exception:
                continue
