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
        """Search LinkedIn jobs with Easy Apply filter enabled."""
        jobs: List[JobPost] = []
        kw = urllib.parse.quote(" ".join(keywords[:2]))
        loc = urllib.parse.quote(locations[0] if locations else "Remote")
        # f_LF=f_AL corresponds to Easy Apply filter on LinkedIn
        search_url = f"https://www.linkedin.com/jobs/search/?keywords={kw}&location={loc}&f_AL=true"
        
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
                print(f"[LinkedIn Engine] Navigating to search: {search_url}")
                page.goto(search_url, timeout=35000)
                page.wait_for_timeout(4000)

                # Locate job cards
                card_locators = page.locator("li.jobs-search-results__list-item, div.job-card-container").all()
                print(f"[LinkedIn Engine] Found {len(card_locators)} job cards on page.")

                for idx, card in enumerate(card_locators[:limit]):
                    try:
                        title_elem = card.locator("a.job-card-list__title--link, a.job-card-container__link").first
                        if not title_elem.is_visible():
                            continue
                        title = title_elem.inner_text().strip()
                        job_url = title_elem.get_attribute("href") or ""
                        if job_url.startswith("/"):
                            job_url = "https://www.linkedin.com" + job_url

                        company_elem = card.locator(".job-card-container__primary-description").first
                        company = company_elem.inner_text().strip() if company_elem.is_visible() else "Company"

                        loc_elem = card.locator(".job-card-container__metadata-wrapper li").first
                        location = loc_elem.inner_text().strip() if loc_elem.is_visible() else "Remote"

                        # Extract Job ID
                        job_id = f"li_{idx}_{int(time.time())}"
                        if "view/" in job_url:
                            job_id = "li_" + job_url.split("view/")[1].split("/")[0].split("?")[0]
                        elif "currentJobId=" in job_url:
                            job_id = "li_" + job_url.split("currentJobId=")[1].split("&")[0]

                        # Click card to load job details
                        card.click()
                        page.wait_for_timeout(1500)

                        desc_elem = page.locator("div.jobs-description__content, div#job-details").first
                        description = desc_elem.inner_text().strip() if desc_elem.is_visible() else ""

                        # Evaluate Match Score with RAG
                        score, matched_skills, _ = self.vector_store.match_job(title, description, self.profile.skills)

                        # Check whether Easy Apply button or External Apply button is present
                        easy_apply_btn = page.locator("button.jobs-apply-button:has-text('Easy Apply')").first
                        has_easy_apply = easy_apply_btn.is_visible()

                        job_post = JobPost(
                            platform=Platform.LINKEDIN,
                            job_id=job_id,
                            title=title,
                            company=company,
                            location=location,
                            job_url=job_url,
                            description=description[:2000],
                            apply_type=ApplyType.EASY_APPLY if has_easy_apply else ApplyType.EXTERNAL_REDIRECT,
                            match_score=score,
                            skills_matched=matched_skills
                        )
                        jobs.append(job_post)
                    except Exception as e:
                        continue
            except Exception as e:
                print(f"[LinkedIn Search Warning] {e}")
            finally:
                browser.close()

        return jobs

    def apply_to_job(self, job: JobPost) -> bool:
        """Applies to a LinkedIn job or delegates to external handler if redirected."""
        if self.tracker.is_already_applied(job.job_id):
            print(f"[LinkedIn] Job '{job.title}' at {job.company} already applied. Skipping.")
            return False

        if job.apply_type == ApplyType.EXTERNAL_REDIRECT or job.external_url:
            print(f"[LinkedIn] Job redirects to external website. Delegating to Antigravity CLI...")
            return self.external_handler.handle_redirect(job, interactive=True)

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
                page.goto(job.job_url, timeout=35000)
                page.wait_for_timeout(3000)

                # Look for Apply button
                apply_btn = page.locator("button.jobs-apply-button").first
                if not apply_btn.is_visible():
                    print(f"[LinkedIn] No apply button found for {job.title}.")
                    return False

                btn_text = apply_btn.inner_text().lower()
                if "easy apply" not in btn_text:
                    # External redirect button
                    print(f"[LinkedIn] External redirect button detected: '{btn_text}'")
                    with page.expect_popup() as popup_info:
                        apply_btn.click()
                    ext_page = popup_info.value
                    job.external_url = ext_page.url
                    job.apply_type = ApplyType.EXTERNAL_REDIRECT
                    ext_page.close()
                    return self.external_handler.handle_redirect(job, interactive=True)

                # Open Easy Apply modal
                apply_btn.click()
                page.wait_for_timeout(2000)

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
                        submit_btn.click()
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
                        next_btn.click()
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
