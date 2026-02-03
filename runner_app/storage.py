from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from runner_app.config import data_dir
from runner_app.models import Job, JobStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class Storage:
    def __init__(self, db_path: Optional[Path] = None):
        dd = data_dir()
        dd.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or (dd / "my-own-script.sqlite")
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  job_id TEXT PRIMARY KEY,
                  app TEXT NOT NULL,
                  action TEXT NOT NULL,
                  env TEXT,
                  ref TEXT,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  provider TEXT NOT NULL,
                  provider_run_id TEXT NOT NULL,
                  run_url TEXT,
                  log_path TEXT
                )
                """
            )

    def create_job(
        self,
        *,
        job_id: str,
        app: str,
        action: str,
        env: Optional[str],
        ref: Optional[str],
        status: JobStatus,
        provider: str,
        provider_run_id: str,
        run_url: Optional[str],
        log_path: Optional[str],
    ) -> Job:
        now = utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                  job_id, app, action, env, ref, status, created_at, updated_at,
                  provider, provider_run_id, run_url, log_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    app,
                    action,
                    env,
                    ref,
                    status.value,
                    now.isoformat(),
                    now.isoformat(),
                    provider,
                    provider_run_id,
                    run_url,
                    str(log_path) if log_path else None,
                ),
            )
        return self.get_job(job_id)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        run_url: Optional[str] = None,
        log_path: Optional[str] = None,
    ) -> Job:
        now = utcnow().isoformat()
        with self._connect() as conn:
            # only update run_url/log_path if provided
            if run_url is not None and log_path is not None:
                conn.execute(
                    "UPDATE jobs SET status=?, updated_at=?, run_url=?, log_path=? WHERE job_id=?",
                    (status.value, now, run_url, str(log_path), job_id),
                )
            elif run_url is not None:
                conn.execute(
                    "UPDATE jobs SET status=?, updated_at=?, run_url=? WHERE job_id=?",
                    (status.value, now, run_url, job_id),
                )
            elif log_path is not None:
                conn.execute(
                    "UPDATE jobs SET status=?, updated_at=?, log_path=? WHERE job_id=?",
                    (status.value, now, str(log_path), job_id),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status=?, updated_at=? WHERE job_id=?",
                    (status.value, now, job_id),
                )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Job:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown job_id: {job_id}")
        return Job(
            job_id=row["job_id"],
            app=row["app"],
            action=row["action"],
            env=row["env"],
            ref=row["ref"],
            status=JobStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            provider=row["provider"],
            provider_run_id=row["provider_run_id"],
            run_url=row["run_url"],
            log_path=row["log_path"],
        )
