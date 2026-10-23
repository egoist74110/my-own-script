"""Private Telegram journal. No message bodies or raw update JSON are persisted."""

import asyncio
import contextlib
import fcntl
import json
import os
import secrets
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from toolbox_backend.adapters.config_store import private_dir, stamp
from toolbox_backend.adapters.run_store import secure_open
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.logging_setup import contains_secret, redact_exception

SCHEMA = (
    """CREATE TABLE tg_bots(bot_id TEXT PRIMARY KEY, username TEXT, next_offset INTEGER
       NOT NULL DEFAULT 0, baseline_done INTEGER NOT NULL DEFAULT 0, state TEXT,
       updated_at TEXT NOT NULL, slot TEXT)""",
    """CREATE TABLE tg_updates(bot_id TEXT, update_id INTEGER, received_at TEXT,
       kind TEXT, chat_id TEXT, user_id TEXT, command TEXT, status TEXT, reason TEXT,
       handled_at TEXT, PRIMARY KEY(bot_id,update_id))""",
    """CREATE TABLE tg_actions(token TEXT PRIMARY KEY, bot_id TEXT, chat_id TEXT,
       user_id TEXT, kind TEXT, payload_json TEXT, created_at TEXT, expires_at TEXT,
       consumed_at TEXT, result_run_id TEXT)""",
    """CREATE TABLE tg_outbox(id INTEGER PRIMARY KEY, bot_id TEXT, chat_id TEXT,
       dedup_key TEXT UNIQUE, kind TEXT, text TEXT, reply_markup_json TEXT,
       edit_message_id INTEGER, state TEXT, attempts INTEGER DEFAULT 0,
       next_attempt_at TEXT, created_at TEXT, sent_at TEXT, error_category TEXT)""",
)


def unavailable():
    return SettingsError("telegram_store_unavailable", "Telegram 数据库不可用，原件保留", 503)


class TelegramStore:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).absolute()
        self.path = self.data_dir / "telegram.sqlite3"
        self._db = None
        self._fd = None
        self._lock = threading.RLock()
        self._holders = set()
        self.readonly_error = None
        self.checkpoint = lambda _: None

    def require(self):
        if self._db is None or self.readonly_error:
            raise unavailable()
        return self._db

    def _initialize(self):
        with self._lock:
            if self._db is not None or self.readonly_error:
                return
            try:
                if self.data_dir.is_symlink():
                    raise OSError("symlink")
                private_dir(self.data_dir)
                self._fd = secure_open(self.data_dir / "telegram.lock")
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                for suffix in ("", "-wal", "-shm"):
                    if Path(str(self.path) + suffix).is_symlink():
                        raise OSError("symlink")
                fd = secure_open(self.path)
                os.close(fd)
                self._db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
                self._db.row_factory = sqlite3.Row
                db = self._db
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2):
                    self.readonly_error = "Telegram 数据库版本不支持"
                    db.close()
                    self._db = None
                    return
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA synchronous=FULL")
                db.execute("PRAGMA busy_timeout=5000")
                if version == 0:
                    with self.transaction() as db:
                        for statement in SCHEMA:
                            db.execute(statement)
                        db.execute("PRAGMA user_version=2")
                elif version == 1:
                    # v1 -> v2 (S5-C): one transaction; every pre-existing bot is the main slot.
                    with self.transaction() as db:
                        db.execute("ALTER TABLE tg_bots ADD COLUMN slot TEXT")
                        db.execute("UPDATE tg_bots SET slot='main'")
                        db.execute("PRAGMA user_version=2")
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("corrupt")
                with self.transaction() as db:
                    db.execute(
                        "UPDATE tg_outbox SET state='unknown',error_category='interrupted' "
                        "WHERE state='sending'"
                    )
                    cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
                    db.execute(
                        "DELETE FROM tg_updates WHERE received_at<? OR rowid NOT IN "
                        "(SELECT rowid FROM tg_updates ORDER BY received_at DESC, "
                        "update_id DESC LIMIT 10000)",
                        (cutoff,),
                    )
                    db.execute("DELETE FROM tg_actions WHERE expires_at<?", (stamp(),))
                self._permissions()
            except OSError, sqlite3.Error, ValueError:
                self.readonly_error = "Telegram 数据库损坏、不可写或已被占用"
                self._close()

    def _permissions(self):
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.path) + suffix)
            if path.exists():
                path.chmod(0o600)

    async def initialize(self, holder=None):
        # A holder is registered before awaiting so a concurrent release cannot close the
        # database under a slot that is still starting.
        if holder is not None:
            self._holders.add(holder)
        try:
            await self.call(self._initialize)
        except BaseException:
            if holder is not None:
                self._holders.discard(holder)
            raise
        if holder is not None and self._db is None:
            self._holders.discard(holder)

    def _call(self, fn, args, kwargs):
        with self._lock:
            try:
                return fn(*args, **kwargs)
            except sqlite3.Error:
                self.readonly_error = "Telegram 数据库无法可靠写入"
                raise unavailable() from None

    async def call(self, fn, *args, **kwargs):
        task = asyncio.create_task(asyncio.to_thread(self._call, fn, args, kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    @contextlib.contextmanager
    def transaction(self):
        db = self.require()
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            self.checkpoint("before_commit")
            db.commit()
        except BaseException:
            db.rollback()
            raise

    async def bot(self, bot_id, username=None, slot=None):
        def read():
            with self.transaction() as db:
                db.execute(
                    "INSERT OR IGNORE INTO tg_bots(bot_id,username,updated_at,slot) "
                    "VALUES(?,?,?,?)",
                    (bot_id, username, stamp(), slot),
                )
                if slot is not None:
                    db.execute("UPDATE tg_bots SET slot=? WHERE bot_id=?", (slot, bot_id))
                if username is not None:
                    db.execute("UPDATE tg_bots SET username=? WHERE bot_id=?", (username, bot_id))
                return dict(
                    db.execute("SELECT * FROM tg_bots WHERE bot_id=?", (bot_id,)).fetchone()
                )

        return await self.call(read)

    async def set_state(self, bot_id, state):
        def save():
            with self.transaction() as db:
                db.execute(
                    "UPDATE tg_bots SET state=?,updated_at=? WHERE bot_id=?",
                    (state, stamp(), bot_id),
                )

        await self.call(save)

    async def baseline(self, bot_id, offset):
        def save():
            with self.transaction() as db:
                db.execute(
                    "UPDATE tg_bots SET baseline_done=1,next_offset=max(next_offset,?),"
                    "updated_at=? WHERE bot_id=?",
                    (offset, stamp(), bot_id),
                )

        await self.call(save)

    async def register(self, bot_id, update_id, kind, chat_id, user_id, command):
        def save():
            with self.transaction() as db:
                cursor = db.execute(
                    "INSERT OR IGNORE INTO tg_updates VALUES (?,?,?,?,?,?,?,'received',NULL,NULL)",
                    (bot_id, update_id, stamp(), kind, chat_id, user_id, command),
                )
                db.execute(
                    "UPDATE tg_bots SET next_offset=max(next_offset,?),updated_at=? WHERE bot_id=?",
                    (update_id + 1, stamp(), bot_id),
                )
                return cursor.rowcount == 1

        return await self.call(save)

    async def finish(self, bot_id, update_id, status, reason=None):
        def save():
            with self.transaction() as db:
                db.execute(
                    "UPDATE tg_updates SET status=?,reason=?,handled_at=? "
                    "WHERE bot_id=? AND update_id=?",
                    (status, reason, stamp(), bot_id, update_id),
                )

        await self.call(save)

    async def activity(self, limit=50):
        return await self.call(
            lambda: [
                dict(r)
                for r in self.require()
                .execute(
                    "SELECT received_at,kind,command,chat_id,status,reason FROM tg_updates "
                    "ORDER BY received_at DESC,update_id DESC LIMIT ?",
                    (limit,),
                )
                .fetchall()
            ]
        )

    async def enqueue(
        self,
        bot_id,
        chat_id,
        dedup_key,
        text,
        *,
        kind="reply",
        error_category=None,
        reply_markup=None,
        edit_message_id=None,
        chunk_size=4000,
    ):
        markup_json = json.dumps(reply_markup) if reply_markup else ""
        if (
            contains_secret(text)
            or contains_secret(markup_json)
            or redact_exception(markup_json) != markup_json
        ):
            text, error_category, reply_markup = "内容包含敏感信息，已隐藏", "redacted", None
        else:
            text = redact_exception(text)

        def save():
            key_base = dedup_key
            with self.transaction() as db:
                prior = db.execute(
                    "SELECT bot_id FROM tg_outbox WHERE dedup_key=?", (key_base,)
                ).fetchone()
                if prior and prior["bot_id"] != bot_id:
                    key_base = f"bot:{bot_id}:{dedup_key}"
                if db.execute("SELECT 1 FROM tg_outbox WHERE dedup_key=?", (key_base,)).fetchone():
                    return
                chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)] or [""]
                for i, chunk in enumerate(chunks):
                    pending = db.execute("SELECT count(*) FROM tg_outbox WHERE state='pending'")
                    if pending.fetchone()[0] >= 500:
                        # AI projection loses tool summaries first, then plain notifications,
                        # then the oldest assistant text; it never raises into a session.
                        victim = None
                        for victim_kind in ("ai_tool", "notify", "ai_text"):
                            victim = db.execute(
                                "SELECT id FROM tg_outbox WHERE state='pending' "
                                "AND kind=? ORDER BY id LIMIT 1",
                                (victim_kind,),
                            ).fetchone()
                            if victim:
                                break
                        if victim and not (kind == "ai_tool" and victim_kind != "ai_tool"):
                            db.execute(
                                "UPDATE tg_outbox SET state='dropped',text='' WHERE id=?",
                                (victim[0],),
                            )
                        elif kind.startswith("ai_"):
                            return  # projection is lossy by contract; the newest is dropped
                        else:
                            raise SettingsError("busy", "Telegram 发件箱已满", 503)
                    key = key_base if i == 0 else f"{key_base}:part:{i}"
                    db.execute(
                        "INSERT OR IGNORE INTO tg_outbox "
                        "(bot_id,chat_id,dedup_key,kind,text,state,next_attempt_at,"
                        "created_at,error_category,reply_markup_json,edit_message_id) "
                        "VALUES(?,?,?,?,?,'pending',?,?,?,?,?)",
                        (
                            bot_id,
                            chat_id,
                            key,
                            kind,
                            chunk,
                            stamp(),
                            stamp(),
                            error_category,
                            json.dumps(reply_markup)
                            if reply_markup and i == len(chunks) - 1
                            else None,
                            edit_message_id if i == 0 else None,
                        ),
                    )

        await self.call(save)

    async def drop_pending_ai(self, bot_id):
        """A re-enabled AI slot never replays output of an earlier run of the slot."""

        def save():
            with self.transaction() as db:
                db.execute(
                    "UPDATE tg_outbox SET state='dropped',text='' WHERE bot_id=? "
                    "AND state='pending' AND kind LIKE 'ai\\_%' ESCAPE '\\'",
                    (bot_id,),
                )

        await self.call(save)

    async def take(self, bot_id, exclude_chats=()):
        def save():
            with self.transaction() as db:
                marks = ",".join("?" for _ in exclude_chats)
                row = db.execute(
                    "SELECT * FROM tg_outbox WHERE bot_id=? AND state='pending' "
                    "AND next_attempt_at<=? "
                    + (f"AND chat_id NOT IN ({marks}) " if exclude_chats else "")
                    + "ORDER BY kind IN ('reply','ai_approval') DESC,id LIMIT 1",
                    (bot_id, stamp(), *exclude_chats),
                ).fetchone()
                if row is None:
                    return None
                db.execute(
                    "UPDATE tg_outbox SET state='sending',attempts=attempts+1 WHERE id=?",
                    (row["id"],),
                )
                result = dict(row)
                result["attempts"] += 1
                return result

        return await self.call(save)

    async def sent(self, ident, state, category=None, delay=0):
        def save():
            with self.transaction() as db:
                db.execute(
                    "UPDATE tg_outbox SET state=?,error_category=coalesce(?,error_category),"
                    "next_attempt_at=?,sent_at=?,text=CASE WHEN ?='sent' THEN '' "
                    "ELSE text END WHERE id=?",
                    (
                        state,
                        category,
                        (datetime.now(UTC) + timedelta(seconds=delay)).isoformat(),
                        stamp() if state == "sent" else None,
                        state,
                        ident,
                    ),
                )

        await self.call(save)

    async def action(self, bot_id, chat_id, user_id, kind, payload, ttl=300):
        if contains_secret(json.dumps(payload)):
            raise SettingsError("validation_error", "动作参数包含凭据值", 422)

        def save():
            token, now = secrets.token_urlsafe(16), stamp()
            with self.transaction() as db:
                # Keep unconsumed expired actions within the same eviction bounds so
                # a late click can explain expiry even after another menu is opened.
                db.execute(
                    "DELETE FROM tg_actions WHERE expires_at<=? AND consumed_at IS NOT NULL", (now,)
                )
                for clause, args, limit in (
                    ("bot_id=?", (bot_id,), 256),
                    ("bot_id=? AND chat_id=?", (bot_id, chat_id), 16),
                ):
                    rows = db.execute(
                        "SELECT token FROM tg_actions WHERE "
                        + clause
                        + " AND consumed_at IS NULL ORDER BY created_at,token",
                        args,
                    ).fetchall()
                    for row in rows[: max(0, len(rows) - limit + 1)]:
                        db.execute("DELETE FROM tg_actions WHERE token=?", (row[0],))
                db.execute(
                    "INSERT INTO tg_actions VALUES(?,?,?,?,?,?,?,?,NULL,NULL)",
                    (
                        token,
                        bot_id,
                        chat_id,
                        user_id,
                        kind,
                        json.dumps(payload),
                        now,
                        (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat(),
                    ),
                )
            return token

        return await self.call(save)

    async def consume(self, token, bot_id, chat_id, user_id):
        def save():
            with self.transaction() as db:
                row = db.execute(
                    "SELECT * FROM tg_actions WHERE token=? AND bot_id=? "
                    "AND chat_id=? AND user_id=? AND expires_at>? "
                    "AND consumed_at IS NULL",
                    (token, bot_id, chat_id, user_id, stamp()),
                ).fetchone()
                if row is None:
                    return None
                db.execute("UPDATE tg_actions SET consumed_at=? WHERE token=?", (stamp(), token))
                return {**dict(row), "payload": json.loads(row["payload_json"])}

        return await self.call(save)

    async def inspect_action(self, token, bot_id, chat_id, user_id):
        def read():
            row = (
                self.require()
                .execute(
                    "SELECT * FROM tg_actions WHERE token=? AND bot_id=? "
                    "AND chat_id=? AND user_id=?",
                    (token, bot_id, chat_id, user_id),
                )
                .fetchone()
            )
            return {**dict(row), "payload": json.loads(row["payload_json"])} if row else None

        return await self.call(read)

    async def cancel_action(self, token, bot_id, chat_id, user_id):
        def save():
            with self.transaction() as db:
                row = db.execute(
                    "UPDATE tg_actions SET consumed_at=? WHERE token=? AND bot_id=? "
                    "AND chat_id=? AND user_id=? AND consumed_at IS NULL",
                    (stamp(), token, bot_id, chat_id, user_id),
                )
                return row.rowcount == 1

        return await self.call(save)

    async def action_result(self, token, run_id):
        def save():
            with self.transaction() as db:
                db.execute(
                    "UPDATE tg_actions SET result_run_id=? WHERE token=? "
                    "AND consumed_at IS NOT NULL",
                    (run_id, token),
                )

        await self.call(save)

    def _close(self):
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None

    async def close(self, holder=None):
        if holder is not None:
            self._holders.discard(holder)
            if self._holders:
                return
        await asyncio.to_thread(self._close)
