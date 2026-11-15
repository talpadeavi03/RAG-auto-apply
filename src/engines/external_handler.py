from src.models import JobPost, CandidateProfile, ApplicationRecord, ApplicationStatus
from src.tracker.database import ApplicationTracker
from src.assistant.agy_bridge import AntigravityCLIBridge
from src.notifier.discord import notifier

class ExternalRedirectHandler:
    """
    Handles applications that redirect to external career sites
    (Workday, Greenhouse, Lever, Taleo, Ashby, company career portals).
    Prepares candidate context, records to tracker, and invokes the Antigravity CLI.
    """
    def __init__(self, profile: CandidateProfile, vector_store, tracker: ApplicationTracker, agy_bridge: AntigravityCLIBridge):
        self.profile = profile
        self.vector_store = vector_store
        self.tracker = tracker
        self.agy_bridge = agy_bridge

    def handle_redirect(self, job: JobPost, interactive: bool = True) -> bool:
        print(f"\n=======================================================")
        print(f"🔗 [External Redirect Detected] {job.company} - {job.title}")
        print(f"Target URL: {job.external_url or job.job_url}")
        print(f"=======================================================")

        # 1. Fetch relevant RAG context for this job
        top_docs = self.vector_store.search(f"{job.title} {' '.join(job.skills_matched)}", top_k=4)
        rag_context = "\n---\n".join([f"[{d.title}]:\n{d.content}" for d, _ in top_docs])

        # 2. Record to application tracker as redirected
        record = ApplicationRecord(
            job_id=job.job_id,
            platform=job.platform.value,
            company=job.company,
            title=job.title,
            job_url=job.job_url,
            apply_type="external_redirect",
            external_url=job.external_url,
            status=ApplicationStatus.REDIRECTED,
            match_score=job.match_score,
            notes="Redirected to external career portal. Prepared for Antigravity CLI assist."
        )
        self.tracker.record_job(record)

        # 3. Invoke Antigravity CLI (agy) to assist
        success = self.agy_bridge.assist_application(
            job=job,
            profile=self.profile,
            rag_context=rag_context,
            interactive=interactive
        )

        notifier.notify_external_redirect(
            title=job.title,
            company=job.company,
            platform=job.platform.value,
            external_url=job.external_url or job.job_url,
            match_score=job.match_score,
            dossier_path=f"data/applications/{job.company}_{job.job_id}/application_dossier.md"
        )

        if success:
            record.status = ApplicationStatus.ASSISTED
            record.notes = "Assisted with Antigravity CLI."
            self.tracker.record_job(record)

        return success
