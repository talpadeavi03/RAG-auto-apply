import os
import time
from pathlib import Path
from typing import Optional, Dict, Any
from playwright.sync_api import sync_playwright, Page
from src.models import JobPost, CandidateProfile, ApplicationRecord, ApplicationStatus
from src.tracker.database import ApplicationTracker
from src.config import DATA_DIR, settings
from src.notifier.discord import notifier

class AutonomousFormSubmitter:
    """
    Submits applications to career portals (Greenhouse, Lever, Ashby, Workday,
    and standard company application forms) autonomously on cloud runners.
    Handles resume file uploads, standard candidate fields, and RAG screening answers.
    """
    def __init__(self, profile: CandidateProfile, vector_store, generator, tracker: ApplicationTracker):
        self.profile = profile
        self.vector_store = vector_store
        self.generator = generator
        self.tracker = tracker
        
        # Locate candidate PDF resume
        resume_candidates = [
            DATA_DIR / "resumes" / "avinash_talpade_resume.pdf",
            DATA_DIR / "resumes" / "AT_26_AI.pdf",
            Path("data/resumes/avinash_talpade_resume.pdf"),
            Path("data/resumes/AT_26_AI.pdf")
        ]
        self.resume_path = next((p for p in resume_candidates if p.exists()), None)

    def submit_application(self, job: JobPost, target_url: str, page: Optional[Page] = None) -> bool:
        """
        Navigates to external portal, fills out all form fields,
        attaches resume PDF, and submits automatically.
        Uses existing page if provided, or launches a new browser context.
        """
        print(f"\n[Autonomous Form Submitter] Opening application portal: {target_url}")
        
        if page:
            return self._execute_form_filling(page, job, target_url)

        is_ci = os.getenv("CI", "false").lower() == "true" or os.getenv("HEADLESS", "false").lower() == "true" or not os.getenv("DISPLAY")
        headless = True if is_ci else settings.config_data.get("general", {}).get("headless_browser", False)

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
            )
            new_page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
            try:
                return self._execute_form_filling(new_page, job, target_url)
            finally:
                browser.close()

    def _execute_form_filling(self, page: Page, job: JobPost, target_url: str) -> bool:
        try:
            if page.url != target_url:
                page.goto(target_url, timeout=40000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # 1. If there is an 'Apply' or 'Apply for this job' button, click it to show form
            apply_triggers = page.locator("a:has-text('Apply'), button:has-text('Apply'), a:has-text('Apply for this job'), button:has-text('Apply for this job')").all()
            for trigger in apply_triggers:
                try:
                    if trigger.is_visible() and ("apply" in trigger.inner_text().lower()):
                        trigger.click(force=True)
                        page.wait_for_timeout(2000)
                        break
                except Exception:
                    pass

            # 2. Upload Resume if file input exists
            if self.resume_path and self.resume_path.exists():
                file_inputs = page.locator("input[type='file']").all()
                for finp in file_inputs:
                    try:
                        finp.set_input_files(str(self.resume_path.resolve()))
                        print(f"[Autonomous Form Submitter] ✓ Attached resume PDF: {self.resume_path.name}")
                        page.wait_for_timeout(2000)
                        break
                    except Exception as e:
                        print(f"[Form Submitter] Resume upload note: {e}")

            # 3. Fill text inputs
            self._fill_standard_fields(page, job)

            # 4. Fill textareas with RAG generated responses
            textareas = page.locator("textarea").all()
            for ta in textareas:
                try:
                    if not ta.is_visible():
                        continue
                    val = ta.input_value()
                    if not val:
                        label = self._find_label(page, ta)
                        answer = self.generator.answer_screening_question(label or "Why are you interested in this role?", job.title)
                        ta.fill(answer)
                        print(f"  [Form Answer] Filled question '{label[:40]}...' with RAG pitch.")
                except Exception:
                    pass

            # 5. Check mandatory checkboxes (Terms, Privacy, Consent)
            checkboxes = page.locator("input[type='checkbox']").all()
            for cb in checkboxes:
                try:
                    if cb.is_visible() and not cb.is_checked():
                        cb.check(force=True)
                except Exception:
                    pass

            # 6. Locate Submit button
            submit_btn = page.locator(
                "button[type='submit'], input[type='submit'], button:has-text('Submit Application'), button:has-text('Submit application'), button:has-text('Submit'), button:has-text('Send Application')"
            ).first

            if not submit_btn.is_visible():
                print("[Form Submitter] No direct submit button visible after filling form.")
                return False

            print(f"[Autonomous Form Submitter] Submitting application for {job.title} at {job.company}...")
            submit_btn.click(force=True)
            page.wait_for_timeout(6000)

            # 7. Verify submission confirmation
            page_text = page.locator("body").inner_text().lower()
            success_keywords = ["thank you", "application submitted", "received your application", "successfully applied", "application received"]
            is_success = any(kw in page_text for kw in success_keywords) or "confirmation" in page.url.lower() or "thanks" in page.url.lower()

            if is_success:
                print(f"🎉 [Autonomous Form Submitter] SUCCESS! Application submitted for {job.title} at {job.company}!")
                
                # Record as APPLIED in tracker
                record = ApplicationRecord(
                    job_id=job.job_id,
                    platform=job.platform.value,
                    company=job.company,
                    title=job.title,
                    job_url=job.job_url,
                    apply_type="external_portal",
                    external_url=target_url,
                    status=ApplicationStatus.APPLIED,
                    match_score=job.match_score,
                    notes="Autonomously submitted on cloud runner via Playwright form submitter."
                )
                self.tracker.record_job(record)

                # Discord Notification
                notifier.notify_job_applied(
                    title=job.title,
                    company=job.company,
                    platform=job.platform.value,
                    match_score=job.match_score,
                    apply_type="Autonomous Cloud Portal Submitter"
                )
                return True
            else:
                print(f"[Form Submitter] Form submitted, awaiting employer confirmation.")
                return False

        except Exception as e:
            print(f"[Autonomous Form Submitter Error] {e}")
            return False

    def _fill_standard_fields(self, page: Page, job: JobPost):
        """Intelligently detects and populates candidate details into inputs."""
        full_name = getattr(self.profile, "full_name", None) or getattr(self.profile, "name", "Avinash Vishnu Talpade")
        name_parts = full_name.split()
        first_name = name_parts[0] if name_parts else "Avinash"
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else "Talpade"
        exp_years = getattr(self.profile, "years_of_experience", None) or getattr(self.profile, "experience_years", 3.5)
        notice_days = getattr(self.profile, "notice_period_days", 15)
        current_comp = getattr(self.profile, "current_company", "Accenture")

        field_mappings = [
            # Name
            (["first_name", "firstname", "first name", "given name"], first_name),
            (["last_name", "lastname", "last name", "family name", "surname"], last_name),
            (["full_name", "fullname", "full name", "applicant_name", "name"], full_name),
            # Contact
            (["email", "e-mail", "email address"], self.profile.email),
            (["phone", "mobile", "telephone", "phone number", "contact number"], self.profile.phone),
            (["location", "city", "current location", "address"], "Pune, India"),
            # Links
            (["linkedin", "linkedin profile", "linkedin url"], self.profile.linkedin_url or "https://www.linkedin.com/in/avinashtalpade"),
            (["github", "github profile", "github url"], f"https://github.com/{self.profile.github_username or 'talpadeavi03'}"),
            (["portfolio", "website", "personal website", "portfolio url"], self.profile.portfolio_url or "https://talpadeavi03.github.io/intro"),
            # Experience & Notice
            (["company", "current company", "employer"], current_comp),
            (["experience", "years of experience", "total experience"], str(exp_years)),
            (["notice", "notice period", "availability"], f"{notice_days} days"),
        ]

        inputs = page.locator("input[type='text'], input[type='email'], input[type='tel'], input:not([type])").all()
        for inp in inputs:
            try:
                if not inp.is_visible():
                    continue
                current_val = inp.input_value()
                if current_val:
                    continue

                field_name = (inp.get_attribute("name") or "").lower()
                field_id = (inp.get_attribute("id") or "").lower()
                field_placeholder = (inp.get_attribute("placeholder") or "").lower()
                label = self._find_label(page, inp).lower()

                combined_identifier = f"{field_name} {field_id} {field_placeholder} {label}"

                for keywords, value in field_mappings:
                    if any(kw in combined_identifier for kw in keywords):
                        inp.fill(value)
                        break
            except Exception:
                continue

    def _find_label(self, page: Page, element) -> str:
        """Finds the text label for an input element."""
        try:
            elem_id = element.get_attribute("id")
            if elem_id:
                label_el = page.locator(f"label[for='{elem_id}']").first
                if label_el.is_visible():
                    return label_el.inner_text().strip()
            
            # Check parent label
            parent_text = element.evaluate("el => el.closest('label')?.innerText || el.closest('.form-group')?.querySelector('label')?.innerText || ''")
            if parent_text:
                return parent_text.strip()
        except Exception:
            pass
        return ""
