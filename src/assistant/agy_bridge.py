import os
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
from src.models import JobPost, CandidateProfile
from src.config import DATA_DIR, settings

DOSSIER_DIR = DATA_DIR / "applications"

class AntigravityCLIBridge:
    """
    Integrates with the Antigravity CLI (agy) to assist the user
    whenever an application redirects to an external job portal
    (e.g. Workday, Greenhouse, Lever, Taleo, Ashby, company career sites).
    """
    def __init__(self, agy_path: Optional[str] = None):
        self.agy_path = agy_path or settings.config_data.get("agy_assistant", {}).get("binary_path") or shutil.which("agy") or str(Path.home() / ".local/bin/agy")

    def is_available(self) -> bool:
        return Path(self.agy_path).exists() and os.access(self.agy_path, os.X_OK)

    def prepare_application_dossier(self, job: JobPost, profile: CandidateProfile, rag_context: str) -> Path:
        """Creates a dedicated folder and dossier file for the redirected application."""
        clean_company = "".join(c for c in job.company if c.isalnum() or c in ("-", "_")).lower() or "company"
        target_dir = DOSSIER_DIR / f"{clean_company}_{job.job_id}"
        target_dir.mkdir(parents=True, exist_ok=True)
        
        dossier_file = target_dir / "application_dossier.md"
        
        content = f"""# External Job Application Dossier
**Target Company:** {job.company}
**Job Title:** {job.title}
**External Application URL:** {job.external_url or job.job_url}
**Original Source Platform:** {job.platform.value}
**Match Score:** {int(job.match_score * 100)}%

---

## Candidate Profile & Contact Information
- **Full Name:** {profile.full_name}
- **Email:** {profile.email}
- **Phone:** {profile.phone}
- **Current Title:** {profile.current_title}
- **Years of Experience:** {profile.years_of_experience}
- **Current Location:** {profile.location}
- **GitHub:** https://github.com/{profile.github_username}
- **LinkedIn:** {profile.linkedin_url}
- **Portfolio:** {profile.portfolio_url}
- **Notice Period:** {profile.notice_period_days} days
- **Work Authorization:** {profile.work_authorization} (Requires Sponsorship: {"Yes" if profile.requires_sponsorship else "No"})
- **Expected CTC / Compensation:** {profile.expected_ctc}

---

## Matched Core Competencies
{", ".join(job.skills_matched) if job.skills_matched else ", ".join(profile.skills[:8])}

---

## Tailored Cover Letter / Pitch
Dear Hiring Team at {job.company},

I am writing to express my strong interest in the {job.title} position. With over {profile.years_of_experience} years of hands-on software engineering experience specializing in {', '.join(profile.skills[:4])}, I have developed and deployed robust, scalable applications.

My active open-source projects on GitHub (https://github.com/{profile.github_username}) demonstrate my commitment to clean architecture, automated testing, and practical engineering. I am confident that my technical skills and proactive problem-solving mindset make me an immediate contributor to your team.

Thank you for your consideration.

Warm regards,  
{profile.full_name}

---

## RAG Knowledge Base Extracts & Context
{rag_context}

---

## Antigravity CLI Instructions
Use `agy` to:
1. Inspect the form elements and required fields on the external career portal.
2. Auto-generate tailored answers for any open-ended questions using the candidate context above.
3. Verify uploaded resume consistency and submit.
"""
        with open(dossier_file, "w", encoding="utf-8") as f:
            f.write(content)

        return dossier_file

    def assist_application(self, job: JobPost, profile: CandidateProfile, rag_context: str, interactive: bool = True) -> bool:
        """
        Launches the Antigravity CLI (agy) to assist with the external application.
        Automatically switches to non-interactive mode in CI environments.
        """
        dossier_path = self.prepare_application_dossier(job, profile, rag_context)
        print(f"\n[Antigravity CLI Assistant] Prepared application dossier: {dossier_path}")
        print(f"[Antigravity CLI Assistant] Redirect URL: {job.external_url}")

        is_ci = os.getenv("CI", "false").lower() == "true" or not sys.stdin.isatty()
        if is_ci:
            interactive = False

        if not self.is_available():
            print(f"[Warning] Antigravity CLI binary not found at '{self.agy_path}'.")
            print(f"You can install it anytime using: curl -fsSL https://antigravity.google/cli/install.sh | bash")
            return False

        prompt = (
            f"Assist the candidate ({profile.full_name}) in completing their job application "
            f"for '{job.title}' at '{job.company}'.\n"
            f"Application Portal URL: {job.external_url}\n"
            f"Candidate Dossier: {dossier_path}\n"
            f"Analyze the external form, help populate candidate details, and answer any required questions."
        )

        try:
            if interactive:
                print(f"[Antigravity CLI] Launching interactive assistant session (`agy -i`)...")
                cmd = [self.agy_path, "-i", prompt]
                subprocess.run(cmd)
            else:
                print(f"[Antigravity CLI] Running non-interactive assistance mode (`agy -p`)...")
                cmd = [self.agy_path, "-p", prompt]
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    print(result.stdout)
                except subprocess.TimeoutExpired:
                    print("[Antigravity CLI] Execution timed out or awaiting auth. Dossier preserved.")
            return True
        except Exception as e:
            print(f"[Error] Failed to execute Antigravity CLI: {e}")
            return False
