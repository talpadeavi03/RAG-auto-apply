import os
import time
import requests
from typing import List, Dict, Any, Optional
from src.engines.base import BaseJobEngine
from src.models import JobPost, Platform, ApplyType, ApplicationRecord, ApplicationStatus
from src.engines.form_submitter import AutonomousFormSubmitter
from src.notifier.discord import notifier

class ATSEngine(BaseJobEngine):
    """
    Autonomous Job Engine for Public ATS Portals (Greenhouse, Lever, Ashby).
    Operates 100% in cloud runners with zero CAPTCHAs, zero account logins,
    and submits real applications directly using RAG-powered form completion.
    """
    def __init__(self, profile, vector_store, generator, tracker, form_submitter: AutonomousFormSubmitter):
        super().__init__(profile, vector_store, generator, tracker)
        self.form_submitter = form_submitter

        # Curated list of tech companies with open ATS boards hiring Cloud / Infrastructure
        self.greenhouse_boards = [
            ("Canonical", "canonical"),
            ("InMobi", "inmobi"),
            ("Razorpay", "razorpay"),
            ("Swiggy", "swiggy"),
            ("Airmeet", "airmeet"),
            ("CleverTap", "clevertap"),
            ("Atlan", "atlan"),
            ("Juspay", "juspay"),
            ("Dream11", "dream11"),
            ("Urban Company", "urbancompany"),
            ("Postman", "postman"),
            ("Elastic", "elastic"),
            ("Datadog", "datadog"),
            ("HashiCorp", "hashicorp"),
            ("GitLab", "gitlab")
        ]

        self.lever_boards = [
            ("Cred", "cred"),
            ("BrowserStack", "browserstack"),
            ("Affirm", "affirm"),
            ("Zepto", "zepto"),
            ("Yellow.ai", "yellowai"),
            ("Darwinbox", "darwinbox")
        ]

    def search_jobs(self, keywords: List[str], locations: List[str], limit: int = 15) -> List[JobPost]:
        """Queries public ATS boards for matching Cloud & Infrastructure postings."""
        print(f"[ATS Engine] Scanning public Greenhouse, Lever & Ashby boards for Cloud roles...")
        matched_jobs: List[JobPost] = []
        target_kws = [kw.lower() for kw in keywords] if keywords else ["cloud", "devops", "infrastructure", "platform", "sre"]

        # 1. Scan Greenhouse boards
        for comp_name, board in self.greenhouse_boards:
            if len(matched_jobs) >= limit:
                break
            try:
                r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", timeout=4)
                if r.status_code == 200:
                    data = r.json().get("jobs", [])
                    for j in data:
                        title = j.get("title", "")
                        title_lower = title.lower()
                        loc_name = j.get("location", {}).get("name", "Remote / India")
                        
                        # Check keyword match
                        if any(kw in title_lower for kw in target_kws):
                            job_url = j.get("absolute_url")
                            if not job_url:
                                continue

                            score, skills, _ = self.vector_store.match_job(title, f"{title} at {comp_name}", self.profile.skills)
                            job_id = f"gh_{board}_{j.get('id')}"

                            job_post = JobPost(
                                platform=Platform.EXTERNAL,
                                job_id=job_id,
                                title=title,
                                company=comp_name,
                                location=loc_name,
                                job_url=job_url,
                                description=f"{title} position at {comp_name} ({loc_name})",
                                apply_type=ApplyType.DIRECT,
                                match_score=score,
                                skills_matched=skills
                            )
                            matched_jobs.append(job_post)
                            print(f"  [ATS Match: Greenhouse] {title} @ {comp_name} ({loc_name}) - Score: {int(score*100)}%")
                            if len(matched_jobs) >= limit:
                                break
            except Exception:
                continue

        # 2. Scan Lever boards
        for comp_name, slug in self.lever_boards:
            if len(matched_jobs) >= limit:
                break
            try:
                r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=4)
                if r.status_code == 200:
                    data = r.json()
                    for j in data:
                        title = j.get("text", "")
                        title_lower = title.lower()
                        loc_name = j.get("categories", {}).get("location", "Remote / India")

                        if any(kw in title_lower for kw in target_kws):
                            apply_url = j.get("applyUrl") or j.get("hostedUrl")
                            if not apply_url:
                                continue

                            score, skills, _ = self.vector_store.match_job(title, f"{title} at {comp_name}", self.profile.skills)
                            job_id = f"lever_{slug}_{j.get('id')}"

                            job_post = JobPost(
                                platform=Platform.EXTERNAL,
                                job_id=job_id,
                                title=title,
                                company=comp_name,
                                location=loc_name,
                                job_url=apply_url,
                                description=f"{title} position at {comp_name}",
                                apply_type=ApplyType.DIRECT,
                                match_score=score,
                                skills_matched=skills
                            )
                            matched_jobs.append(job_post)
                            print(f"  [ATS Match: Lever] {title} @ {comp_name} ({loc_name}) - Score: {int(score*100)}%")
                            if len(matched_jobs) >= limit:
                                break
            except Exception:
                continue

        print(f"[ATS Engine] Total candidate roles matched: {len(matched_jobs)}")
        return matched_jobs

    def apply_to_job(self, job: JobPost) -> bool:
        """Autonomously fills and submits application to public ATS portal."""
        if self.tracker.is_already_applied(job.job_id):
            print(f"[ATS Engine] Job '{job.title}' at {job.company} already applied. Skipping.")
            return False

        print(f"\n=======================================================")
        print(f"🚀 [ATS Autonomous Apply] {job.company} - {job.title}")
        print(f"Target URL: {job.job_url}")
        print(f"=======================================================")

        success = self.form_submitter.submit_application(job, job.job_url)
        return success
