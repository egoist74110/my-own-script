"""Private AI journal. All SQLite IO runs on serialized worker threads."""

import asyncio
import contextlib
import fcntl
import json
import os
import signal
import sqlite3
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from toolbox_backend.adapters.config_store import private_dir, stamp
from toolbox_backend.adapters.proc_supervisor import process_identity
from toolbox_backend.adapters.run_store import secure_open
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.logging_setup import redact_exception

TERMINAL = {"ended", "failed"}
SCHEMA = (
    """CREATE TABLE ai_sessions(id TEXT PRIMARY KEY,kind TEXT,cli TEXT,profile_id TEXT,
    repo_id TEXT,cwd_snapshot TEXT,model TEXT,effort TEXT,permission TEXT,purpose TEXT,
    work_item_ref_json TEXT,external_id TEXT,resume_of TEXT,origin_json TEXT,state TEXT,
    ended_reason TEXT,exit_code INTEGER,created_at TEXT,ended_at TEXT,last_seq INTEGER DEFAULT 0,
    usage_json TEXT,request_id TEXT UNIQUE)""",
    """CREATE TABLE ai_events(session_id TEXT REFERENCES ai_sessions(id) ON DELETE CASCADE,
    seq INTEGER,ts TEXT,kind TEXT,payload_json TEXT,PRIMARY KEY(session_id,seq))""",
    """CREATE TABLE ai_approvals(id TEXT PRIMARY KEY,session_id TEXT REFERENCES ai_sessions(id)
    ON DELETE CASCADE,tool_name TEXT,summary TEXT,input_digest TEXT,state TEXT,requested_at TEXT,
    expires_at TEXT,decided_at TEXT,decided_by_json TEXT,scope TEXT)""",
    """CREATE TABLE ai_processes(pid INTEGER,pgid INTEGER,session_id TEXT REFERENCES ai_sessions(id)
    ON DELETE CASCADE,started_at TEXT,proc_start_time TEXT,executable TEXT,
    role TEXT,ended_at TEXT)""",
    "CREATE TABLE ai_meta(key TEXT PRIMARY KEY,value TEXT)",
)


def unavailable():
    return SettingsError("ai_store_unavailable", "AI 数据库不可用；原件保留", 503)


class AIStore:
    def __init__(self, data_dir, on_event=None):
        self.data_dir = Path(data_dir).absolute()
        self.path = self.data_dir / "ai.sqlite3"
        self._db = None
        self._fd = None
        self._lock = threading.RLock()
        self.readonly_error = None
        self.on_event = on_event
        self.checkpoint = lambda _: None

    def require(self):
        if self._db is None or self.readonly_error:
            raise unavailable()
        return self._db

    def _permissions(self):
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.path) + suffix)
            if path.exists():
                path.chmod(0o600)

    def _initialize(self):
        if self._db is not None or self.readonly_error:
            return
        try:
            if self.data_dir.is_symlink():
                raise OSError("symlink")
            private_dir(self.data_dir)
            self._fd = secure_open(self.data_dir / "ai.lock")
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for suffix in ("", "-wal", "-shm"):
                if Path(str(self.path) + suffix).is_symlink():
                    raise OSError("symlink")
            fd = secure_open(self.path)
            os.close(fd)
            self._db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
            db = self._db
            db.row_factory = sqlite3.Row
            if db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise ValueError("version")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=5000")
            if db.execute("PRAGMA user_version").fetchone()[0] == 0:
                with self.transaction() as tx:
                    for statement in SCHEMA:
                        tx.execute(statement)
                    tx.execute("PRAGMA user_version=1")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("corrupt")
            # Persisted identities are only authority when both identity fields still match.
            for record in db.execute("SELECT * FROM ai_processes WHERE ended_at IS NULL"):
                identity = process_identity(record["pgid"])
                if identity and all(
                    identity.get(k) == record[k] for k in ("proc_start_time", "executable")
                ):
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(record["pgid"], signal.SIGKILL)
            with self.transaction() as tx:
                tx.execute("UPDATE ai_processes SET ended_at=? WHERE ended_at IS NULL", (stamp(),))
                ids = [
                    r[0]
                    for r in tx.execute(
                        "SELECT id FROM ai_sessions WHERE state NOT IN ('ended','failed')"
                    )
                ]
                for sid in ids:
                    self._transition(tx, sid, "ended", "backend_restart", None)
                tx.execute(
                    "UPDATE ai_approvals SET state='expired',decided_at=? WHERE state='pending'",
                    (stamp(),),
                )
                cutoff = (datetime.now(UTC) - timedelta(days=14)).isoformat()
                tx.execute("DELETE FROM ai_sessions WHERE ended_at<?", (cutoff,))
            self._permissions()
        except OSError, sqlite3.Error, ValueError, subprocess.SubprocessError:
            self.readonly_error = "AI 数据库损坏、版本不支持或不可写"
            self._close()

    async def initialize(self):
        await self.call(self._initialize)

    @contextlib.contextmanager
    def transaction(self):
        db = self.require()
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            self.checkpoint("before_commit")
            db.commit()
            self._permissions()
        except BaseException:
            db.rollback()
            raise

    def _call(self, fn, args):
        with self._lock:
            try:
                return fn(*args)
            except sqlite3.Error:
                self.readonly_error = "AI 数据库无法可靠写入"
                raise unavailable() from None

    async def call(self, fn, *args):
        task = asyncio.create_task(asyncio.to_thread(self._call, fn, args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def get(self, sid=None, *, request_id=None):
        def read():
            if request_id is not None:
                row = (
                    self.require()
                    .execute("SELECT * FROM ai_sessions WHERE request_id=?", (request_id,))
                    .fetchone()
                )
                return dict(row) if row else None
            row = self.require().execute("SELECT * FROM ai_sessions WHERE id=?", (sid,)).fetchone()
            if row is None:
                raise SettingsError("not_found", "会话不存在", 404)
            return dict(row)

        return await self.call(read)

    async def list(self, state=None, limit=50):
        def read():
            return [
                dict(r)
                for r in self.require().execute(
                    "SELECT * FROM ai_sessions WHERE (? IS NULL OR state=?) "
                    "ORDER BY created_at DESC,id DESC LIMIT ?",
                    (state, state, limit),
                )
            ]

        return await self.call(read)

    def _event(self, db, sid, kind, payload):
        encoded = redact_exception(json.dumps(payload, ensure_ascii=False))
        if len(encoded.encode()) > 64 * 1024:
            encoded = json.dumps({"truncated": True, "summary": encoded[:8000]})
        seq = db.execute("SELECT last_seq FROM ai_sessions WHERE id=?", (sid,)).fetchone()[0] + 1
        event = dict(
            session_id=sid, session_seq=seq, ts=stamp(), kind=kind, payload=json.loads(encoded)
        )
        db.execute(
            "INSERT INTO ai_events VALUES(?,?,?,?,?)", (sid, seq, event["ts"], kind, encoded)
        )
        db.execute("UPDATE ai_sessions SET last_seq=? WHERE id=?", (seq, sid))
        # Bound persisted events without putting raw terminal bytes in this journal.
        rows = db.execute(
            "SELECT seq,length(CAST(payload_json AS BLOB)) FROM ai_events "
            "WHERE session_id=? ORDER BY seq DESC",
            (sid,),
        ).fetchall()
        size, keep = 0, 0
        for row in rows:
            if keep >= 4999 or size + row[1] > 8 * 1024 * 1024 - 1024:
                break
            size += row[1]
            keep += 1
        events = [event]
        if keep < len(rows):
            floor = rows[keep - 1][0] if keep else seq
            db.execute("DELETE FROM ai_events WHERE session_id=? AND seq<?", (sid, floor))
            # Notice is a separate durable sequence, never reuses a previously sent seq.
            seq += 1
            notice = json.dumps({"reason": "events_trimmed"})
            db.execute(
                "INSERT INTO ai_events VALUES(?,?,?,?,?)", (sid, seq, stamp(), "notice", notice)
            )
            db.execute("UPDATE ai_sessions SET last_seq=? WHERE id=?", (seq, sid))
            events.append(
                dict(
                    session_id=sid,
                    session_seq=seq,
                    ts=stamp(),
                    kind="notice",
                    payload={"reason": "events_trimmed"},
                )
            )
        return events

    def _transition(self, db, sid, state, reason, exit_code):
        ended = stamp() if state in TERMINAL else None
        db.execute(
            "UPDATE ai_sessions SET state=?,ended_reason=?,exit_code=?,ended_at=? WHERE id=?",
            (state, reason, exit_code, ended, sid),
        )
        if ended:
            db.execute(
                "UPDATE ai_processes SET ended_at=? WHERE session_id=? AND ended_at IS NULL",
                (ended, sid),
            )
            db.execute(
                "UPDATE ai_approvals SET state='expired',decided_at=? "
                "WHERE session_id=? AND state='pending'",
                (ended, sid),
            )
        return self._event(
            db,
            sid,
            "exit" if ended else "notice",
            dict(state=state, ended_reason=reason, exit_code=exit_code),
        )

    async def create(self, values):
        def save():
            with self.transaction() as db:
                columns = (
                    "id",
                    "kind",
                    "cli",
                    "profile_id",
                    "repo_id",
                    "cwd_snapshot",
                    "model",
                    "effort",
                    "permission",
                    "purpose",
                    "work_item_ref_json",
                    "external_id",
                    "resume_of",
                    "origin_json",
                    "state",
                    "created_at",
                    "usage_json",
                    "request_id",
                )
                db.execute(
                    "INSERT INTO ai_sessions("
                    + ",".join(columns)
                    + ") VALUES("
                    + ",".join("?" for _ in columns)
                    + ")",
                    tuple(values.get(k) for k in columns),
                )
                event = self._event(db, values["id"], "notice", {"state": "starting"})
            return event

        event = await self.call(save)
        if self.on_event:
            for item in event:
                self.on_event(item)

    async def transition(self, sid, state, reason=None, exit_code=None):
        def save():
            with self.transaction() as db:
                return self._transition(db, sid, state, reason, exit_code)

        event = await self.call(save)
        if self.on_event:
            for item in event:
                self.on_event(item)

    async def process(self, sid, identity, role="cli"):
        # Explicit columns prevent schema drift or mismatched placeholders.
        def write():
            with self.transaction() as db:
                db.execute(
                    "INSERT INTO ai_processes(pid,pgid,session_id,started_at,proc_start_time,"
                    "executable,role) VALUES(?,?,?,?,?,?,?)",
                    (
                        identity["pid"],
                        identity["pgid"],
                        sid,
                        stamp(),
                        identity.get("proc_start_time"),
                        identity.get("executable"),
                        role,
                    ),
                )

        await self.call(write)

    async def finish_process(self, pid):
        def save():
            with self.transaction() as db:
                db.execute(
                    "UPDATE ai_processes SET ended_at=? WHERE pid=? AND ended_at IS NULL",
                    (stamp(), pid),
                )

        await self.call(save)

    async def record_cleanup_failure(self, sid):
        def save():
            with self.transaction() as db:
                db.execute(
                    "INSERT OR REPLACE INTO ai_meta VALUES(?,?)", ("kill_failed:" + sid, stamp())
                )

        await self.call(save)

    async def cleanup_failed(self, sid):
        return await self.call(
            lambda: (
                self.require()
                .execute("SELECT 1 FROM ai_meta WHERE key=?", ("kill_failed:" + sid,))
                .fetchone()
                is not None
            )
        )

    async def events(self, sid, after=0, limit=200):
        def read():
            row = (
                self.require()
                .execute("SELECT last_seq FROM ai_sessions WHERE id=?", (sid,))
                .fetchone()
            )
            if not row:
                raise SettingsError("not_found", "会话不存在", 404)
            items = [
                dict(
                    session_id=sid,
                    session_seq=r["seq"],
                    ts=r["ts"],
                    kind=r["kind"],
                    payload=json.loads(r["payload_json"]),
                )
                for r in self.require().execute(
                    "SELECT * FROM ai_events WHERE session_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (sid, after, limit),
                )
            ]
            return dict(items=items, last_seq=row[0])

        return await self.call(read)

    async def delete(self, sid):
        def save():
            with self.transaction() as db:
                row = db.execute("SELECT state FROM ai_sessions WHERE id=?", (sid,)).fetchone()
                if not row:
                    raise SettingsError("not_found", "会话不存在", 404)
                if row[0] not in TERMINAL:
                    raise SettingsError("session_ended", "仅可删除已结束会话", 409)
                db.execute("DELETE FROM ai_sessions WHERE id=?", (sid,))
                db.execute("DELETE FROM ai_meta WHERE key=?", ("kill_failed:" + sid,))

        await self.call(save)

    def _close(self):
        if self._db:
            self._db.close()
            self._db = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    async def close(self):
        await self.call(self._close)
