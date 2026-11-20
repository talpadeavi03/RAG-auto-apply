import re
from typing import List, Dict, Any
from src.models import CandidateProfile, GitHubRepoInfo, ProfileUpdatePayload, Platform

class RAGGenerator:
    """
    Synthesizes tailored profile updates, recruiter answers,
    and external application dossiers using Candidate RAG context.
    """
    def __init__(self, profile: CandidateProfile, vector_store):
        self.profile = profile
        self.vector_store = vector_store

    def generate_linkedin_profile(self, repos: List[GitHubRepoInfo]) -> ProfileUpdatePayload:
        """Generates an ATS-optimized LinkedIn profile with GitHub project highlights."""
        primary_skills = ", ".join(self.profile.skills[:6])
        top_projects = sorted(repos, key=lambda r: r.stars, reverse=True)[:3]

        # 1. Headline (220 characters max)
        headline = f"{self.profile.current_title} | Specializing in {primary_skills} | Open Source Contributor @ {self.profile.github_username}"
        if len(headline) > 220:
            headline = headline[:217] + "..."

        # 2. About / Summary
        summary_lines = [
            f"👋 Hi, I'm {self.profile.full_name}, a results-driven {self.profile.current_title} with {self.profile.years_of_experience}+ years of experience building scalable systems.",
            "",
            "💻 Core Technical Competencies:",
            f"• Languages & Frameworks: {', '.join(self.profile.skills)}",
            f"• Architecture: Distributed Systems, REST/GraphQL APIs, Microservices, RAG/AI Integrations",
            "",
            "🚀 Featured Open Source & GitHub Projects:"
        ]
        for p in top_projects:
            desc = p.description or "High performance software system"
            summary_lines.append(f"• {p.name} ({p.language}): {desc} [Link: {p.html_url}]")

        summary_lines.extend([
            "",
            "📫 Connect with me:",
            f"• GitHub: https://github.com/{self.profile.github_username}",
            f"• Email: {self.profile.email}"
        ])
        summary = "\n".join(summary_lines)

        return ProfileUpdatePayload(
            platform=Platform.LINKEDIN,
            headline=headline,
            summary=summary,
            key_skills=self.profile.skills[:50]
        )

    def generate_naukri_profile(self, repos: List[GitHubRepoInfo]) -> ProfileUpdatePayload:
        """Generates an ATS-optimized Naukri profile with strict character restrictions."""
        # Naukri Resume Headline: Max 250 characters
        key_skills_short = ", ".join(self.profile.skills[:5])
        headline = (
            f"{self.profile.current_title} with {self.profile.years_of_experience} yrs exp in {key_skills_short}. "
            f"Active open-source developer on GitHub ({self.profile.github_username}). Available in {self.profile.notice_period_days} days."
        )
        if len(headline) > 250:
            headline = headline[:247] + "..."

        # Naukri Profile Summary
        summary_lines = [
            f"{self.profile.current_title} with {self.profile.years_of_experience}+ years of practical experience developing reliable software applications.",
            f"Primary skills include {', '.join(self.profile.skills)}.",
            f"Notice Period: {self.profile.notice_period_days} Days.",
            f"GitHub Portfolio: https://github.com/{self.profile.github_username}"
        ]
        summary = "\n".join(summary_lines)

        # Projects section
        projects_text = ""
        for p in repos[:3]:
            projects_text += f"Project: {p.name}\nTechnologies: {p.language}\nDetails: {p.description}\nGitHub: {p.html_url}\n\n"

        return ProfileUpdatePayload(
            platform=Platform.NAUKRI,
            headline=headline,
            summary=summary,
            key_skills=self.profile.skills[:30],
            projects_text=projects_text
        )

    def answer_screening_question(self, question_text: str, job_title: str = "") -> str:
        """
        Intelligently answers recruiter screening questions (years of experience,
        work auth, notice period, relocation, tools, GitHub repo, etc.).
        """
        q_lower = question_text.lower()

        # Check explicit custom Q&A configured by user
        for custom_q, custom_a in self.profile.custom_qa.items():
            if custom_q.lower() in q_lower:
                return str(custom_a)

        # 1. Experience inquiries
        if any(w in q_lower for w in ["how many years", "years of experience", "experience with"]):
            # Extract specific skill mentioned
            for skill in self.profile.skills:
                if skill.lower() in q_lower:
                    return str(int(self.profile.years_of_experience))
            return str(int(self.profile.years_of_experience))

        # 2. Notice period / Availability
        if any(w in q_lower for w in ["notice period", "how soon", "when can you start", "available to join"]):
            if "day" in q_lower:
                return str(self.profile.notice_period_days)
            elif "month" in q_lower:
                return "0" if self.profile.notice_period_days == 0 else str(max(1, round(self.profile.notice_period_days / 30)))
            return "Immediate" if self.profile.notice_period_days == 0 else f"{self.profile.notice_period_days} days"

        # 3. Work Authorization / Sponsorship
        if any(w in q_lower for w in ["authorized to work", "legally authorized", "visa sponsorship", "sponsorship now or in the future"]):
            if "sponsorship" in q_lower:
                return "No" if not self.profile.requires_sponsorship else "Yes"
            return "Yes"

        # 4. Salary / CTC
        if "expected ctc" in q_lower or "expected salary" in q_lower:
            return self.profile.expected_ctc or "Negotiable / As per market standards"
        if "current ctc" in q_lower or "current salary" in q_lower:
            return self.profile.current_ctc or "Confidential"

        # 5. Relocation / Remote
        if any(w in q_lower for w in ["willing to relocate", "open to relocate", "relocation"]):
            return "Yes"
        if any(w in q_lower for w in ["commute", "work hybrid", "work from office"]):
            return "Yes"

        # 6. Education / Degree
        if any(w in q_lower for w in ["bachelor", "degree", "master", "graduation", "education"]):
            return "Yes"

        # 7. Portfolio / GitHub / Website
        if "github" in q_lower:
            return f"https://github.com/{self.profile.github_username}"
        if "portfolio" in q_lower or "website" in q_lower or "linkedin" in q_lower:
            return self.profile.portfolio_url or self.profile.linkedin_url or f"https://github.com/{self.profile.github_username}"

        # 8. General open-ended question: query vector store
        top_docs = self.vector_store.search(question_text, top_k=2)
        if top_docs:
            snippet = top_docs[0][0].content.split("\n")[0]
            if len(snippet) > 10:
                return f"Yes, I have hands-on experience: {snippet[:150]}"

        return "Yes"
