"""Headless Claude 会话 ↔ Telegram 桥（CC Pocket 式结构化聊天）。

和旧的 ai_dev_tg_bridge（屏幕镜像 + 软键盘遥控）彻底不同：

- 后端是 HeadlessSession（claude stream-json），事件是结构化的（助手文本 / 工具调用 /
  工具结果 / 一轮结束），桥把每条事件渲染成一条**正经 TG 消息**，不再 editMessage 刷屏。
- 新建会话是个多步向导：选仓库（或手输路径）→ 选模型 → 选 effort → 选权限模式。
- 用户在 TG 直接打字 = 给当前聚焦会话发一轮提示词（reply 某会话消息也行）。

callback_data 命名空间统一用 "cc:"。所有同步 UI（菜单/向导）由 handle_* 返回
(text, markup) 交给 controller 发送；会话产生的异步输出由本桥用自己的 token 直接推送。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import httpx

from app_ado.ai_headless_session import (
    HeadlessEvent,
    HeadlessSession,
    HeadlessSessionManager,
    resolve_claude_executable,
)


_TG_HTTP_TIMEOUT = 15.0
_TG_MAX_LEN = 3900  # 给 markdown 包裹留余量（TG 上限 4096）

# 新建会话统一用 claude 的 auto 模式（分类器自动判断每个工具该不该跑），
# 不再让用户选 model / effort / permission。这套保留为 dead code（cc_approval_hook
# 之类的设施仍在仓库里，需要时可重新接回）。


def _short(s: str, n: int) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _tool_summary(tool_name: str, inp: dict) -> str:
    """把工具调用浓缩成一行人话。"""
    inp = inp or {}
    if tool_name == "Bash":
        return _short(inp.get("command") or "", 200)
    if tool_name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        return _short(inp.get("file_path") or inp.get("notebook_path") or "", 200)
    if tool_name == "Glob":
        return _short(inp.get("pattern") or "", 120)
    if tool_name == "Grep":
        return _short(inp.get("pattern") or inp.get("query") or "", 120)
    if tool_name == "TodoWrite":
        todos = inp.get("todos") or []
        return f"{len(todos)} 项待办"
    if tool_name in ("WebFetch", "WebSearch"):
        return _short(inp.get("url") or inp.get("query") or "", 160)
    if tool_name == "Task":
        return _short(inp.get("description") or "", 160)
    # 兜底：拣几个短字段
    for k in ("description", "prompt", "path", "url"):
        if inp.get(k):
            return _short(str(inp[k]), 160)
    return ""


class AiHeadlessTgBridge:
    def __init__(
        self,
        *,
        manager: HeadlessSessionManager,
        bot_token_fn: Callable[[], Optional[str]],
        owner_chat_id_fn: Callable[[], Optional[str]],
    ) -> None:
        self._manager = manager
        self._bot_token_fn = bot_token_fn
        self._owner_chat_id_fn = owner_chat_id_fn

        self._lock = threading.Lock()
        # sid -> set(chat_id)：会话输出推给哪些 chat
        self._sid_to_chats: dict[str, set[str]] = {}
        # chat_id -> sid：当前聚焦会话
        self._chat_focus: dict[str, str] = {}
        # chat_id -> 向导状态 {step, cwd, repo_name, model, effort, expects}
        self._wizard: dict[str, dict] = {}

        # 审批（PreToolUse hook 落盘 IPC）
        self._appr_dir: Optional[Path] = None
        self._settings_path: str = ""
        self._seen_reqs: set[str] = set()
        self._stop_appr = threading.Event()
        self._appr_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # 生命周期 + 审批监听
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._appr_thread and self._appr_thread.is_alive():
            return
        self._ensure_hook_settings()
        self._stop_appr.clear()
        self._appr_thread = threading.Thread(
            target=self._approval_loop, daemon=True, name="cc-approval")
        self._appr_thread.start()

    def stop(self) -> None:
        self._stop_appr.set()

    def shutdown(self) -> None:
        self.stop()
        self._manager.shutdown()

    def _ensure_hook_settings(self) -> str:
        """生成注入给 headless 会话的 --settings：PreToolUse 钩子拦 Bash → 推 TG 审批。"""
        if self._settings_path:
            return self._settings_path
        import sys
        from app_ado.store import config_dir
        base = Path(config_dir())
        appr = base / "cc_approvals"
        appr.mkdir(parents=True, exist_ok=True)
        self._appr_dir = appr
        hook_py = str(Path(__file__).resolve().parent / "cc_approval_hook.py")
        py = sys.executable or "python3"
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{
                            "type": "command",
                            "command": f'"{py}" "{hook_py}" "{appr}"',
                            "timeout": 600,
                        }],
                    }
                ]
            }
        }
        sp = base / "cc_hook_settings.json"
        sp.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        self._settings_path = str(sp)
        return self._settings_path

    def _approval_loop(self) -> None:
        while not self._stop_appr.is_set():
            try:
                d = self._appr_dir
                if d and d.is_dir():
                    current: set[str] = set()
                    for f in sorted(d.glob("*.req")):
                        rid = f.stem
                        current.add(rid)
                        if rid in self._seen_reqs:
                            continue
                        self._seen_reqs.add(rid)
                        try:
                            req = json.loads(f.read_text(encoding="utf-8"))
                        except Exception:
                            continue
                        self._push_approval(req)
                    # 钩子拿到决定后会删掉 .req；据此回收 seen 集，避免只增不减
                    self._seen_reqs &= current
            except Exception:
                pass
            self._stop_appr.wait(0.5)

    def _chats_for_claude_session(self, claude_session_id: str) -> list[str]:
        for info in self._manager.list():
            if claude_session_id and info.claude_session_id == claude_session_id:
                with self._lock:
                    chats = list(self._sid_to_chats.get(info.sid, set()))
                if chats:
                    return chats
        owner = self._owner_chat_id_fn()
        return [str(owner)] if owner else []

    def _push_approval(self, req: dict) -> None:
        token = self._bot_token_fn()
        if not token:
            # 没法问用户：写个拒绝，别让钩子干等到超时
            self._write_resp(req.get("req_id", ""), "deny", "无 Bot Token，无法审批")
            return
        rid = req.get("req_id", "")
        tool = req.get("tool_name", "")
        summ = _tool_summary(tool, req.get("tool_input") or {})
        cwd = req.get("cwd", "")
        text = (
            f"🔐 审批请求 · {tool}\n"
            + (f"`{summ}`\n" if summ else "")
            + (f"📂 {cwd}\n" if cwd else "")
            + "点「允许」放行这一步，「拒绝」则跳过。"
        )
        kb = {"inline_keyboard": [[
            {"text": "✅ 允许", "callback_data": f"cc:appr:{rid}:allow"},
            {"text": "❌ 拒绝", "callback_data": f"cc:appr:{rid}:deny"},
        ]]}
        for chat_id in self._chats_for_claude_session(req.get("session_id", "")):
            self._tg_send(token, chat_id, text, kb=kb, markdown=True)

    def _write_resp(self, req_id: str, decision: str, reason: str = "") -> None:
        if not self._appr_dir or not req_id:
            return
        try:
            tmp = self._appr_dir / f"{req_id}.resp.tmp"
            tmp.write_text(json.dumps({"decision": decision, "reason": reason},
                                      ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._appr_dir / f"{req_id}.resp")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 权限（沿用 owner/group ACL，与旧 dev 桥一致）
    # ------------------------------------------------------------------

    @staticmethod
    def can_dev(role: str, group: Optional[dict], action: str) -> bool:
        if role == "owner":
            return True
        if role != "group" or not group:
            return False
        flag_map = {
            "dev_status": "can_dev_status",
            "dev_run": "can_dev_run",
            "dev_message": "can_dev_message",
            "dev_stop": "can_dev_stop",
        }
        flag = flag_map.get(action)
        if flag is None:
            return False
        return bool(group.get(flag, False))

    # ------------------------------------------------------------------
    # 主菜单
    # ------------------------------------------------------------------

    def handle_menu(self, chat_id: str, role: str, group: Optional[dict]) -> tuple[Optional[str], Optional[dict]]:
        if not self.can_dev(role, group, "dev_status"):
            return "无权限：AI 开发", None
        infos = self._manager.list()
        focus = self._chat_focus.get(str(chat_id))
        kb: list[list[dict]] = []
        status_zh = {"starting": "启动中", "idle": "空闲", "busy": "运行中", "exited": "已结束"}
        for info in infos:
            mark = "★" if info.sid == focus else " "
            st = status_zh.get(info.status, info.status)
            if info.status == "exited" and info.exit_code is not None:
                st = f"已结束({info.exit_code})"
            label = f"{mark} {info.repo_name} [{st}]"
            kb.append([
                {"text": label, "callback_data": f"cc:focus:{info.sid}"},
                {"text": "🗑", "callback_data": f"cc:kill:{info.sid}"},
            ])
        kb.append([{"text": "➕ 新建 Claude 会话", "callback_data": "cc:new"}])
        head = "🤖 Claude 会话" + (f"\n共 {len(infos)} 个会话。" if infos else "\n暂无会话，点下面新建。")
        return head, {"inline_keyboard": kb}

    # ------------------------------------------------------------------
    # callback 分发（controller 把 "cc:" 前缀的 callback_data 丢进来）
    # ------------------------------------------------------------------

    def handle_callback(
        self, data: str, chat_id: str, role: str, group: Optional[dict]
    ) -> tuple[Optional[str], Optional[dict]]:
        cid = str(chat_id)
        try:
            _, rest = data.split(":", 1)
        except ValueError:
            return None, None

        if rest == "menu":
            return self.handle_menu(chat_id, role, group)

        if rest == "cancel":
            self._wizard.pop(cid, None)
            return "已取消新建。", None

        if rest == "new":
            if not self.can_dev(role, group, "dev_run"):
                return "无权限：dev_run", None
            return self._wiz_start(cid)

        if rest.startswith("proj:"):
            return self._wiz_pick_proj(cid, rest.split(":", 1)[1])

        if rest == "repo_manual":
            self._wizard.setdefault(cid, {})["expects"] = "path"
            self._wizard[cid]["step"] = "repo_manual"
            return (
                "✍️ 回复本条消息，发送项目目录的绝对路径（例如 /Users/you/proj）：",
                {"force_reply": True, "input_field_placeholder": "/Users/you/proj", "selective": True},
            )

        if rest == "fresh":
            return self._wiz_fresh(cid)

        if rest.startswith("resume:"):
            return self._wiz_pick_resume(cid, rest.split(":", 1)[1])

        if rest == "filter":
            self._wizard.setdefault(cid, {})["expects"] = "filter"
            return (
                "🔎 回复本条消息，发送筛选关键字（匹配会话标题）：",
                {"force_reply": True, "input_field_placeholder": "关键字", "selective": True},
            )

        if rest.startswith("focus:"):
            sid = rest.split(":", 1)[1]
            if not self._manager.get(sid):
                return f"会话不存在：{sid}", None
            self._chat_focus[cid] = sid
            self._sid_to_chats.setdefault(sid, set()).add(cid)
            return f"已切换到会话 {sid}，直接打字即可发提示词。", None

        if rest.startswith("kill:"):
            if not self.can_dev(role, group, "dev_stop"):
                return "无权限：dev_stop", None
            sid = rest.split(":", 1)[1]
            ok = self._manager.remove(sid)
            with self._lock:
                self._sid_to_chats.pop(sid, None)
                for c, f in list(self._chat_focus.items()):
                    if f == sid:
                        self._chat_focus.pop(c, None)
            return (f"已结束会话 {sid}。" if ok else f"会话不存在：{sid}"), None

        if rest.startswith("prompt:"):
            sid = rest.split(":", 1)[1]
            sess = self._manager.get(sid)
            if not sess or sess.info.status == "exited":
                return "会话不存在或已结束。", None
            self._chat_focus[cid] = sid
            self._sid_to_chats.setdefault(sid, set()).add(cid)
            return (
                f"📝 给会话 {sid} 发提示词：",
                {"force_reply": True, "input_field_placeholder": f"发给 {sid}", "selective": True},
            )

        if rest.startswith("stop:"):
            sid = rest.split(":", 1)[1]
            sess = self._manager.get(sid)
            if not sess or sess.info.status == "exited":
                return "会话不存在或已结束。", None
            if not sess.is_busy:
                return "当前没有正在执行的回合。", None
            sess.interrupt()
            return "⏹ 已请求停止本轮（多步任务会在当前步骤后停下）。", None

        if rest.startswith("appr:"):
            try:
                _, rid, decision = rest.split(":", 2)
            except ValueError:
                return None, None
            decision = "allow" if decision == "allow" else "deny"
            self._write_resp(rid, decision, "用户允许" if decision == "allow" else "用户拒绝")
            return ("✅ 已允许，继续执行" if decision == "allow" else "❌ 已拒绝，跳过该步"), None

        return None, None

    # ------------------------------------------------------------------
    # 向导各步
    # ------------------------------------------------------------------

    def _wiz_start(self, cid: str) -> tuple[str, dict]:
        """① 选项目：📁 本地配好的仓库 + 🕐 最近跑过 claude 的目录，按绝对路径去重。"""
        from app_ado.store import load_ui_settings
        from app_ado import claude_sessions
        s = load_ui_settings()
        repos = list(getattr(s, "local_repos", []) or [])
        recent = claude_sessions.list_recent_projects(limit=12)
        seen: set[str] = set()
        options: list[tuple[str, str, str]] = []  # (abspath, name, kind)
        for r in repos:
            ap = os.path.abspath(os.path.expanduser(r.path or ""))
            if not ap or ap in seen:
                continue
            seen.add(ap)
            options.append((ap, r.name, "repo"))
        for p in recent:
            ap = os.path.abspath(p.path)
            if ap in seen:
                continue
            seen.add(ap)
            options.append((ap, p.name, "recent"))
        self._wizard[cid] = {"step": "pick_repo", "proj_options": options}
        kb: list[list[dict]] = []
        for i, (ap, name, kind) in enumerate(options):
            icon = "📁" if kind == "repo" else "🕐"
            kb.append([{"text": f"{icon} {name}", "callback_data": f"cc:proj:{i}"}])
        kb.append([{"text": "✍️ 手输路径", "callback_data": "cc:repo_manual"}])
        kb.append([{"text": "✖ 取消", "callback_data": "cc:cancel"}])
        head = ("① 选择项目（📁 已配置 / 🕐 最近用过）：" if options
                else "① 点「手输路径」输入项目目录绝对路径：")
        return head, {"inline_keyboard": kb}

    def _wiz_set_cwd(self, cid: str, cwd: str, repo_name: str) -> tuple[Optional[str], Optional[dict]]:
        w = self._wizard.setdefault(cid, {})
        w["cwd"] = cwd
        w["repo_name"] = repo_name
        w.pop("expects", None)
        return self._wiz_session_picker(cid)

    def _wiz_pick_proj(self, cid: str, idx_s: str) -> tuple[Optional[str], Optional[dict]]:
        w = self._wizard.get(cid)
        if not w:
            return "向导已过期，请重新点「新建」。", None
        try:
            idx = int(idx_s)
        except ValueError:
            return "无效选择。", None
        opts = w.get("proj_options") or []
        if idx < 0 or idx >= len(opts):
            return "无效选择。", None
        ap, name, _kind = opts[idx]
        return self._wiz_set_cwd(cid, ap, name)

    # ---- ② 选会话：续聊已有 / 全新 / 关键字筛选 ----
    def _wiz_session_picker(self, cid: str, query: str = "") -> tuple[Optional[str], Optional[dict]]:
        from app_ado import claude_sessions
        w = self._wizard.setdefault(cid, {})
        w["step"] = "pick_session"
        w.pop("expects", None)
        cwd = w.get("cwd") or ""
        repo_name = w.get("repo_name") or cwd
        sessions = claude_sessions.list_sessions(cwd, limit=10, query=query)
        kb: list[list[dict]] = [[{"text": "🆕 全新会话", "callback_data": "cc:fresh"}]]
        for m in sessions:
            label = f"⏯ {m.when} {m.title}"
            kb.append([{
                "text": (label[:59] + "…") if len(label) > 60 else label,
                "callback_data": f"cc:resume:{m.session_id}",
            }])
        if sessions or query:
            kb.append([{"text": "🔎 关键字筛选", "callback_data": "cc:filter"}])
        kb.append([{"text": "✖ 取消", "callback_data": "cc:cancel"}])
        if query:
            head = f"项目：{repo_name}\n② 续聊（筛选「{query}」命中 {len(sessions)} 条）或新建："
        elif sessions:
            head = f"项目：{repo_name}\n② 选「全新会话」，或续聊最近 {len(sessions)} 个会话："
        else:
            head = f"项目：{repo_name}\n② 该项目暂无历史会话，点「全新会话」："
        return head, {"inline_keyboard": kb}

    def _wiz_pick_resume(self, cid: str, session_id: str) -> tuple[Optional[str], Optional[dict]]:
        from app_ado import claude_sessions
        w = self._wizard.get(cid)
        if not w or not w.get("cwd"):
            return "向导已过期，请重新点「新建」。", None
        meta = claude_sessions.get_session(w["cwd"], session_id)
        if not meta:
            return "该会话不存在了。", None
        cwd = w["cwd"]
        repo_name = w.get("repo_name") or cwd
        self._wizard.pop(cid, None)
        return self._create_session(
            cid, cwd, repo_name,
            resume_session_id=session_id, resume_title=meta.title,
        )

    def _wiz_fresh(self, cid: str) -> tuple[Optional[str], Optional[dict]]:
        w = self._wizard.get(cid)
        if not w or not w.get("cwd"):
            return "向导已过期，请重新点「新建」。", None
        cwd = w["cwd"]
        repo_name = w.get("repo_name") or cwd
        self._wizard.pop(cid, None)
        return self._create_session(cid, cwd, repo_name)

    # ------------------------------------------------------------------
    # 向导的文字输入（手输路径）
    # ------------------------------------------------------------------

    def wizard_expects_text(self, chat_id: str) -> bool:
        w = self._wizard.get(str(chat_id))
        return bool(w and w.get("expects") in ("path", "filter"))

    def handle_wizard_text(
        self, chat_id: str, text: str, role: str, group: Optional[dict]
    ) -> tuple[Optional[str], Optional[dict]]:
        import os
        cid = str(chat_id)
        w = self._wizard.get(cid)
        if not w:
            return None, None
        expects = w.get("expects")
        if expects == "filter":
            w.pop("expects", None)
            return self._wiz_session_picker(cid, query=(text or "").strip())
        if expects == "path":
            path = os.path.expanduser((text or "").strip().rstrip("/"))
            if not path or not os.path.isdir(path):
                return f"路径无效或不是目录：{path}\n请重发一个存在的目录绝对路径，或点旧消息的「取消」。", None
            return self._wiz_set_cwd(cid, path, os.path.basename(path) or path)
        return None, None

    # ------------------------------------------------------------------
    # 创建会话
    # ------------------------------------------------------------------

    def _create_session(
        self, cid: str, cwd: str, repo_name: str,
        *, resume_session_id: str = "", resume_title: str = "",
    ) -> tuple[Optional[str], Optional[dict]]:
        """新建/续聊会话。统一走 claude --permission-mode auto，由分类器自动放行/拦截。"""
        if not resolve_claude_executable("claude"):
            return "找不到 claude 可执行文件（检查 PATH）。", None
        sess = self._manager.new(
            model_id="", repo_name=repo_name, cwd=cwd,
            effort="", permission_mode="auto",
            resume_session_id=resume_session_id,
            settings_path="",
        )
        sid = sess.info.sid
        with self._lock:
            self._sid_to_chats.setdefault(sid, set()).add(cid)
            self._chat_focus[cid] = sid
        sess.add_listener(self._on_event)
        if resume_session_id:
            head = (
                f"🟢 已续聊会话 {sid}\n项目：{repo_name}\n"
                f"续聊：{resume_title or resume_session_id[:8]}\n\n直接打字继续。"
            )
        else:
            head = (
                f"🟢 已新建会话 {sid}\n项目：{repo_name}\nauto 模式（Claude 自动判断每步是否放行）\n\n"
                f"直接打字给它发提示词。"
            )
        return head, self._session_kb(sid)

    def _session_kb(self, sid: str) -> dict:
        return {"inline_keyboard": [[
            {"text": "📝 发提示词", "callback_data": f"cc:prompt:{sid}"},
            {"text": "⏹ 停止本轮", "callback_data": f"cc:stop:{sid}"},
            {"text": "🗑 结束", "callback_data": f"cc:kill:{sid}"},
        ]]}

    # ------------------------------------------------------------------
    # 文字消息路由（发提示词给聚焦会话）
    # ------------------------------------------------------------------

    def should_consume_text(self, chat_id: str, reply_to_msg_id: Optional[int]) -> bool:
        sid = self._chat_focus.get(str(chat_id))
        sess = self._manager.get(sid) if sid else None
        return bool(sess and sess.info.status != "exited")

    def handle_text(
        self, *, text: str, chat_id: str, reply_to_msg_id: Optional[int],
        role: str, group: Optional[dict],
    ) -> tuple[bool, str]:
        if not self.can_dev(role, group, "dev_message"):
            return False, "无权限：dev_message"
        sid = self._chat_focus.get(str(chat_id))
        sess = self._manager.get(sid) if sid else None
        if not sess:
            return False, "没有聚焦的会话。点 /cc 新建或选择。"
        if sess.info.status == "exited":
            return False, f"会话 {sid} 已结束。"
        status, pos = sess.submit(text)
        if status == "sent":
            return True, ""  # 静默，等它出回复
        if status == "queued":
            return True, f"🕓 已排队（前面还有 {pos - 1} 条），当前回合结束后自动执行。"
        return False, "写入失败（会话可能已结束）。"

    # ------------------------------------------------------------------
    # 异步：会话事件 → TG 消息
    # ------------------------------------------------------------------

    def _on_event(self, sess: HeadlessSession, ev: HeadlessEvent) -> None:
        sid = sess.info.sid
        text: Optional[str] = None
        kb: Optional[dict] = None
        markdown = False

        if ev.kind == "assistant":
            text = ev.text
            markdown = True
        elif ev.kind == "tool_use":
            summ = _tool_summary(ev.tool_name, ev.tool_input)
            text = f"🔧 {ev.tool_name}" + (f"\n`{summ}`" if summ else "")
            markdown = True
        elif ev.kind == "tool_result":
            if ev.is_error:
                text = f"⚠️ 工具失败：{_short(ev.text, 500)}"
        elif ev.kind == "result":
            if ev.is_error:
                text = f"❌ 出错（{ev.subtype or 'error'}）"
                kb = self._session_kb(sid)
            else:
                text = "✓ 完成"
                kb = self._session_kb(sid)
        elif ev.kind == "error":
            t = _short(ev.text, 500)
            if t:
                text = f"⚠️ {t}"
        elif ev.kind == "exit":
            text = f"🔚 会话 {sid} 已结束（exit={ev.exit_code}）"

        if not text:
            return
        self._push(sid, text, kb=kb, markdown=markdown)

    def _push(self, sid: str, text: str, *, kb: Optional[dict] = None, markdown: bool = False) -> None:
        token = self._bot_token_fn()
        if not token:
            return
        with self._lock:
            chats = list(self._sid_to_chats.get(sid, set()))
        if not chats:
            owner = self._owner_chat_id_fn()
            if owner:
                chats = [str(owner)]
                with self._lock:
                    self._sid_to_chats.setdefault(sid, set()).add(str(owner))
        for chat_id in chats:
            self._send_long(token, chat_id, text, kb=kb, markdown=markdown)

    def _send_long(
        self, token: str, chat_id: str, text: str, *, kb: Optional[dict], markdown: bool
    ) -> None:
        chunks = _chunk(text, _TG_MAX_LEN)
        for i, chunk in enumerate(chunks):
            last = i == len(chunks) - 1
            self._tg_send(token, chat_id, chunk, kb=(kb if last else None), markdown=markdown)

    @staticmethod
    def _tg_send(token: str, chat_id: str, text: str, *, kb: Optional[dict], markdown: bool) -> None:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload: dict = {
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": True,
        }
        if markdown:
            payload["parse_mode"] = "Markdown"
        if kb is not None:
            payload["reply_markup"] = kb
        try:
            with httpx.Client(timeout=httpx.Timeout(_TG_HTTP_TIMEOUT, connect=5.0)) as c:
                r = c.post(url, json=payload)
                if r.status_code != 200 and "parse_mode" in payload:
                    # markdown 解析失败 → 退回纯文本
                    payload.pop("parse_mode", None)
                    c.post(url, json=payload)
        except Exception:
            pass

def _chunk(text: str, n: int) -> list[str]:
    if len(text) <= n:
        return [text]
    out: list[str] = []
    buf = ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > n:
            if buf:
                out.append(buf)
            if len(line) > n:
                # 单行超长：硬切
                for j in range(0, len(line), n):
                    out.append(line[j:j + n])
                buf = ""
            else:
                buf = line
        else:
            buf = (buf + "\n" + line) if buf else line
    if buf:
        out.append(buf)
    return out
