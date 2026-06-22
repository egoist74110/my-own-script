"""Headless Codex 会话 ↔ Telegram 桥。

接口对齐 AiHeadlessTgBridge（Claude 桥），所以可以直接当作 TelegramController(mode="ai")
的 headless_bridge 用，复用同一套 "cc:" 回调协议、ACL、文字投递逻辑——**Codex 专属机器人**
和 Claude 专属机器人各跑各的 controller，"cc:" 命名空间不会串。

但 Codex 的规则和 Claude 不同，所以这里有两处刻意不一样：
  1) 新建会话向导多了 **模型 / 思考强度 / 审计(沙箱)** 三步——这正是 Codex 的几个关键旋钮，
     Claude 桥是写死 auto 的。
  2) **没有逐条工具审批**：codex exec 是非交互的，审计靠首轮选的沙箱档位定调，不像 Claude
     有 PreToolUse 钩子。所以这里没有审批落盘那套设施。

会话产生的异步输出由本桥用自己的 token 直接推送；同步 UI 由 handle_* 返回 (text, markup)
交给 controller 发送。
"""

from __future__ import annotations

import os
import threading
from typing import Callable, Optional

from app_ado.ai_headless_session import HeadlessEvent
from app_ado.ai_headless_tg_bridge import AiHeadlessTgBridge, _chunk, _short
from app_ado.codex_headless_session import (
    AUDIT_CHOICES,
    EFFORT_CHOICES,
    CodexSession,
    CodexSessionManager,
    resolve_codex_executable,
)


# 新建向导里给用户选的模型预设（本机 CLI 0.123.0 + ChatGPT 账号实测：gpt-5.4-mini 可用；
# gpt-5 / gpt-5-codex 被拒；gpt-5.5 需更新的 CLI）。留空 key="" = 不传 -m，走 codex 配置默认。
_MODEL_PRESETS: list[tuple[str, str]] = [
    ("", "默认（codex 配置）"),
    ("gpt-5.5", "gpt-5.5"),
    ("gpt-5.4-mini", "gpt-5.4-mini"),
    ("gpt-5-codex", "gpt-5-codex"),
]

# 审计/沙箱档位的中文说明（key 对齐 codex_headless_session.AUDIT_CHOICES）
_AUDIT_LABELS: dict[str, str] = {
    "read-only": "🔒 只读（不能改文件，最安全）",
    "workspace-write": "✍️ 自动改文件（可改工作区·推荐）",
    "danger-full-access": "⚠️ 完全放开（无沙箱，危险）",
}

_EFFORT_LABELS: dict[str, str] = {
    "minimal": "minimal（最快）",
    "low": "low",
    "medium": "medium（默认）",
    "high": "high（最强）",
}


def _codex_tool_summary(tool_name: str, inp: dict) -> str:
    inp = inp or {}
    if tool_name == "shell":
        return _short(inp.get("command") or "", 200)
    if tool_name == "apply_patch":
        return _short(inp.get("files") or "", 200)
    if tool_name == "web_search":
        return _short(inp.get("query") or "", 160)
    if tool_name == "todo":
        todos = inp.get("todos") or []
        return f"{len(todos)} 项待办"
    if tool_name.startswith("mcp:"):
        return _short(str(inp), 160)
    return ""


class CodexHeadlessTgBridge:
    def __init__(
        self,
        *,
        manager: CodexSessionManager,
        bot_token_fn: Callable[[], Optional[str]],
        owner_chat_id_fn: Callable[[], Optional[str]],
        command_fn: Optional[Callable[[], str]] = None,
    ) -> None:
        self._manager = manager
        self._bot_token_fn = bot_token_fn
        self._owner_chat_id_fn = owner_chat_id_fn
        # codex 可执行命令来源（默认 "codex"；可由 AI 配置里的 profile.command 覆盖）
        self._command_fn = command_fn or (lambda: "codex")

        self._lock = threading.Lock()
        self._sid_to_chats: dict[str, set[str]] = {}
        self._chat_focus: dict[str, str] = {}
        self._wizard: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # 生命周期（codex 无审批落盘线程，start/shutdown 仅占位对齐接口）
    # ------------------------------------------------------------------

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def shutdown(self) -> None:
        self._manager.shutdown()

    # ------------------------------------------------------------------
    # 权限（沿用 owner/group ACL，和 Claude 桥一致）
    # ------------------------------------------------------------------

    @staticmethod
    def can_dev(role: str, group: Optional[dict], action: str) -> bool:
        return AiHeadlessTgBridge.can_dev(role, group, action)

    # ------------------------------------------------------------------
    # 主菜单
    # ------------------------------------------------------------------

    def handle_menu(self, chat_id: str, role: str, group: Optional[dict]) -> tuple[Optional[str], Optional[dict]]:
        if not self.can_dev(role, group, "dev_status"):
            return "无权限：AI 开发", None
        infos = self._manager.list()
        focus = self._chat_focus.get(str(chat_id))
        kb: list[list[dict]] = []
        status_zh = {"idle": "空闲", "busy": "运行中", "exited": "已结束"}
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
        kb.append([{"text": "➕ 新建 Codex 会话", "callback_data": "cc:new"}])
        head = "🤖 Codex 会话" + (f"\n共 {len(infos)} 个会话。" if infos else "\n暂无会话，点下面新建。")
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
            w = self._wizard.setdefault(cid, {})
            w["expects"] = "path"
            w["step"] = "repo_manual"
            return (
                "✍️ 回复本条消息，发送项目目录的绝对路径（例如 /Users/you/proj）：",
                {"force_reply": True, "input_field_placeholder": "/Users/you/proj", "selective": True},
            )

        if rest.startswith("model:"):
            return self._wiz_pick_model(cid, rest.split(":", 1)[1])

        if rest.startswith("effort:"):
            return self._wiz_pick_effort(cid, rest.split(":", 1)[1])

        if rest.startswith("audit:"):
            return self._wiz_pick_audit(cid, rest.split(":", 1)[1])

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
            return "⏹ 已请求停止本轮（杀掉当前 codex 进程，下条会自动续聊）。", None

        return None, None

    # ------------------------------------------------------------------
    # 向导各步：① 选项目 → ② 选模型 → ③ 选思考强度 → ④ 选审计(沙箱) → 建会话
    # ------------------------------------------------------------------

    def _wiz_start(self, cid: str) -> tuple[str, dict]:
        from app_ado.store import load_ui_settings
        s = load_ui_settings()
        repos = list(getattr(s, "local_repos", []) or [])
        seen: set[str] = set()
        options: list[tuple[str, str]] = []  # (abspath, name)
        for r in repos:
            ap = os.path.abspath(os.path.expanduser(r.path or ""))
            if not ap or ap in seen:
                continue
            seen.add(ap)
            options.append((ap, r.name))
        self._wizard[cid] = {"step": "pick_repo", "proj_options": options}
        kb: list[list[dict]] = []
        for i, (ap, name) in enumerate(options):
            kb.append([{"text": f"📁 {name}", "callback_data": f"cc:proj:{i}"}])
        kb.append([{"text": "✍️ 手输路径", "callback_data": "cc:repo_manual"}])
        kb.append([{"text": "✖ 取消", "callback_data": "cc:cancel"}])
        head = ("① 选择项目（📁 已配置仓库）：" if options
                else "① 点「手输路径」输入项目目录绝对路径：")
        return head, {"inline_keyboard": kb}

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
        ap, name = opts[idx]
        return self._wiz_set_cwd(cid, ap, name)

    def _wiz_set_cwd(self, cid: str, cwd: str, repo_name: str) -> tuple[Optional[str], Optional[dict]]:
        w = self._wizard.setdefault(cid, {})
        w["cwd"] = cwd
        w["repo_name"] = repo_name
        w.pop("expects", None)
        return self._wiz_model_picker(cid)

    def _wiz_model_picker(self, cid: str) -> tuple[Optional[str], Optional[dict]]:
        w = self._wizard.setdefault(cid, {})
        w["step"] = "pick_model"
        kb: list[list[dict]] = []
        for i, (key, label) in enumerate(_MODEL_PRESETS):
            kb.append([{"text": label, "callback_data": f"cc:model:{i}"}])
        kb.append([{"text": "✖ 取消", "callback_data": "cc:cancel"}])
        repo = w.get("repo_name") or w.get("cwd") or ""
        head = (f"项目：{repo}\n② 选模型（gpt-5.4-mini 本机实测可用；gpt-5.5 需较新 CLI）：")
        return head, {"inline_keyboard": kb}

    def _wiz_pick_model(self, cid: str, idx_s: str) -> tuple[Optional[str], Optional[dict]]:
        w = self._wizard.get(cid)
        if not w or not w.get("cwd"):
            return "向导已过期，请重新点「新建」。", None
        try:
            idx = int(idx_s)
        except ValueError:
            return "无效选择。", None
        if idx < 0 or idx >= len(_MODEL_PRESETS):
            return "无效选择。", None
        w["model"] = _MODEL_PRESETS[idx][0]
        return self._wiz_effort_picker(cid)

    def _wiz_effort_picker(self, cid: str) -> tuple[Optional[str], Optional[dict]]:
        w = self._wizard.setdefault(cid, {})
        w["step"] = "pick_effort"
        kb: list[list[dict]] = []
        for eff in EFFORT_CHOICES:
            kb.append([{"text": _EFFORT_LABELS.get(eff, eff), "callback_data": f"cc:effort:{eff}"}])
        kb.append([{"text": "✖ 取消", "callback_data": "cc:cancel"}])
        return "③ 选思考强度（reasoning effort）：", {"inline_keyboard": kb}

    def _wiz_pick_effort(self, cid: str, eff: str) -> tuple[Optional[str], Optional[dict]]:
        w = self._wizard.get(cid)
        if not w or not w.get("cwd"):
            return "向导已过期，请重新点「新建」。", None
        if eff not in EFFORT_CHOICES:
            return "无效选择。", None
        w["effort"] = eff
        return self._wiz_audit_picker(cid)

    def _wiz_audit_picker(self, cid: str) -> tuple[Optional[str], Optional[dict]]:
        w = self._wizard.setdefault(cid, {})
        w["step"] = "pick_audit"
        kb: list[list[dict]] = []
        for key in AUDIT_CHOICES:
            kb.append([{"text": _AUDIT_LABELS.get(key, key), "callback_data": f"cc:audit:{key}"}])
        kb.append([{"text": "✖ 取消", "callback_data": "cc:cancel"}])
        head = (
            "④ 选审计/沙箱档位（Codex 非交互，没有逐条审批，靠这里定调）：\n"
            "· 只读：能看不能改\n· 自动改文件：可改工作区，失败才升权（推荐）\n· 完全放开：无沙箱，谨慎"
        )
        return head, {"inline_keyboard": kb}

    def _wiz_pick_audit(self, cid: str, key: str) -> tuple[Optional[str], Optional[dict]]:
        w = self._wizard.get(cid)
        if not w or not w.get("cwd"):
            return "向导已过期，请重新点「新建」。", None
        if key not in AUDIT_CHOICES:
            return "无效选择。", None
        cwd = w["cwd"]
        repo_name = w.get("repo_name") or cwd
        model = w.get("model") or ""
        effort = w.get("effort") or ""
        self._wizard.pop(cid, None)
        return self._create_session(cid, cwd, repo_name, model=model, effort=effort, audit=key)

    # ------------------------------------------------------------------
    # 向导文字输入（手输路径）
    # ------------------------------------------------------------------

    def wizard_expects_text(self, chat_id: str) -> bool:
        w = self._wizard.get(str(chat_id))
        return bool(w and w.get("expects") == "path")

    def handle_wizard_text(
        self, chat_id: str, text: str, role: str, group: Optional[dict]
    ) -> tuple[Optional[str], Optional[dict]]:
        cid = str(chat_id)
        w = self._wizard.get(cid)
        if not w:
            return None, None
        if w.get("expects") == "path":
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
        *, model: str = "", effort: str = "", audit: str = "workspace-write",
        initial_prompt: str = "",
    ) -> tuple[Optional[str], Optional[dict]]:
        if not resolve_codex_executable(self._command_fn()):
            return "找不到 codex 可执行文件（检查 PATH）。", None
        sess = self._manager.new(
            repo_name=repo_name, cwd=cwd, model_id=model, effort=effort,
            audit=audit, command=self._command_fn(),
        )
        sid = sess.info.sid
        with self._lock:
            self._sid_to_chats.setdefault(sid, set()).add(cid)
            self._chat_focus[cid] = sid
        sess.add_listener(self._on_event)
        if initial_prompt:
            sess.submit(initial_prompt)
        model_zh = model or "codex 默认"
        audit_zh = {"read-only": "只读", "workspace-write": "自动改文件", "danger-full-access": "完全放开"}.get(audit, audit)
        head = (
            f"🟢 已新建 Codex 会话 {sid}\n项目：{repo_name}\n"
            f"模型：{model_zh} · 强度：{effort or 'medium'} · 审计：{audit_zh}"
        )
        if initial_prompt:
            head += "\n\n📝 已自动发送提示词，等待回复…"
        else:
            head += "\n\n直接打字给它发提示词（第一条会真正起一轮 codex）。"
        return head, self._session_kb(sid)

    def start_session_with_prompt(
        self, chat_id: str, *, cwd: str, repo_name: str, prompt: str,
        model: str = "", effort: str = "", audit: str = "workspace-write",
    ) -> tuple[Optional[str], Optional[dict]]:
        """对外入口（如工单 MCP 分析按钮）：创建会话并自动投第一轮提示词。"""
        return self._create_session(
            str(chat_id), cwd, repo_name,
            model=model, effort=effort, audit=audit, initial_prompt=prompt or "",
        )

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
            return True, ""
        if status == "queued":
            return True, f"🕓 已排队（前面还有 {pos - 1} 条），当前回合结束后自动执行。"
        return False, "写入失败（会话可能已结束）。"

    # ------------------------------------------------------------------
    # 异步：会话事件 → TG 消息
    # ------------------------------------------------------------------

    def _on_event(self, sess: CodexSession, ev: HeadlessEvent) -> None:
        sid = sess.info.sid
        text: Optional[str] = None
        kb: Optional[dict] = None
        markdown = False

        if ev.kind == "assistant":
            text = ev.text
            markdown = True
        elif ev.kind == "thinking":
            t = _short(ev.text, 600)
            if t:
                text = f"💭 {t}"
        elif ev.kind == "tool_use":
            summ = _codex_tool_summary(ev.tool_name, ev.tool_input)
            text = f"🔧 {ev.tool_name}" + (f"\n`{summ}`" if summ else "")
            markdown = True
        elif ev.kind == "tool_result":
            if ev.is_error:
                text = f"⚠️ 命令失败：{_short(ev.text, 500)}"
        elif ev.kind == "result":
            if ev.is_error:
                text = f"❌ 出错：{_short(ev.text, 600) or ev.subtype or 'error'}"
                kb = self._session_kb(sid)
            else:
                text = "✓ 完成"
                kb = self._session_kb(sid)
        elif ev.kind == "error":
            t = _short(ev.text, 600)
            if t:
                text = f"⚠️ {t}"
        elif ev.kind == "exit":
            text = f"🔚 会话 {sid} 已结束"

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
            chunks = _chunk(text, 3900)
            for i, chunk in enumerate(chunks):
                last = i == len(chunks) - 1
                AiHeadlessTgBridge._tg_send(
                    token, chat_id, chunk, kb=(kb if last else None), markdown=markdown
                )
