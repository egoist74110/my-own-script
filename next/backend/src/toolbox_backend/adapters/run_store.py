"""Private WAL journal. Every mutation and its durable event share one transaction."""

import asyncio
import contextlib
import fcntl
import json
import os
import re
import sqlite3
import stat
import threading
import uuid
from pathlib import Path

from toolbox_backend.adapters.config_store import private_dir, stamp
from toolbox_backend.adapters.run_log import safe_text
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.logging_setup import contains_secret, redact_exception

ACTIVE = ("queued", "running", "cancelling", "unknown")
TERMINAL = ("succeeded", "failed", "cancelled")
TRANSITIONS = {
    "queued": {"running", "cancelled", "failed"},
    "running": {"cancelling", "succeeded", "failed", "unknown"},
    "cancelling": {"cancelled", "failed", "unknown", "succeeded"},
    "unknown": {"unknown", *TERMINAL},
}
SCHEMA = (
    """CREATE TABLE runs (
    run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, operation TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN
      ('queued','running','cancelling','cancelled','succeeded','failed','unknown')),
    phase TEXT NOT NULL DEFAULT 'queued', reason_code TEXT, created_at TEXT NOT NULL,
    started_at TEXT, updated_at TEXT NOT NULL, finished_at TEXT, config_revision INTEGER NOT NULL,
    task_snapshot_json TEXT NOT NULL, request_id TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
    cancel_requested_at TEXT, stop_reason TEXT, deadline_at TEXT NOT NULL,
    last_seq INTEGER NOT NULL DEFAULT 0, log_bytes INTEGER NOT NULL DEFAULT 0,
    state_version INTEGER NOT NULL DEFAULT 0, recovery_state TEXT NOT NULL DEFAULT 'none',
    summary TEXT NOT NULL DEFAULT '')""",
    """CREATE UNIQUE INDEX active_task ON runs(task_id)
       WHERE status IN ('queued','running','cancelling','unknown')""",
    """CREATE TABLE run_steps (run_id TEXT REFERENCES runs(run_id), step_no INTEGER,
       kind TEXT NOT NULL, target_index INTEGER, status TEXT NOT NULL DEFAULT 'pending',
       started_at TEXT, finished_at TEXT, checkpoint_json TEXT NOT NULL DEFAULT '{}',
       PRIMARY KEY(run_id, step_no))""",
    """CREATE TABLE run_effects (effect_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
       step_no INTEGER NOT NULL, kind TEXT NOT NULL, intent_key TEXT NOT NULL UNIQUE,
       intent_json TEXT NOT NULL, state TEXT NOT NULL, remote_id TEXT,
       owned INTEGER NOT NULL DEFAULT 0, intent_at TEXT NOT NULL, confirmed_at TEXT,
       error_category TEXT, FOREIGN KEY(run_id,step_no) REFERENCES run_steps(run_id,step_no))""",
    """CREATE TABLE run_events (run_id TEXT REFERENCES runs(run_id), seq INTEGER,
       ts TEXT NOT NULL, type TEXT NOT NULL, level TEXT NOT NULL, data_json TEXT NOT NULL,
       PRIMARY KEY(run_id,seq))""",
    """CREATE TABLE run_reservations (resource_key TEXT PRIMARY KEY,
       run_id TEXT NOT NULL REFERENCES runs(run_id))""",
)


def unavailable():
    return SettingsError("run_store_unavailable", "运行库不可用；保留原件供检查", 503)


def secure_open(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        raise
    return fd


class RunStore:
    def __init__(self, data_dir: Path, on_event=None):
        self.data_dir = data_dir.absolute()
        self.path = self.data_dir / "runs.sqlite3"
        self.on_event = on_event
        self.readonly_error = None
        self.checkpoint = lambda _: None
        self._db = None
        self._fd = None
        self._lock = threading.RLock()

    def _initialize(self):
        with self._lock:
            if self._db is not None or self.readonly_error:
                return
            try:
                if self.data_dir.is_symlink():
                    raise OSError("symlink")
                private_dir(self.data_dir)
                self._fd = secure_open(self.data_dir / "runner.lock")
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                for suffix in ("", "-wal", "-shm"):
                    path = Path(str(self.path) + suffix)
                    if path.is_symlink():
                        raise OSError("symlink")
                fd = secure_open(self.path)
                os.close(fd)
                self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
                self._db.row_factory = sqlite3.Row
                db = self._db
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    db.close()
                    self._db = sqlite3.connect(
                        self.path.as_uri() + "?mode=ro",
                        uri=True,
                        check_same_thread=False,
                        isolation_level=None,
                    )
                    self._db.row_factory = sqlite3.Row
                    self._db.execute("PRAGMA query_only=ON")
                    self.readonly_error = "运行库版本不支持；仅展示兼容历史"
                    return
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA synchronous=FULL")
                db.execute("PRAGMA busy_timeout=5000")
                if version == 0:
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        for statement in SCHEMA:
                            db.execute(statement)
                        db.execute("PRAGMA user_version=1")
                        db.commit()
                    except BaseException:
                        db.rollback()
                        raise
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("corrupt")
                for suffix in ("", "-wal", "-shm"):
                    path = Path(str(self.path) + suffix)
                    if path.exists():
                        path.chmod(0o600)
            except OSError, sqlite3.Error, ValueError:
                self.readonly_error = "运行库损坏、版本不支持或已由其他后端持有"
                if self._db is not None:
                    self._db.close()
                    self._db = None
                if self._fd is not None:
                    os.close(self._fd)
                    self._fd = None

    async def initialize(self):
        self._loop = asyncio.get_running_loop()
        await asyncio.to_thread(self._initialize)

    def _require(self, *, writable=False):
        if self._db is None or writable and self.readonly_error:
            raise unavailable()
        return self._db

    async def call(self, fn, *args, **kwargs):
        task = asyncio.create_task(asyncio.to_thread(self._call, fn, args, kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    def _call(self, fn, args, kwargs):
        with self._lock:
            try:
                return fn(*args, **kwargs)
            except sqlite3.Error as exc:
                code = getattr(exc, "sqlite_errorcode", 0) & 255
                if code in {
                    sqlite3.SQLITE_CORRUPT,
                    sqlite3.SQLITE_NOTADB,
                    sqlite3.SQLITE_IOERR,
                    sqlite3.SQLITE_FULL,
                    sqlite3.SQLITE_READONLY,
                }:
                    self.readonly_error = "运行库无法可靠写入；已禁止后续写操作"
                raise unavailable() from None

    @contextlib.contextmanager
    def transaction(self):
        db = self._require(writable=True)
        events = []
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db, events
            self.checkpoint("before_commit")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        for event in events:
            if self.on_event:
                self._loop.call_soon_threadsafe(self.on_event, event)

    def _event(self, db, events, rid, kind, payload, level="info"):
        db.execute("UPDATE runs SET last_seq=last_seq+1 WHERE run_id=?", (rid,))
        seq = db.execute("SELECT last_seq FROM runs WHERE run_id=?", (rid,)).fetchone()[0]
        now = stamp()
        encoded = redact_exception(json.dumps(payload, ensure_ascii=False))
        db.execute(
            "INSERT INTO run_events VALUES (?,?,?,?,?,?)", (rid, seq, now, kind, level, encoded)
        )
        events.append(dict(run_id=rid, run_seq=seq, type=kind, payload=json.loads(encoded)))

    def _get(self, rid):
        row = self._require().execute("SELECT * FROM runs WHERE run_id=?", (rid,)).fetchone()
        if row is None:
            raise SettingsError("not_found", "运行不存在", 404)
        result = dict(row)
        result["store_error"] = self.readonly_error
        result["task_snapshot"] = json.loads(result.pop("task_snapshot_json"))
        result["steps"] = []
        for step in (
            self._require()
            .execute("SELECT * FROM run_steps WHERE run_id=? ORDER BY step_no", (rid,))
            .fetchall()
        ):
            item = dict(step)
            item["checkpoint"] = json.loads(item.pop("checkpoint_json"))
            result["steps"].append(item)
        result["effects"] = []
        for effect in (
            self._require()
            .execute(
                "SELECT * FROM run_effects WHERE run_id=? ORDER BY intent_at,effect_id", (rid,)
            )
            .fetchall()
        ):
            item = dict(effect)
            item["intent"] = json.loads(item.pop("intent_json"))
            item["owned"] = bool(item["owned"])
            result["effects"].append(item)
        return result

    async def get(self, rid):
        return await self.call(self._get, rid)

    def _create(
        self,
        *,
        task_id,
        operation,
        request_id,
        request_hash,
        config_revision,
        snapshot,
        resources,
        deadline_at,
        steps=(),
    ):
        if contains_secret(json.dumps(snapshot, ensure_ascii=False)):
            raise SettingsError("validation_error", "运行快照包含凭据值", 422)
        with self.transaction() as (db, events):
            prior = db.execute(
                "SELECT run_id,request_hash FROM runs WHERE request_id=?", (request_id,)
            ).fetchone()
            if prior:
                if prior["request_hash"] != request_hash:
                    raise SettingsError("idempotency_conflict", "请求标识已用于不同请求")
                return self._get(prior["run_id"])
            if db.execute(
                "SELECT 1 FROM runs WHERE task_id=? AND status IN (?,?,?,?)", (task_id, *ACTIVE)
            ).fetchone():
                raise SettingsError("task_active", "任务存在活动运行")
            if db.execute("SELECT count(*) FROM runs WHERE status='queued'").fetchone()[0] >= 100:
                raise SettingsError("busy", "运行队列已满", 503)
            for key in set(resources):
                if db.execute(
                    "SELECT 1 FROM run_reservations WHERE resource_key=?", (key,)
                ).fetchone():
                    raise SettingsError("resource_active", "运行资源已被预约")
            rid, now = str(uuid.uuid4()), stamp()
            db.execute(
                """INSERT INTO runs
                (run_id,task_id,operation,status,created_at,updated_at,config_revision,
                 task_snapshot_json,request_id,request_hash,deadline_at)
                VALUES (?,?,?,'queued',?,?,?,?,?,?,?)""",
                (
                    rid,
                    task_id,
                    operation,
                    now,
                    now,
                    config_revision,
                    json.dumps(snapshot),
                    request_id,
                    request_hash,
                    deadline_at,
                ),
            )
            db.executemany(
                "INSERT INTO run_reservations VALUES (?,?)", [(key, rid) for key in set(resources)]
            )
            db.executemany(
                "INSERT INTO run_steps(run_id,step_no,kind,target_index) VALUES(?,?,?,?)",
                [(rid, i, step["kind"], step.get("target_index")) for i, step in enumerate(steps)],
            )
            self._event(db, events, rid, "state", {"status": "queued"})
        return self._get(rid)

    async def create(self, **kwargs):
        return await self.call(self._create, **kwargs)

    def _transition(self, rid, version, status, reason_code=None, summary="", recovery_state=None):
        with self.transaction() as (db, events):
            old = self._get(rid)
            if status not in TRANSITIONS.get(old["status"], set()):
                raise SettingsError("invalid_transition", "运行状态不可转换")
            if status in TERMINAL and any(
                e["state"] in {"intent", "unknown"} for e in old["effects"]
            ):
                raise SettingsError("invalid_transition", "副作用结果未核实，必须保留 unknown")
            if status == "succeeded" and any(
                s["status"] not in {"succeeded", "skipped"} for s in old["steps"]
            ):
                raise SettingsError("invalid_transition", "执行计划尚未完成")
            fields = dict(
                status=status,
                reason_code=reason_code,
                updated_at=stamp(),
                summary=safe_text(summary)[:2000],
            )
            if status == "running":
                fields["started_at"] = stamp()
            if status in TERMINAL:
                fields["finished_at"] = stamp()
            if recovery_state:
                fields["recovery_state"] = recovery_state
            assignments = ",".join(f"{key}=?" for key in fields)
            cursor = db.execute(
                f"UPDATE runs SET {assignments},state_version=state_version+1 "
                "WHERE run_id=? AND state_version=?",
                (*fields.values(), rid, version),
            )
            if cursor.rowcount != 1:
                raise SettingsError("state_conflict", "运行已被其他操作更新")
            if status in TERMINAL:
                db.execute("DELETE FROM run_reservations WHERE run_id=?", (rid,))
            self._event(db, events, rid, "state", fields)
        return self._get(rid)

    async def transition(self, rid, version, status, **kwargs):
        return await self.call(self._transition, rid, version, status, **kwargs)

    def _cancel(self, rid, reason="user"):
        old = self._get(rid)
        if old["status"] in TERMINAL or old["cancel_requested_at"]:
            return old
        with self.transaction() as (db, events):
            status = (
                "cancelled"
                if old["status"] == "queued"
                else ("cancelling" if old["status"] == "running" else old["status"])
            )
            db.execute(
                """UPDATE runs SET status=?,cancel_requested_at=?,stop_reason=?,
                updated_at=?,state_version=state_version+1,finished_at=? WHERE run_id=?
                AND state_version=?""",
                (
                    status,
                    stamp(),
                    reason,
                    stamp(),
                    stamp() if status == "cancelled" else None,
                    rid,
                    old["state_version"],
                ),
            )
            if status == "cancelled":
                db.execute("DELETE FROM run_reservations WHERE run_id=?", (rid,))
            self._event(db, events, rid, "state", {"status": status, "stop_reason": reason})
        return self._get(rid)

    async def cancel(self, rid, reason="user"):
        return await self.call(self._cancel, rid, reason)

    def _events(self, rid, after_seq=0, limit=200):
        self._get(rid)
        rows = (
            self._require()
            .execute(
                "SELECT * FROM run_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (rid, after_seq, limit + 1),
            )
            .fetchall()
        )
        items = [
            dict(run_id=rid, run_seq=r["seq"], type=r["type"], payload=json.loads(r["data_json"]))
            for r in rows[:limit]
        ]
        return dict(
            items=items,
            next_seq=items[-1]["run_seq"] if items else after_seq,
            has_more=len(rows) > limit,
        )

    async def events(self, rid, after_seq=0, limit=200):
        return await self.call(self._events, rid, after_seq, limit)

    def _list(self, task_id=None, status=None, cursor=None, limit=50, order="asc"):
        if order not in {"asc", "desc"}:
            raise SettingsError("validation_error", "排序方向无效", 422)
        clauses, args = [], []
        if task_id:
            clauses.append("task_id=?")
            args.append(task_id)
        if status:
            clauses.append("status=?")
            args.append(status)
        if cursor:
            try:
                decoded = json.loads(cursor)
                if not isinstance(decoded, list):
                    raise ValueError
                if len(decoded) == 2:
                    cursor_order = "asc"  # Preserve existing ascending cursors.
                    created, rid = decoded
                elif len(decoded) == 3:
                    cursor_order, created, rid = decoded
                else:
                    raise ValueError
                if cursor_order != order:
                    raise ValueError
                if not isinstance(created, str) or not isinstance(rid, str):
                    raise ValueError
            except ValueError, TypeError:
                raise SettingsError("validation_error", "游标无效", 422) from None
            clauses.append(
                "(created_at,run_id)>(?,?)" if order == "asc" else "(created_at,run_id)<(?,?)"
            )
            args.extend((created, rid))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = (
            self._require()
            .execute(
                "SELECT run_id,created_at FROM runs"
                + where
                + (
                    " ORDER BY created_at,run_id LIMIT ?"
                    if order == "asc"
                    else " ORDER BY created_at DESC,run_id DESC LIMIT ?"
                ),
                (*args, limit + 1),
            )
            .fetchall()
        )
        items = [self._get(row["run_id"]) for row in rows[:limit]]
        return dict(
            items=items,
            cursor=json.dumps(
                ([] if order == "asc" else ["desc"])
                + [items[-1]["created_at"], items[-1]["run_id"]]
            )
            if len(rows) > limit
            else None,
        )

    async def list(self, **kwargs):
        return await self.call(self._list, **kwargs)

    def task_summaries(self):
        """One read for all tasks' latest run and active ids; no snapshots/effects N+1."""
        return self._call(self._task_summaries, (), {})

    def _task_summaries(self):
        if self.readonly_error:
            raise unavailable()
        rows = (
            self._require()
            .execute(
                """WITH ranked AS (
                SELECT task_id,run_id,status,operation,created_at,finished_at,
                       row_number() OVER (
                           PARTITION BY task_id ORDER BY created_at DESC,run_id DESC
                       ) AS position
                FROM runs
            ) SELECT task_id,run_id,status,operation,created_at,finished_at,position
              FROM ranked WHERE position=1 OR status IN (?,?,?,?)""",
                ACTIVE,
            )
            .fetchall()
        )
        active, latest = {}, {}
        for row in rows:
            if row["status"] in ACTIVE:
                active[row["task_id"]] = row["run_id"]
            if row["position"] == 1:
                latest[row["task_id"]] = {
                    key: row[key]
                    for key in ("run_id", "status", "operation", "created_at", "finished_at")
                }
        return active, latest

    def _recover(self, run_ids=None, reason_code="backend_restart"):
        previous_error = self.readonly_error
        retry_write = run_ids is not None and previous_error == (
            "运行库无法可靠写入；已禁止后续写操作"
        )
        # _call holds the store lock: no normal writer can slip through this probe.
        # Only an actual recovery commit can lift a runtime write-failure guard.
        if retry_write:
            self.readonly_error = None
        try:
            recovered = self._recover_runs(run_ids, reason_code)
        except BaseException:
            if retry_write:
                self.readonly_error = previous_error
            raise
        if retry_write and not recovered:
            self.readonly_error = previous_error

    def _recover_runs(self, run_ids, reason_code):
        recovered = 0
        rows = (
            self._require()
            .execute("SELECT run_id FROM runs WHERE status IN (?,?,?,?)", ACTIVE)
            .fetchall()
        )
        for row in rows:
            if run_ids is not None and row["run_id"] not in run_ids:
                continue
            old = self._get(row["run_id"])
            effect = (
                self._require()
                .execute("SELECT 1 FROM run_effects WHERE run_id=?", (row["run_id"],))
                .fetchone()
            )
            if old["status"] == "queued" and not effect:
                self._transition(
                    old["run_id"], old["state_version"], "cancelled", reason_code=reason_code
                )
            else:
                self._transition(
                    old["run_id"],
                    old["state_version"],
                    "unknown",
                    reason_code=reason_code,
                    recovery_state="pending",
                )
            recovered += 1
        return recovered

    async def recover(self, *, run_ids=None, reason_code="backend_restart"):
        return await self.call(self._recover, run_ids, reason_code)

    async def lookup(self, request_id):
        def read():
            row = (
                self._require()
                .execute("SELECT run_id FROM runs WHERE request_id=?", (request_id,))
                .fetchone()
            )
            return self._get(row[0]) if row else None

        return await self.call(read)

    async def recovery_started(self, rid):
        def read():
            row = (
                self._require()
                .execute(
                    """SELECT ts FROM run_events WHERE run_id=?
                AND type='state' AND json_extract(data_json,'$.status')='unknown'
                ORDER BY seq LIMIT 1""",
                    (rid,),
                )
                .fetchone()
            )
            return row[0] if row else self._get(rid)["updated_at"]

        return await self.call(read)

    def _record(self, rid, step_no, kind, data, effect_id=None, state=None):
        with self.transaction() as (db, events):
            run = self._get(rid)
            if run["status"] in TERMINAL:
                raise SettingsError("invalid_transition", "终态运行不可修改")
            encoded = redact_exception(json.dumps(data, ensure_ascii=False))
            if len(encoded.encode()) > 256 * 1024:
                raise SettingsError("validation_error", "检查点过大", 422)
            if kind == "checkpoint":
                cursor = db.execute(
                    """UPDATE run_steps SET checkpoint_json=?,status='running',
                    started_at=coalesce(started_at,?) WHERE run_id=? AND step_no=?""",
                    (encoded, stamp(), rid, step_no),
                )
                if cursor.rowcount != 1:
                    raise SettingsError("not_found", "步骤不存在", 404)
                db.execute("UPDATE runs SET phase=? WHERE run_id=?", (data["kind"], rid))
            elif kind == "step_finished":
                if data.get("status") not in {"succeeded", "failed", "skipped", "unknown"}:
                    raise SettingsError("validation_error", "步骤状态无效", 422)
                previous = db.execute(
                    "SELECT checkpoint_json FROM run_steps WHERE run_id=? AND step_no=?",
                    (rid, step_no),
                ).fetchone()
                if previous is None:
                    raise SettingsError("not_found", "步骤不存在", 404)
                encoded = redact_exception(
                    json.dumps({**json.loads(previous[0]), **data}, ensure_ascii=False)
                )
                cursor = db.execute(
                    """UPDATE run_steps SET status=?,finished_at=?,checkpoint_json=?
                    WHERE run_id=? AND step_no=?""",
                    (data["status"], stamp(), encoded, rid, step_no),
                )
                if cursor.rowcount != 1:
                    raise SettingsError("not_found", "步骤不存在", 404)
            elif kind == "intent":
                cancelling_build = data["kind"] == "build_cancel" and run["status"] == "cancelling"
                if data["kind"] == "build_cancel" and not cancelling_build:
                    raise SettingsError("invalid_transition", "尚未请求停止，禁止远端取消")
                if cancelling_build:
                    creates = [
                        e
                        for e in run["effects"]
                        if e["kind"] == "build_create"
                        and e["state"] == "confirmed"
                        and e["owned"]
                        and e["step_no"] == step_no
                    ]
                    known_ids = {str(e["remote_id"]) for e in creates if e["remote_id"]}
                    for step in run["steps"]:
                        if creates and step["step_no"] == step_no:
                            known_ids.update(
                                str(step["checkpoint"][k])
                                for k in ("build_id", "pipeline_run_id")
                                if step["checkpoint"].get(k) is not None
                            )
                    requested = {
                        str(data[k])
                        for k in ("build_id", "pipeline_run_id")
                        if data.get(k) is not None
                    }
                    if not creates or not requested or not requested.issubset(known_ids):
                        raise SettingsError("invalid_transition", "未核实归属，禁止取消远端构建")
                if not cancelling_build and (
                    run["status"] != "running" or run["cancel_requested_at"]
                ):
                    raise SettingsError("invalid_transition", "停止后禁止新副作用")
                resource = (
                    data.get("branch")
                    if data["kind"] == "git_push"
                    else data.get("environment_id")
                    if data["kind"] == "env_deploy"
                    else data.get("api_kind")
                    if data["kind"] == "build_cancel"
                    else None
                )
                intent_key = json.dumps([rid, step_no, data["kind"], resource])
                if db.execute(
                    "SELECT 1 FROM run_effects WHERE intent_key=?", (intent_key,)
                ).fetchone():
                    raise SettingsError("effect_already_recorded", "副作用意图已存在；只能查询核实")
                db.execute(
                    """INSERT INTO run_effects(effect_id,run_id,step_no,kind,
                    intent_key,intent_json,state,intent_at) VALUES(?,?,?,?,?,?,'intent',?)""",
                    (effect_id, rid, step_no, data["kind"], intent_key, encoded, stamp()),
                )
            elif kind == "receipt":
                remote_id = data.get("remote_id")
                if (
                    state not in {"confirmed", "rejected", "unknown"}
                    or remote_id is not None
                    and (
                        not isinstance(remote_id, str)
                        or not re.fullmatch(r"[1-9][0-9]{0,9}", remote_id)
                        or int(remote_id) > 2147483647
                    )
                    or type(data.get("owned", False)) is not bool
                ):
                    raise SettingsError("validation_error", "远端回执标识或状态无效", 422)
                row = db.execute(
                    "SELECT state FROM run_effects WHERE effect_id=? AND run_id=?", (effect_id, rid)
                ).fetchone()
                if row is None or row[0] not in ("intent", "unknown"):
                    raise SettingsError("invalid_transition", "副作用回执不可覆盖")
                db.execute(
                    """UPDATE run_effects SET state=?,remote_id=?,owned=?,confirmed_at=?
                    WHERE effect_id=? AND run_id=?""",
                    (
                        state,
                        data.get("remote_id"),
                        int(data.get("owned", False)),
                        stamp(),
                        effect_id,
                        rid,
                    ),
                )
            else:
                raise ValueError("invalid journal mutation")
            db.execute(
                "UPDATE runs SET state_version=state_version+1,updated_at=? WHERE run_id=?",
                (stamp(), rid),
            )
            self._event(
                db,
                events,
                rid,
                "checkpoint",
                {"step_no": step_no, "kind": kind, "data": json.loads(encoded)},
            )

    async def record(self, *args, **kwargs):
        return await self.call(self._record, *args, **kwargs)

    async def log(self, rid, text, *, raw_bytes=None):
        def append():
            with self.transaction() as (db, events):
                run = self._get(rid)
                if run["log_bytes"] >= 20 * 1024 * 1024:
                    return
                # UTF-8 slice is bounded and never leaks a partial code point.
                safe = safe_text(text).encode()[:8192].decode(errors="ignore")
                consumed = len(text.encode()) if raw_bytes is None else max(0, raw_bytes)
                budget = min(20 * 1024 * 1024, run["log_bytes"] + consumed)
                db.execute(
                    "UPDATE runs SET log_bytes=?,state_version=state_version+1 WHERE run_id=?",
                    (budget, rid),
                )
                if safe:
                    self._event(db, events, rid, "log", {"text": safe})
                if budget >= 20 * 1024 * 1024:
                    self._event(db, events, rid, "log", {"text": "日志已达上限，后续输出省略"})

        return await self.call(append)

    def active_snapshots(self):
        with self._lock:
            if self.readonly_error:
                raise unavailable()
            if self._db is None:
                if self.readonly_error:
                    raise unavailable()
                return []
            return [
                self._get(row[0])
                for row in self._db.execute(
                    "SELECT run_id FROM runs WHERE status IN (?,?,?,?)", ACTIVE
                ).fetchall()
            ]

    def _close(self):
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None

    async def close(self):
        await asyncio.to_thread(self._close)
