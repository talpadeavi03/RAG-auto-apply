import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from src.models import ApplicationRecord, ApplicationStatus
from src.config import DATA_DIR

DB_FILE = DATA_DIR / "tracker.db"

class ApplicationTracker:
    def __init__(self):
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(DB_FILE)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                platform TEXT NOT NULL,
                company TEXT NOT NULL,
                title TEXT NOT NULL,
                job_url TEXT NOT NULL,
                apply_type TEXT NOT NULL,
                external_url TEXT,
                status TEXT NOT NULL,
                match_score REAL DEFAULT 0.0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                applied_at TIMESTAMP
            )
            """)
            conn.commit()

    def is_already_applied(self, job_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM applications WHERE job_id = ? AND status IN ('applied', 'assisted')", (job_id,))
            return cursor.fetchone() is not None

    def record_job(self, record: ApplicationRecord):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO applications (job_id, platform, company, title, job_url, apply_type, external_url, status, match_score, notes, applied_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                status = excluded.status,
                external_url = excluded.external_url,
                notes = excluded.notes,
                applied_at = excluded.applied_at
            """, (
                record.job_id,
                record.platform,
                record.company,
                record.title,
                record.job_url,
                record.apply_type,
                record.external_url,
                record.status.value,
                record.match_score,
                record.notes,
                record.applied_at.isoformat() if record.applied_at else None
            ))
            conn.commit()

    def get_redirected_jobs(self, pending_only: bool = True) -> List[ApplicationRecord]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if pending_only:
                cursor.execute("SELECT id, job_id, platform, company, title, job_url, apply_type, external_url, status, match_score, notes, applied_at FROM applications WHERE status = 'redirected'")
            else:
                cursor.execute("SELECT id, job_id, platform, company, title, job_url, apply_type, external_url, status, match_score, notes, applied_at FROM applications WHERE external_url IS NOT NULL")
            rows = cursor.fetchall()

            results = []
            for r in rows:
                results.append(ApplicationRecord(
                    id=r[0],
                    job_id=r[1],
                    platform=r[2],
                    company=r[3],
                    title=r[4],
                    job_url=r[5],
                    apply_type=r[6],
                    external_url=r[7],
                    status=ApplicationStatus(r[8]),
                    match_score=r[9] or 0.0,
                    notes=r[10],
                    applied_at=datetime.fromisoformat(r[11]) if r[11] else None
                ))
            return results

    def get_summary_stats(self) -> dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, count(*) FROM applications GROUP BY status")
            counts = dict(cursor.fetchall())
            cursor.execute("SELECT count(*) FROM applications")
            total = cursor.fetchone()[0]
            return {"total": total, "breakdown": counts}
