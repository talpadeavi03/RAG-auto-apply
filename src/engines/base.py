from abc import ABC, abstractmethod
from typing import List
from src.models import JobPost, CandidateProfile
from src.tracker.database import ApplicationTracker

class BaseJobEngine(ABC):
    def __init__(self, profile: CandidateProfile, vector_store, generator, tracker: ApplicationTracker):
        self.profile = profile
        self.vector_store = vector_store
        self.generator = generator
        self.tracker = tracker

    @abstractmethod
    def search_jobs(self, keywords: List[str], locations: List[str], limit: int = 15) -> List[JobPost]:
        """Search jobs matching target keywords and locations."""
        pass

    @abstractmethod
    def apply_to_job(self, job: JobPost) -> bool:
        """Apply to the specific job post."""
        pass
