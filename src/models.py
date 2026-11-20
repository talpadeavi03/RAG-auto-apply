from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class Platform(str, Enum):
    LINKEDIN = "linkedin"
    NAUKRI = "naukri"
    EXTERNAL = "external"

class ApplyType(str, Enum):
    EASY_APPLY = "easy_apply"
    DIRECT = "direct"
    EXTERNAL_REDIRECT = "external_redirect"

class ApplicationStatus(str, Enum):
    FOUND = "found"
    FILTERED_OUT = "filtered_out"
    APPLIED = "applied"
    FAILED = "failed"
    REDIRECTED = "redirected"
    ASSISTED = "assisted"

class CandidateProfile(BaseModel):
    full_name: str = "Candidate"
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    github_username: str = ""
    portfolio_url: str = ""
    years_of_experience: float = 3.0
    notice_period_days: int = 0
    current_ctc: str = "450000"
    expected_ctc: str = "750000"
    current_company: str = ""
    current_title: str = "Software Engineer"
    skills: List[str] = Field(default_factory=list)
    target_titles: List[str] = Field(default_factory=list)
    target_locations: List[str] = Field(default_factory=list)
    work_authorization: str = "Citizen / Authorized to work"
    requires_sponsorship: bool = False
    custom_qa: Dict[str, str] = Field(default_factory=dict)

class GitHubRepoInfo(BaseModel):
    name: str
    full_name: str
    description: Optional[str] = ""
    html_url: str
    stars: int = 0
    language: Optional[str] = ""
    topics: List[str] = Field(default_factory=list)
    readme_summary: Optional[str] = ""
    key_technologies: List[str] = Field(default_factory=list)

class RAGDocument(BaseModel):
    doc_id: str
    source_type: str  # "resume", "github_repo", "profile", "project"
    title: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class JobPost(BaseModel):
    platform: Platform
    job_id: str
    title: str
    company: str
    location: str
    job_url: str
    description: str = ""
    apply_type: ApplyType = ApplyType.DIRECT
    external_url: Optional[str] = None
    match_score: float = 0.0
    skills_matched: List[str] = Field(default_factory=list)
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

class ApplicationRecord(BaseModel):
    id: Optional[int] = None
    job_id: str
    platform: str
    company: str
    title: str
    job_url: str
    apply_type: str
    external_url: Optional[str] = None
    status: ApplicationStatus = ApplicationStatus.FOUND
    applied_at: Optional[datetime] = None
    match_score: float = 0.0
    notes: Optional[str] = None

class ProfileUpdatePayload(BaseModel):
    platform: Platform
    headline: str
    summary: str
    key_skills: List[str]
    projects_text: Optional[str] = None
