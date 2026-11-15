import os
import json
import requests
from typing import Optional, List, Dict, Any
from datetime import datetime

class DiscordNotifier:
    """
    Sends rich, real-time alert notifications and status embeds
    to Discord via Discord Webhook.
    """
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")

    def is_enabled(self) -> bool:
        return bool(self.webhook_url and self.webhook_url.startswith("https://discord.com/api/webhooks/"))

    def send_raw(self, payload: Dict[str, Any]) -> bool:
        if not self.is_enabled():
            return False
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code in [200, 204]
        except Exception as e:
            print(f"[Discord Notifier Error] Failed to send webhook: {e}")
            return False

    def notify_profile_updated(self, platform: str, headline: str, summary_snippet: str = ""):
        """Alert when profile is updated / refreshed."""
        embed = {
            "title": f"🔄 {platform.upper()} Profile Refreshed & Synced",
            "description": f"Successfully updated **{platform.capitalize()}** profile with latest RAG & GitHub highlights.",
            "color": 0x3498DB,  # Blue
            "fields": [
                {"name": "Headline", "value": headline[:250], "inline": False},
            ],
            "footer": {"text": "RAG-AG-Apply • Profile Sync"},
            "timestamp": datetime.utcnow().isoformat()
        }
        if summary_snippet:
            embed["fields"].append({"name": "Summary Preview", "value": summary_snippet[:300] + "...", "inline": False})

        self.send_raw({
            "username": "RAG-AG-Apply Bot",
            "embeds": [embed]
        })

    def notify_job_applied(self, title: str, company: str, platform: str, match_score: float, job_url: str, location: str = "India / Remote"):
        """Alert when a job is successfully applied."""
        embed = {
            "title": f"🎉 Successfully Applied to {title}",
            "description": f"Applied via **{platform.capitalize()}** automation.",
            "color": 0x2ECC71,  # Green
            "fields": [
                {"name": "Company", "value": company, "inline": True},
                {"name": "Match Score", "value": f"{int(match_score * 100)}%", "inline": True},
                {"name": "Platform", "value": platform.capitalize(), "inline": True},
                {"name": "Location", "value": location, "inline": True},
                {"name": "Job Link", "value": f"[View Job Posting]({job_url})", "inline": False}
            ],
            "footer": {"text": "RAG-AG-Apply • Automated Application"},
            "timestamp": datetime.utcnow().isoformat()
        }
        self.send_raw({
            "username": "RAG-AG-Apply Bot",
            "embeds": [embed]
        })

    def notify_external_redirect(self, title: str, company: str, platform: str, external_url: str, match_score: float, dossier_path: str):
        """Alert when a job redirects externally and Antigravity CLI assists."""
        embed = {
            "title": f"🔗 External Portal Redirect Assisted",
            "description": f"Job for **{title}** at **{company}** requires external application.\n**Antigravity CLI (agy)** has prepared candidate application dossier and response pack.",
            "color": 0xE67E22,  # Amber / Orange
            "fields": [
                {"name": "Company", "value": company, "inline": True},
                {"name": "Match Score", "value": f"{int(match_score * 100)}%", "inline": True},
                {"name": "Original Source", "value": platform.capitalize(), "inline": True},
                {"name": "External Application Link", "value": f"[Direct Portal URL]({external_url})", "inline": False},
                {"name": "Dossier Path", "value": f"`{dossier_path}`", "inline": False}
            ],
            "footer": {"text": "RAG-AG-Apply • Antigravity CLI Assistant"},
            "timestamp": datetime.utcnow().isoformat()
        }
        self.send_raw({
            "username": "RAG-AG-Apply Bot",
            "embeds": [embed]
        })

    def notify_cycle_summary(self, total_processed: int, applied_count: int, redirect_count: int, platform: str = "Both"):
        """Alert summary at the conclusion of a 4-hour cycle."""
        embed = {
            "title": "📊 4-Hour Job Cycle Completed",
            "description": f"Autonomous pipeline run completed for **{platform}**.",
            "color": 0x9B59B6,  # Purple
            "fields": [
                {"name": "Total Jobs Scanned", "value": str(total_processed), "inline": True},
                {"name": "Directly Applied", "value": str(applied_count), "inline": True},
                {"name": "External Redirects (AG Assisted)", "value": str(redirect_count), "inline": True}
            ],
            "footer": {"text": "RAG-AG-Apply • Scheduled Runner"},
            "timestamp": datetime.utcnow().isoformat()
        }
        self.send_raw({
            "username": "RAG-AG-Apply Bot",
            "embeds": [embed]
        })

notifier = DiscordNotifier()
