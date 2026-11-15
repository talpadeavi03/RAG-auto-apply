import os
import time
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from playwright.sync_api import sync_playwright, Page
from src.models import JobPost, CandidateProfile, ApplicationRecord, ApplicationStatus
from src.tracker.database import ApplicationTracker
from src.config import DATA_DIR, settings
from src.notifier.discord import notifier

class AutonomousFormSubmitter:
    """
    Autonomous Job Form Submitter for career portals (Lever, Greenhouse, Ashby,
    Workday, and direct company forms).
    Operates 100% autonomously in cloud runners with zero human intervention.
    Strictly uses candidate PDF resume 'AT_26_AI.pdf', handles all screening questions,
    comboboxes, dropdowns, radios, and validation hurdles.
    """
    def __init__(self, profile: CandidateProfile, vector_store, generator, tracker: ApplicationTracker):
        self.profile = profile
        self.vector_store = vector_store
        self.generator = generator
        self.tracker = tracker
        
        # Strictly use AT_26_AI.pdf provided by user
        candidate_resumes = [
            DATA_DIR / "resumes" / "AT_26_AI.pdf",
            Path("data/resumes/AT_26_AI.pdf")
        ]
        self.resume_path = next((p for p in candidate_resumes if p.exists()), None)
        if not self.resume_path or not self.resume_path.exists():
            raise FileNotFoundError("Candidate resume 'AT_26_AI.pdf' not found in data/resumes/")

    def submit_application(self, job: JobPost, target_url: str, page: Optional[Page] = None) -> bool:
        """
        Navigates to external portal, fills all form fields,
        attaches AT_26_AI.pdf, answers screening questions, and submits.
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
                page.goto(target_url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # 1. Click 'Apply' button if on overview page
            apply_triggers = page.locator(
                "a:has-text('Apply'), button:has-text('Apply'), a:has-text('Apply for this job'), button:has-text('Apply for this job'), button:has-text('Apply Now'), a:has-text('Apply Now')"
            ).all()
            for trigger in apply_triggers:
                try:
                    if trigger.is_visible() and ("apply" in trigger.inner_text().lower()):
                        trigger.click(force=True)
                        page.wait_for_timeout(2500)
                        break
                except Exception:
                    pass

            # 2. Upload AT_26_AI.pdf to file inputs
            self._upload_resume(page)

            # 3. Fill standard candidate inputs (text, email, tel, etc.)
            self._fill_standard_fields(page, job)

            # 4. Handle Comboboxes / React Select dropdowns
            self._fill_comboboxes(page)

            # 5. Handle native <select> elements
            self._fill_selects(page)

            # 6. Handle radio buttons (work authorization, sponsorship, etc.)
            self._fill_radio_buttons(page)

            # 7. Check mandatory checkboxes (Terms, Privacy, Consent)
            self._fill_checkboxes(page)

            # 8. Fill textareas and screening questions using RAG Generator
            self._fill_textareas(page, job)

            # 9. Handle any remaining empty required inputs (Hurdle Solver)
            self._solve_remaining_hurdles(page, job)

            # 10. Locate Submit button
            submit_btn = self._find_submit_button(page)
            if not submit_btn or not submit_btn.is_visible():
                print("[Autonomous Form Submitter] No direct submit button visible after filling form.")
                return False

            print(f"[Autonomous Form Submitter] 🚀 Submitting application for {job.title} at {job.company}...")
            submit_btn.scroll_into_view_if_needed()
            submit_btn.click(force=True)
            page.wait_for_timeout(7000)

            # 11. Verify submission confirmation
            page_text = page.locator("body").inner_text().lower()
            current_url = page.url.lower()
            success_keywords = [
                "thank you", "application submitted", "received your application",
                "successfully applied", "application received", "thanks for applying",
                "your application has been submitted", "we've received your application",
                "submission received"
            ]
            is_success = any(kw in page_text for kw in success_keywords) or any(u in current_url for u in ["thank", "confirm", "applied", "success"])

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
                    notes=f"Autonomously submitted on cloud runner using resume AT_26_AI.pdf. Confirmation detected on {page.url}."
                )
                self.tracker.record_job(record)

                # Discord Notification
                notifier.notify_job_applied(
                    title=job.title,
                    company=job.company,
                    platform=job.platform.value,
                    match_score=job.match_score,
                    apply_type="Autonomous Cloud Form Submitter (AT_26_AI.pdf)"
                )
                return True
            else:
                # Check if validation errors blocked submission
                invalid_count = len([i for i in page.locator(':invalid, [aria-invalid="true"]').all() if i.evaluate('e => e.tagName != "FORM"')])
                print(f"[Form Submitter] Form submitted (remaining invalid fields: {invalid_count}), awaiting employer confirmation.")
                return False

        except Exception as e:
            print(f"[Autonomous Form Submitter Error] {e}")
            return False

    def _upload_resume(self, page: Page):
        """Attaches AT_26_AI.pdf to any visible or hidden file input."""
        file_inputs = page.locator("input[type='file']").all()
        for finp in file_inputs:
            try:
                finp.set_input_files(str(self.resume_path.resolve()))
                print(f"[Autonomous Form Submitter] ✓ Attached resume PDF: {self.resume_path.name}")
                page.wait_for_timeout(1500)
                break
            except Exception as e:
                print(f"[Form Submitter] Resume upload note: {e}")

    def _fill_standard_fields(self, page: Page, job: JobPost):
        """Intelligently detects and populates candidate details into inputs."""
        full_name = getattr(self.profile, "full_name", None) or getattr(self.profile, "name", "Avinash Vishnu Talpade")
        name_parts = full_name.split()
        first_name = name_parts[0] if name_parts else "Avinash"
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else "Talpade"
        exp_years = getattr(self.profile, "years_of_experience", None) or getattr(self.profile, "experience_years", 3.5)
        notice_days = getattr(self.profile, "notice_period_days", 15)
        current_comp = getattr(self.profile, "current_company", "Accenture")
        current_title = getattr(self.profile, "current_title", "Cloud Infrastructure Analyst")

        field_mappings = [
            # Name
            (["first_name", "firstname", "first name", "given name", "first"], first_name),
            (["last_name", "lastname", "last name", "family name", "surname", "last"], last_name),
            (["full_name", "fullname", "full name", "applicant_name", "your name", "name"], full_name),
            # Contact
            (["email", "e-mail", "email address"], self.profile.email),
            (["phone", "mobile", "telephone", "phone number", "contact number"], self.profile.phone),
            (["location", "city", "current location", "present location", "address"], "Pune, India"),
            # Links
            (["linkedin", "linkedin profile", "linkedin url", "urls[linkedin]"], self.profile.linkedin_url or "https://www.linkedin.com/in/avinashtalpade"),
            (["github", "github profile", "github url", "urls[github]"], f"https://github.com/{self.profile.github_username or 'talpadeavi03'}"),
            (["portfolio", "website", "personal website", "portfolio url", "urls[portfolio]"], self.profile.portfolio_url or "https://talpadeavi03.github.io/intro"),
            # Company & Experience
            (["current company", "employer", "organization", "org", "company"], current_comp),
            (["current title", "job title", "designation", "role"], current_title),
            (["years of experience", "total experience", "experience"], str(exp_years)),
            (["notice period", "notice", "availability"], f"{notice_days} days"),
            (["current ctc", "present ctc", "current salary"], "Negotiable / As per market"),
            (["expected ctc", "salary expectations", "expected salary"], "Competitive / As per role"),
        ]

        inputs = page.locator("input[type='text'], input[type='email'], input[type='tel'], input[type='number'], input:not([type])").all()
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

    def _fill_comboboxes(self, page: Page):
        """Handles React-Select and Combobox dropdowns (e.g. Country, City)."""
        combos = page.locator("input[role='combobox'], .select__input, input.select__input").all()
        for cb in combos:
            try:
                if not cb.is_visible():
                    continue
                if cb.input_value():
                    continue
                
                label = self._find_label(page, cb).lower()
                cb_id = (cb.get_attribute("id") or "").lower()
                target_text = f"{label} {cb_id}"

                if any(w in target_text for w in ["country", "nationality", "prefix"]):
                    cb.click()
                    cb.press_sequentially("India", delay=80)
                    page.wait_for_timeout(800)
                    cb.press("ArrowDown")
                    cb.press("Enter")
                    page.wait_for_timeout(500)
                elif any(w in target_text for w in ["location", "city", "residence"]):
                    cb.click()
                    cb.press_sequentially("Pune", delay=80)
                    page.wait_for_timeout(1000)
                    cb.press("ArrowDown")
                    cb.press("Enter")
                    page.wait_for_timeout(500)
            except Exception:
                continue

    def _fill_selects(self, page: Page):
        """Intelligently fills <select> elements with candidate-appropriate options."""
        selects = page.locator("select").all()
        for sel in selects:
            try:
                if not sel.is_visible():
                    continue
                current_val = sel.input_value()
                if current_val and current_val not in ["", "select", "none"]:
                    continue

                options = sel.locator("option").all()
                opt_texts = [o.inner_text().strip() for o in options if o.get_attribute("value")]
                if not opt_texts:
                    continue

                label = self._find_label(page, sel).lower()
                sel_id = (sel.get_attribute("id") or "").lower()
                sel_name = (sel.get_attribute("name") or "").lower()
                combined = f"{label} {sel_id} {sel_name}"

                # Match by question topic
                chosen_option = None
                if any(w in combined for w in ["authorized", "legally", "work in"]):
                    chosen_option = next((o for o in opt_texts if "yes" in o.lower()), None)
                elif any(w in combined for w in ["sponsor", "require visa"]):
                    chosen_option = next((o for o in opt_texts if "no" in o.lower()), None)
                elif any(w in combined for w in ["country", "nationality"]):
                    chosen_option = next((o for o in opt_texts if "india" in o.lower()), None)
                elif any(w in combined for w in ["gender"]):
                    chosen_option = next((o for o in opt_texts if "male" in o.lower() or "decline" in o.lower()), None)
                elif any(w in combined for w in ["notice", "availability"]):
                    chosen_option = next((o for o in opt_texts if any(k in o.lower() for k in ["15", "immediate", "1 month"])), None)
                elif any(w in combined for w in ["degree", "education"]):
                    chosen_option = next((o for o in opt_texts if any(k in o.lower() for k in ["master", "bachelor", "computer"])), None)

                # Fallback to first non-empty option
                if not chosen_option:
                    chosen_option = opt_texts[0]

                if chosen_option:
                    sel.select_option(label=chosen_option)
            except Exception:
                continue

    def _fill_radio_buttons(self, page: Page):
        """Handles radio groups (work authorization, sponsorship, terms)."""
        radios = page.locator("input[type='radio']").all()
        processed_names = set()

        for r in radios:
            try:
                if not r.is_visible():
                    continue
                name = r.get_attribute("name")
                if not name or name in processed_names:
                    continue
                processed_names.add(name)

                # Check if any radio in this group is already checked
                group_radios = page.locator(f"input[type='radio'][name='{name}']").all()
                if any(gr.is_checked() for gr in group_radios):
                    continue

                # Inspect label of the group or first radio
                group_text = self._find_label(page, group_radios[0]).lower()
                container_text = group_radios[0].evaluate("e => e.closest('.form-group, .field, fieldset, div')?.innerText || ''").lower()
                combined = f"{group_text} {container_text}"

                # Decide Yes vs No
                if any(w in combined for w in ["sponsorship", "require visa", "criminal", "convicted", "disability"]):
                    # Target No
                    target = next((gr for gr in group_radios if gr.get_attribute("value") and "no" in gr.get_attribute("value").lower()), None)
                else:
                    # Target Yes
                    target = next((gr for gr in group_radios if gr.get_attribute("value") and "yes" in gr.get_attribute("value").lower()), None)

                if not target and group_radios:
                    target = group_radios[0]

                if target:
                    target.check(force=True)
            except Exception:
                continue

    def _fill_checkboxes(self, page: Page):
        """Checks mandatory terms, privacy, and agreement checkboxes."""
        checkboxes = page.locator("input[type='checkbox']").all()
        for cb in checkboxes:
            try:
                if not cb.is_visible():
                    continue
                if cb.is_checked():
                    continue
                
                req = cb.get_attribute("required") is not None or cb.get_attribute("aria-required") == "true"
                label = self._find_label(page, cb).lower()
                is_policy = any(w in label for w in ["agree", "consent", "terms", "privacy", "certify", "accurate", "policy"])

                if req or is_policy:
                    cb.check(force=True)
            except Exception:
                continue

    def _fill_textareas(self, page: Page, job: JobPost):
        """Fills open-ended textareas using RAG Generator."""
        textareas = page.locator("textarea").all()
        for ta in textareas:
            try:
                if not ta.is_visible():
                    continue
                val = ta.input_value()
                if val:
                    continue

                label = self._find_label(page, ta) or "Why are you interested in this role and what makes you a great fit?"
                answer = self.generator.answer_screening_question(label, job.title)
                ta.fill(answer)
                print(f"  [Form Submitter] Answered question: '{label[:45]}...'")
            except Exception:
                continue

    def _solve_remaining_hurdles(self, page: Page, job: JobPost):
        """Fills any remaining required inputs that may block submission."""
        empty_required = page.locator("input:required, textarea:required, select:required").all()
        for el in empty_required:
            try:
                if not el.is_visible():
                    continue
                tag = el.evaluate("e => e.tagName.toLowerCase()")
                val = el.input_value() if tag != "select" else el.input_value()
                if val:
                    continue

                label = self._find_label(page, el) or "Question"
                if tag == "textarea" or tag == "input":
                    answer = self.generator.answer_screening_question(label, job.title)
                    el.fill(answer)
            except Exception:
                continue

    def _find_submit_button(self, page: Page):
        """Locates the form submit button across different ATS and custom designs."""
        candidates = [
            page.locator("button#btn-submit").first,
            page.locator("button[type='submit']").first,
            page.locator("input[type='submit']").first,
            page.locator("button.template-btn-submit").first,
            page.locator("button:has-text('Submit application')").first,
            page.locator("button:has-text('Submit Application')").first,
            page.locator("button:has-text('SUBMIT APPLICATION')").first,
            page.locator("button:has-text('Submit')").first,
            page.locator("button:has-text('Send Application')").first,
        ]
        for c in candidates:
            try:
                if c.is_visible():
                    return c
            except Exception:
                continue
        return None

    def _find_label(self, page: Page, element) -> str:
        """Finds text label for an input element."""
        try:
            elem_id = element.get_attribute("id")
            if elem_id:
                label_el = page.locator(f"label[for='{elem_id}']").first
                if label_el.is_visible():
                    return label_el.inner_text().strip()

            parent_text = element.evaluate(
                "el => el.closest('label')?.innerText || el.closest('.form-group, .field')?.querySelector('label')?.innerText || ''"
            )
            if parent_text:
                return parent_text.strip()
        except Exception:
            pass
        return ""
