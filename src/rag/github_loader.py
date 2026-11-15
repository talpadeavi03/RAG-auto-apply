import os
import json
import base64
import requests
from pathlib import Path
from typing import List, Optional
from src.models import GitHubRepoInfo, RAGDocument
from src.config import DATA_DIR

CACHE_FILE = DATA_DIR / "github_cache" / "repos.json"

class GitHubLoader:
    def __init__(self, username: str, token: Optional[str] = None):
        self.username = username
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"

    def fetch_repos(self, max_repos: int = 15, include_forks: bool = False) -> List[GitHubRepoInfo]:
        """Fetch repositories from GitHub or cache."""
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://api.github.com/users/{self.username}/repos?sort=updated&per_page=30"
        
        repos_info: List[GitHubRepoInfo] = []
        try:
            resp = requests.get(url, headers=self.headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for item in data:
                    if not include_forks and item.get("fork", False):
                        continue
                    repo = GitHubRepoInfo(
                        name=item.get("name", ""),
                        full_name=item.get("full_name", ""),
                        description=item.get("description") or "",
                        html_url=item.get("html_url", ""),
                        stars=item.get("stargazers_count", 0),
                        language=item.get("language") or "",
                        topics=item.get("topics", [])
                    )
                    readme_content = self.fetch_readme(repo.name)
                    if readme_content:
                        repo.readme_summary = readme_content[:1500]
                    repos_info.append(repo)
                    if len(repos_info) >= max_repos:
                        break

                # Save to cache
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump([r.model_dump() for r in repos_info], f, indent=2)
                return repos_info
            else:
                print(f"[Warning] GitHub API returned status {resp.status_code}. Attempting cache fallback.")
        except Exception as e:
            print(f"[Warning] Failed to fetch GitHub repos online: {e}. Falling back to cache.")

        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                    return [GitHubRepoInfo(**item) for item in cached]
            except Exception as e:
                print(f"[Error] Failed reading cache: {e}")

        return repos_info

    def fetch_readme(self, repo_name: str) -> Optional[str]:
        """Fetch repo README and return clean summary text."""
        url = f"https://api.github.com/repos/{self.username}/{repo_name}/readme"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                raw_data = resp.json()
                content = raw_data.get("content", "")
                decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
                return self._clean_markdown(decoded)
        except Exception:
            pass
        return None

    def _clean_markdown(self, text: str) -> str:
        lines = [line.strip() for line in text.split("\n") if line.strip() and not line.startswith("!")]
        return "\n".join(lines[:60])

    def to_rag_documents(self, repos: List[GitHubRepoInfo]) -> List[RAGDocument]:
        """Convert repos into RAG searchable documents."""
        docs = []
        for r in repos:
            content = f"Project Name: {r.name}\nLanguage: {r.language}\nStars: {r.stars}\n"
            content += f"Description: {r.description}\n"
            if r.topics:
                content += f"Tags / Topics: {', '.join(r.topics)}\n"
            if r.readme_summary:
                content += f"README Highlights:\n{r.readme_summary}\n"
            content += f"URL: {r.html_url}"

            doc = RAGDocument(
                doc_id=f"github_repo_{r.name}",
                source_type="github_repo",
                title=f"GitHub Repo: {r.name} ({r.language})",
                content=content,
                metadata={
                    "name": r.name,
                    "language": r.language,
                    "stars": r.stars,
                    "url": r.html_url
                }
            )
            docs.append(doc)
        return docs
