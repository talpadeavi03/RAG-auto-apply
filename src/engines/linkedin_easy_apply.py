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

                for idx, card in enumerate(cards):
                    if len(jobs) >= limit:
                        break
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
                        raw_slug = ""
                        if "view/" in job_url:
                            raw_slug = job_url.split("view/")[1].split("/")[0].split("?")[0]
                            num_id = raw_slug.split("-")[-1] if "-" in raw_slug else raw_slug
                            job_id = f"li_{num_id}"

                        if self.tracker.has_applied(job_id, job_url):
                            continue

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
                page.wait_for_timeout(2500)

                # Handle remember-me auto-login redirect if encountered
                if "remember-me" in page.url:
                    try:
                        print("  [LinkedIn] Resolving auto-login redirect...")
                        page.wait_for_function("() => !window.location.href.includes('remember-me')", timeout=15000)
                        page.wait_for_timeout(2000)
                        if state_file.exists():
                            context.storage_state(path=str(state_file))
                    except Exception:
                        pass

                # 3. Locate visible Apply Button
                candidates = page.locator("button[aria-label*='Easy Apply'], button:has-text('Easy Apply'), button.jobs-apply-button, button.apply-button, .top-card-layout__cta-container button, .top-card-layout__cta-container a, button:has-text('Apply'), a:has-text('Apply')").all()
                visible_apply = [b for b in candidates if b.is_visible() and ("apply" in b.inner_text().lower() or "apply" in (b.get_attribute("aria-label") or "").lower())]

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
                aria_label = (apply_btn.get_attribute("aria-label") or "").lower()
                href = apply_btn.get_attribute("href") or ""
                
                # Check for External redirect link
                if "easy apply" not in btn_text and "easy apply" not in aria_label and (href.startswith("http") or "external" in btn_text):
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
                print(f"[LinkedIn] Clicking Easy Apply button for {job.title}...")
                popup_url = None
                try:
                    with page.expect_popup(timeout=2500) as popup_info:
                        apply_btn.click(force=True)
                    popup = popup_info.value
                    popup_url = popup.url
                    popup.close()
                except Exception:
                    pass

                # If clicking triggered remember-me auto login redirect
                if "remember-me" in page.url:
                    try:
                        print("  [LinkedIn] Resolving auto-login redirect...")
                        page.wait_for_function("() => !window.location.href.includes('remember-me')", timeout=15000)
                        page.wait_for_timeout(2500)
                        if state_file.exists():
                            context.storage_state(path=str(state_file))
                        # Click the newly revealed authenticated Easy Apply button
                        easy_apply = page.locator("button.jobs-apply-button, button:has-text('Easy Apply')").first
                        if easy_apply.is_visible():
                            easy_apply.click(force=True)
                            page.wait_for_timeout(2500)
                    except Exception:
                        pass

                if popup_url and "linkedin.com" not in popup_url:
                    print(f"[LinkedIn] External career portal opened: {popup_url}")
                    job.external_url = popup_url
                    job.apply_type = ApplyType.EXTERNAL_REDIRECT
                    return self.external_handler.handle_redirect(job, page=page, interactive=False)

                page.wait_for_timeout(3000)

                # Check if multi-step form appeared
                dialog = page.locator("dialog, div[role='dialog'], [aria-modal='true'], .jobs-easy-apply-modal").first
                try:
                    dialog.wait_for(state="visible", timeout=6000)
                except Exception:
                    pass
                container = dialog if dialog.is_visible() else page

                form_active = (
                    container.locator("button:has-text('Next'), button:has-text('Review'), button:has-text('Submit application'), button[aria-label*='Submit application']").count() > 0
                    or len([inp for inp in container.locator("input, select, textarea").all() if inp.is_visible()]) >= 2
                )

                if not form_active:
                    print(f"[LinkedIn] Easy Apply modal did not appear. Preparing application dossier for Antigravity assist...")
                    job.apply_type = ApplyType.EXTERNAL_REDIRECT
                    return self.external_handler.handle_redirect(job, page=page, interactive=False)

                # Iterate through multi-step dialog
                max_steps = 14
                for step in range(max_steps):
                    print(f"  [LinkedIn Easy Apply] Processing application step {step + 1}...")
                    dialog = page.locator("dialog, div[role='dialog'], [aria-modal='true'], .jobs-easy-apply-modal").first
                    container = dialog if dialog.is_visible() else page

                    # Check for Submit button FIRST (Review page / final step)
                    submit_btn = container.locator("button:has-text('Submit application'), button[aria-label*='Submit application']").first
                    if not submit_btn.is_visible():
                        submit_btn = page.locator("button:has-text('Submit application'), button[aria-label*='Submit application']").first

                    if not submit_btn.is_visible():
                        try:
                            container.evaluate("e => e.scrollTo(0, e.scrollHeight)")
                            page.wait_for_timeout(500)
                        except Exception:
                            pass
                        submit_btn = container.locator("button:has-text('Submit application'), button[aria-label*='Submit application']").first

                    if submit_btn.is_visible():
                        print(f"  [LinkedIn] Final Submit button detected! Submitting application for {job.title} at {job.company}...")
                        submit_btn.scroll_into_view_if_needed()
                        submit_btn.click(force=True)
                        page.wait_for_timeout(4000)
                        
                        # Dismiss confirmation modal if present
                        dismiss_btn = page.locator("button:has-text('Done'), button[aria-label*='Dismiss'], button:has-text('Dismiss')").first
                        if dismiss_btn.is_visible():
                            dismiss_btn.click(force=True)
                            page.wait_for_timeout(1000)

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
                            notes="Applied via automated Easy Apply with RAG answers and resume AT_26_AI.pdf."
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

                    # Check if Save button is visible (work experience / education open in edit state)
                    save_btn = container.locator("button:has-text('Save')").first
                    if save_btn.is_visible():
                        print("  [LinkedIn] Detected open section with Save button. Selecting options and saving...")
                        for sel in container.locator("select").all():
                            try:
                                if sel.is_visible():
                                    for opt in sel.locator("option:not([disabled])").all():
                                        val = opt.get_attribute("value")
                                        if val and val.lower() not in ["", "none", "select"]:
                                            sel.select_option(value=val)
                                            break
                            except Exception:
                                pass
                        page.wait_for_timeout(500)
                        save_btn.click(force=True)
                        page.wait_for_timeout(1500)

                    # Answer inputs on current step
                    self._answer_form_inputs(container, job.title)
                    page.wait_for_timeout(1000)

                    # Check for Next / Review button
                    next_btn = container.locator("button:has-text('Review'), button[aria-label*='Review'], button:has-text('Next'), button[aria-label*='Continue to next step']").first
                    if not next_btn.is_visible():
                        next_btn = page.locator("button:has-text('Review'), button[aria-label*='Review'], button:has-text('Next'), button[aria-label*='Continue to next step']").first

                    if next_btn.is_visible():
                        btn_label = next_btn.inner_text().strip()
                        print(f"  [LinkedIn] Advancing with '{btn_label}' button...")
                        next_btn.scroll_into_view_if_needed()
                        next_btn.click(force=True)
                        page.wait_for_timeout(2500)
                    else:
                        submit_check = page.locator("button:has-text('Submit application'), button[aria-label*='Submit application']").first
                        if submit_check.is_visible():
                            continue
                        break

                print(f"[LinkedIn] Finished form steps for {job.title} without final submit.")
                return False
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

    def _answer_form_inputs(self, container, job_title: str):
        """Fills text inputs, selects, radios, and attaches resume using RAG generator."""
        resume_pdf = DATA_DIR / "resumes" / "AT_26_AI.pdf"
        if not resume_pdf.exists():
            resume_pdf = Path("data/resumes/AT_26_AI.pdf")

        # 1. Attach AT_26_AI.pdf if file input present
        try:
            file_inps = container.locator("input[type='file']").all()
            for finp in file_inps:
                if resume_pdf.exists():
                    finp.set_input_files(str(resume_pdf.resolve()))
                    print(f"  [LinkedIn] Attached {resume_pdf.name}")
                    break
        except Exception:
            pass

        # 2. Select first resume radio card if visible and not selected
        try:
            resume_radios = container.locator("input[type='radio']").all()
            for rr in resume_radios:
                r_id = (rr.get_attribute("id") or "").lower()
                r_val = (rr.get_attribute("value") or "").lower()
                if rr.is_visible() and ("resume" in r_id or "cv" in r_id or "at_26" in r_id or "resume" in r_val):
                    if not rr.is_checked():
                        rr.check(force=True)
                    break
        except Exception:
            pass

        # 3. Fill text & number inputs
        inputs = container.locator("input[type='text'], input[type='number'], input[type='tel'], input:not([type]), textarea").all()
        for inp in inputs:
            try:
                if not inp.is_visible():
                    continue
                val = inp.input_value()
                if val and val.strip():
                    continue

                # Skip optional typeahead inputs that break auto-advance
                is_typeahead = inp.get_attribute("data-testid") == "typeahead-input" or "typeahead" in (inp.get_attribute("class") or "").lower()
                is_required = inp.get_attribute("required") is not None or inp.get_attribute("aria-required") == "true"
                if is_typeahead and not is_required:
                    continue

                # Fetch preceding sibling question text and attributes
                preceding_q = inp.evaluate("""e => {
                    let node = e;
                    while (node && node.tagName !== "FORM" && node.tagName !== "DIALOG") {
                        let prev = node.previousElementSibling;
                        while (prev) {
                            if (prev.innerText && prev.innerText.trim()) return prev.innerText.trim();
                            prev = prev.previousElementSibling;
                        }
                        node = node.parentElement;
                    }
                    return "";
                }""").lower()
                input_id = inp.get_attribute("id") or ""
                input_name = (inp.get_attribute("name") or "").lower()
                aria_label = (inp.get_attribute("aria-label") or "").lower()
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                
                # Fetch surrounding label / question text from DOM
                lbl_text = inp.evaluate("e => e.closest('div.k4dlcw, fieldset, div.k4dl5v, form')?.innerText || ''").lower()

                combined = f"{preceding_q} {aria_label} {placeholder} {input_name} {lbl_text}".lower()

                if any(w in combined for w in ["phone", "mobile", "tel", "contact"]):
                    inp.fill("+91 8999285015")
                elif any(w in combined for w in ["email"]):
                    inp.fill("talpadeavi0303@gmail.com")
                elif any(w in combined for w in ["current ctc", "fixed"]):
                    inp.fill("450000")
                elif any(w in combined for w in ["expected ctc"]):
                    inp.fill("750000")
                elif any(w in combined for w in ["financial", "gross", "salary", "compensation", "ctc", "expectation"]):
                    inp.fill("450000")
                elif any(w in combined for w in ["location", "city", "country"]):
                    inp.fill("India, Pune")
                elif any(w in combined for w in ["notice", "serving", "days"]):
                    inp.fill("0")
                elif any(w in combined for w in ["experience", "years", "total"]):
                    inp.fill("3")
                elif inp.get_attribute("type") == "number":
                    inp.fill("3")
                else:
                    question = aria_label or lbl_text.split("\n")[0] or placeholder or "Question"
                    answer = self.generator.answer_screening_question(question, job_title)
                    inp.fill(answer[:150])
            except Exception:
                continue

        # 4. Fill dropdown selects
        selects = container.locator("select").all()
        for sel in selects:
            try:
                if not sel.is_visible():
                    continue
                cur_val = sel.input_value()
                if cur_val and cur_val.lower() not in ["", "none", "select", "select an option"]:
                    continue

                sel_label = sel.evaluate("e => e.closest('div.k4dlcw, fieldset, div.k4dl5v, form')?.innerText || ''").lower()

                enabled_opts = sel.locator("option:not([disabled])").all()
                chosen_val = None
                first_valid_val = None
                for o in enabled_opts:
                    val = o.get_attribute("value")
                    txt = o.inner_text().strip().lower()
                    if not val or txt in ["select", "choose", "none", "select an option"]:
                        continue
                    if not first_valid_val:
                        first_valid_val = val

                    if any(w in sel_label for w in ["notice", "availability"]):
                        if any(k in txt for k in ["immediate", "0", "0-15", "15"]):
                            chosen_val = val
                            break
                    elif any(w in sel_label for w in ["learn about", "source", "where"]):
                        if "linkedin" in txt:
                            chosen_val = val
                            break
                    elif any(w in sel_label for w in ["terraform", "iac", "cloud", "aws", "azure"]):
                        if any(k in txt for k in ["3–5", "1–3", "3", "5", "yes"]):
                            chosen_val = val
                            break
                    elif any(w in sel_label for w in ["python", "rate", "scripting"]):
                        if any(k in txt for k in ["4", "advanced", "expert", "3"]):
                            chosen_val = val
                            break
                    elif any(w in sel_label for w in ["sponsorship", "require visa"]):
                        if "no" in txt:
                            chosen_val = val
                            break
                    elif any(w in sel_label for w in ["authorized", "legally", "eligible"]):
                        if "yes" in txt:
                            chosen_val = val
                            break
                    elif any(k in txt for k in ["yes", "authorized", "india", "pune", "immediate", "15 days", "3", "4", "2022", "january", "may"]):
                        chosen_val = val
                        break

                if not chosen_val:
                    chosen_val = first_valid_val

                if chosen_val:
                    sel.select_option(value=chosen_val)
            except Exception:
                continue

        # 5. Radio groups
        radios = container.locator("input[type='radio']").all()
        processed_names = set()
        for r in radios:
            try:
                name = r.get_attribute("name")
                if not name or name in processed_names:
                    continue
                processed_names.add(name)

                group_radios = container.locator(f"input[type='radio'][name='{name}']").all()
                if any(gr.is_checked() for gr in group_radios):
                    continue

                # Question is either in r aria-label, legend, or preceding heading
                q_text = (r.get_attribute("aria-label") or "").lower()
                if not q_text:
                    q_text = r.evaluate("""e => {
                        let node = e;
                        while (node && node.tagName !== "FORM" && node.tagName !== "DIALOG") {
                            let legend = node.querySelector("legend")?.innerText || "";
                            if (legend) return legend;
                            let prev = node.previousElementSibling;
                            while (prev) {
                                if (prev.innerText && prev.innerText.trim()) return prev.innerText.trim();
                                prev = prev.previousElementSibling;
                            }
                            node = node.parentElement;
                        }
                        return "";
                    }""").lower()

                is_negative = any(w in q_text for w in ["sponsorship", "require visa", "criminal", "convicted"])
                target = None
                for gr in group_radios:
                    opt_text = gr.evaluate("e => e.parentElement?.parentElement?.innerText || e.closest('label')?.innerText || ''").strip().lower()
                    gr_val = (gr.get_attribute("value") or "").lower()
                    combined_gr = f"{opt_text} {gr_val}"
                    if is_negative and "no" in combined_gr:
                        target = gr
                        break
                    elif not is_negative and "yes" in combined_gr:
                        target = gr
                        break

                if not target and group_radios:
                    target = group_radios[0]

                if target:
                    target.scroll_into_view_if_needed()
                    target.evaluate("e => { if (!e.checked) e.click(); }")
            except Exception:
                continue

        # 6. Checkboxes (terms / consent / skills)
        checkboxes = container.locator("input[type='checkbox']").all()
        for cb in checkboxes:
            try:
                cb.scroll_into_view_if_needed()
                cb_label = cb.evaluate("""e => {
                    const l = e.closest("label") || document.querySelector(`label[for="${e.id}"]`) || e.closest("div")?.querySelector("p, label, span");
                    return l ? l.innerText.trim() : "";
                }""").lower()

                if "none of the above" in cb_label:
                    if cb.is_checked():
                        cb.evaluate("e => { if (e.checked) e.click(); }")
                else:
                    if not cb.is_checked():
                        cb.evaluate("e => { if (!e.checked) e.click(); }")
            except Exception:
                continue
