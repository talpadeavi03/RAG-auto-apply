import os
import json
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from src.models import CandidateProfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

class Settings:
    def __init__(self):
        self.settings_file = CONFIG_DIR / "settings.yaml"
        self.profile_file = CONFIG_DIR / "user_profile.json"
        self.config_data = self._load_settings()
        self.profile = self._load_profile()

    def _load_settings(self) -> Dict[str, Any]:
        default_settings = {
            "general": {
                "headless_browser": False,
                "browser_timeout_ms": 30000,
                "max_applications_per_run": 25,
                "min_match_score": 0.65,
                "user_data_dir": str(DATA_DIR / "browser_sessions"),
            },
            "github": {
                "username": os.getenv("GITHUB_USERNAME", "developer"),
                "token": os.getenv("GITHUB_TOKEN", ""),
                "max_repos": 10,
                "include_forks": False,
            },
            "linkedin": {
                "enabled": True,
                "email": os.getenv("LINKEDIN_EMAIL", ""),
                "password": os.getenv("LINKEDIN_PASSWORD", ""),
                "target_titles": ["Software Engineer", "Full Stack Developer", "Backend Engineer", "AI/ML Engineer"],
                "locations": ["Remote", "India", "United States"],
                "experience_levels": ["Entry level", "Associate", "Mid-Senior level"],
                "auto_easy_apply": True,
            },
            "naukri": {
                "enabled": True,
                "email": os.getenv("NAUKRI_EMAIL", ""),
                "password": os.getenv("NAUKRI_PASSWORD", ""),
                "keywords": ["Python", "Full Stack", "Backend", "AI", "FastAPI", "React"],
                "locations": ["Bangalore", "Hyderabad", "Pune", "Remote"],
                "min_experience_years": 1,
                "max_experience_years": 5,
                "auto_apply": True,
            },
            "agy_assistant": {
                "binary_path": os.getenv("AGY_PATH", str(Path.home() / ".local/bin/agy")),
                "enabled": True,
                "interactive_mode": True,
                "auto_generate_dossier": True,
            }
        }
        if self.settings_file.exists():
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    user_cfg = yaml.safe_load(f) or {}
                    self._deep_update(default_settings, user_cfg)
            except Exception as e:
                print(f"[Warning] Failed to load {self.settings_file}: {e}")
        return default_settings

    def _load_profile(self) -> CandidateProfile:
        if self.profile_file.exists():
            try:
                with open(self.profile_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return CandidateProfile(**data)
            except Exception as e:
                print(f"[Warning] Failed to load {self.profile_file}: {e}")
        return CandidateProfile()

    def save_settings(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.settings_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.config_data, f, default_flow_style=False, sort_keys=False)

    def save_profile(self, profile: CandidateProfile):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.profile = profile
        with open(self.profile_file, "w", encoding="utf-8") as f:
            f.write(profile.model_dump_json(indent=2))

    def _deep_update(self, base: dict, update: dict):
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._deep_update(base[k], v)
            else:
                base[k] = v

settings = Settings()
