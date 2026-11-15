import os
import time
import urllib.parse
from typing import List
from playwright.sync_api import sync_playwright
from src.engines.base import BaseJobEngine
from src.models import JobPost, Platform, ApplyType, ApplicationRecord, ApplicationStatus
from src.engines.external_handler import ExternalRedirectHandler
from src.config import settings, DATA_DIR
from src.notifier.discord import notifier

class NaukriApplyEngine(BaseJobEngine):
    def __init__(self, profile, vector_store, generator, tracker, external_handler: ExternalRedirectHandler):
        super().__init__(profile, vector_store, generator, tracker)
        self.external_handler = external_handler
        self.email = settings.config_data.get("naukri", {}).get("email")
        self.password = settings.config_data.get("naukri", {}).get("password")
        self.user_data_dir = DATA_DIR / "browser_sessions" / "naukri"

    def search_jobs(self, keywords: List[str], locations: List[str], limit: int = 15) -> List[JobPost]:
        """Search jobs on Naukri with keywords."""
        jobs: List[JobPost] = []
        target_kw = keywords[0] if keywords else "Cloud Engineer"
        kw_slug = target_kw.lower().replace(" ", "-")
        loc_slug = locations[0].lower().replace(" ", "-") if locations else "pune"
        search_url = f"https://www.naukri.com/{kw_slug}-jobs-in-{loc_slug}"

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
                print(f"[Naukri Engine] Navigating to search: {search_url}")
                page.goto(search_url, timeout=35000)
                page.wait_for_timeout(4000)

                # Find job articles
                articles = page.locator("div.cust-job-tuple, div.srp-jobtuple-wrapper, article.jobTuple, div[data-job-id]").all()
                print(f"[Naukri Engine] Found {len(articles)} job listings.")

                for idx, art in enumerate(articles[:limit]):
                    try:
                        title_elem = art.locator("a.title").first
                        if not title_elem.is_visible():
                            continue
                        title = title_elem.inner_text().strip()
                        job_url = title_elem.get_attribute("href") or ""

                        comp_elem = art.locator("a.comp-name").first
                        company = comp_elem.inner_text().strip() if comp_elem.is_visible() else "Company"

                        loc_elem = art.locator(".loc-wrap, .location").first
                        location = loc_elem.inner_text().strip() if loc_elem.is_visible() else "India"

                        job_id = f"naukri_{idx}_{int(time.time())}"
                        if job_url:
                            # Parse unique jobId if present in query
                            parsed = urllib.parse.urlparse(job_url)
                            query_params = urllib.parse.parse_qs(parsed.query)
                            if "jobId" in query_params:
                                job_id = f"naukri_{query_params['jobId'][0]}"

                        desc_elem = art.locator(".job-desc, .row4").first
                        description = desc_elem.inner_text().strip() if desc_elem.is_visible() else ""

                        # Evaluate Match Score with RAG
                        score, matched_skills, _ = self.vector_store.match_job(title, description, self.profile.skills)

                        # Check for external apply flag
                        ext_tag = art.locator(":text('Apply on company website')").first
                        has_ext_tag = ext_tag.is_visible()

                        job_post = JobPost(
                            platform=Platform.NAUKRI,
                            job_id=job_id,
                            title=title,
                            company=company,
                            location=location,
                            job_url=job_url,
                            description=description[:2000],
                            apply_type=ApplyType.EXTERNAL_REDIRECT if has_ext_tag else ApplyType.DIRECT,
                            match_score=score,
                            skills_matched=matched_skills
                        )
                        jobs.append(job_post)
                    except Exception:
                        continue
            except Exception as e:
                print(f"[Naukri Search Warning] {e}")
            finally:
                browser.close()

        return jobs

    def apply_to_job(self, job: JobPost) -> bool:
        """Applies to a Naukri job, or intercepts external redirect to hand off to Antigravity CLI."""
        if self.tracker.is_already_applied(job.job_id):
            print(f"[Naukri] Job '{job.title}' at {job.company} already applied. Skipping.")
            return False

        if job.apply_type == ApplyType.EXTERNAL_REDIRECT and job.external_url:
            print(f"[Naukri] Job redirects externally. Handing off to Antigravity CLI...")
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

                # Look for Apply Button
                apply_btn = page.locator("button#apply-button, button:has-text('Apply')").first
                if not apply_btn.is_visible():
                    print(f"[Naukri] No apply button found for {job.title}.")
                    return False

                btn_text = apply_btn.inner_text().lower()
                # Check if it redirects to external website
                if "company site" in btn_text or "external" in btn_text:
                    print(f"[Naukri] External redirect detected on apply button: '{btn_text}'")
                    with page.expect_popup() as popup_info:
                        apply_btn.click()
                    ext_page = popup_info.value
                    job.external_url = ext_page.url
                    job.apply_type = ApplyType.EXTERNAL_REDIRECT
                    ext_page.close()
                    return self.external_handler.handle_redirect(job, interactive=True)

                # Direct Apply
                apply_btn.click()
                page.wait_for_timeout(3000)

                # Handle Questionnaire / Chatbot if presented
                self._handle_naukri_questionnaire(page, job.title)

                print(f"🎉 [Naukri] Successfully applied to {job.title} at {job.company}!")
                record = ApplicationRecord(
                    job_id=job.job_id,
                    platform=Platform.NAUKRI.value,
                    company=job.company,
                    title=job.title,
                    job_url=job.job_url,
                    apply_type="direct",
                    status=ApplicationStatus.APPLIED,
                    match_score=job.match_score,
                    notes="Applied via Naukri direct apply with RAG answers."
                )
                self.tracker.record_job(record)
                notifier.notify_job_applied(
                    title=job.title,
                    company=job.company,
                    platform="Naukri Direct Apply",
                    match_score=job.match_score,
                    job_url=job.job_url,
                    location=job.location
                )
                return True
            except Exception as e:
                print(f"[Naukri Apply Error] {e}")
                return False
            finally:
                browser.close()

    def _handle_naukri_questionnaire(self, page, job_title: str):
        """Answers recruiter questionnaire modal if it appears."""
        try:
            questions = page.locator("div.questionnaire-box, div.chatbot-container").first
            if questions.is_visible():
                inputs = page.locator("input[type='text'], textarea").all()
                for inp in inputs:
                    if inp.is_visible() and not inp.input_value():
                        inp.fill(self.generator.answer_screening_question("Experience and skills", job_title))
                
                submit = page.locator("button:has-text('Submit'), button:has-text('Save & Apply')").first
                if submit.is_visible():
                    submit.click()
                    page.wait_for_timeout(2000)
        except Exception:
            pass
