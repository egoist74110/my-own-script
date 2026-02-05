from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QWidget, QFormLayout
from qfluentwidgets import CardWidget, ComboBox, PushButton

from app_ado.ui.task_card import TaskCard

from app_ado.store import load_task_settings, save_task_settings
from app_ado.ui.confirm import show_confirm_dialog
from app_ado.ui.dialogs import show_error_dialog
from app_ado.ui.run_log_dialog import RunLogDialog
from app_ado.ui.task_flow_dialog import FlowTaskConfigDialog
from ok.gui.widget.Tab import Tab


class TasksTab(Tab):
    """Task page placeholder.

    Next step: implement FlowTask config + execution:
    - repo/branches dropdown discovery
    - merge/push
    - build trigger + monitor
    - release trigger + monitor (multi-stage)
    - logs
    """

    icon = None
    name = "任务"

    def __init__(self):
        super().__init__()
        self._stop_event = None
        self._running: bool = False
        self._running_task: str = ""

        # Task 1: sync+merge+build+release
        self.flow_card = TaskCard(
            title="同步/合并 + 构建 + 发布",
            subtitle="把源分支合并到目标分支，然后构建并发布",
        )
        self.flow_card.config_clicked.connect(lambda: self._edit("sync_merge_build_release"))
        self.flow_card.run_clicked.connect(lambda: self._run("sync_merge_build_release", self.flow_card))
        self.flow_card.stop_clicked.connect(self._stop)
        self.add_widget(self.flow_card)

        # Task 2: sync+build+release (no merge)
        self.sync_card = TaskCard(
            title="同步 + 构建 + 发布",
            subtitle="同步目标分支到最新，然后构建并发布（不做分支合并）",
        )
        self.sync_card.config_clicked.connect(lambda: self._edit("sync_build_release"))
        self.sync_card.run_clicked.connect(lambda: self._run("sync_build_release", self.sync_card))
        self.sync_card.stop_clicked.connect(self._stop)
        self.add_widget(self.sync_card)

    def _clear_run_log(self, card: TaskCard) -> None:
        card.clear_log()

    def _append_run_log(self, card: TaskCard, text: str) -> None:
        card.append_log(text)

    def _edit(self, flow_id: str) -> None:
        ts = load_task_settings()
        flow = next((f for f in ts.flows if f.id == flow_id), None)
        if flow is None:
            from app_ado.models import FlowTaskConfig

            flow = FlowTaskConfig(id=flow_id)
            ts.flows.append(flow)

        from app_ado.store import load_ui_settings

        settings = load_ui_settings()
        dlg = FlowTaskConfigDialog(self.window(), settings=settings, flow=flow)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        updated = dlg.result_config()
        if not updated:
            return
        ts.flows = [updated if f.id == updated.id else f for f in ts.flows]
        save_task_settings(ts)

    def run_task(self, flow_id: str) -> None:
        card = self.flow_card if flow_id == "sync_merge_build_release" else self.sync_card
        QtCore.QTimer.singleShot(0, lambda: self._run(flow_id, card))

    def stop_task(self) -> None:
        QtCore.QTimer.singleShot(0, self._stop)

    def status_text(self) -> str:
        if self._running:
            return f"运行中：{self._running_task}"
        return "空闲"

    def _run(self, flow_id: str, card: TaskCard) -> None:
        """Run in a background Python thread to keep UI responsive."""
        ts = load_task_settings()
        flow = next((f for f in ts.flows if f.id == flow_id), None)
        if not flow:
            self._edit(flow_id)
            ts = load_task_settings()
            flow = next((f for f in ts.flows if f.id == flow_id), None)
        if not flow:
            return

        # basic config validation (UI thread)
        missing: list[str] = []
        if not flow.local_repo_path:
            missing.append("- 本地仓库路径")
        if flow_id == "sync_merge_build_release" and not flow.source_branch:
            missing.append("- 源分支")
        if not flow.target_branch:
            missing.append("- 目标分支")
        # multi targets
        targets = list(getattr(flow, "targets", []) or [])
        if not targets and (flow.build_id or flow.release_id or (flow.release_stage_ids or [])):
            # back-compat single target
            from app_ado.models import DeployTarget

            targets = [
                DeployTarget(
                    name="目标1",
                    enabled=True,
                    build_kind=flow.build_kind,
                    build_id=flow.build_id,
                    build_name=flow.build_name,
                    release_id=flow.release_id,
                    release_name=flow.release_name,
                    release_stage_ids=list(flow.release_stage_ids or []),
                    release_stage_names=list(flow.release_stage_names or []),
                )
            ]

        if not targets:
            missing.append("- 发布目标（至少新增一个：构建+发布+阶段）")
        if missing:
            show_error_dialog(self.window(), "配置不完整", f"请先在【配置】中补齐（{flow_id}）：\n" + "\n".join(missing))
            return

        local_path = flow.local_repo_path

        ok = show_confirm_dialog(
            self.window(),
            "确认执行任务？",
            "将执行以下操作：\n"
            + (
                f"1) fetch origin {flow.source_branch} / {flow.target_branch}\n"
                f"2) 更新本地分支（ff-only）\n"
                f"3) merge origin/{flow.source_branch} -> {flow.target_branch}\n"
                f"4) push origin {flow.target_branch}\n"
                if flow_id == "sync_merge_build_release"
                else f"1) fetch origin {flow.target_branch}\n2) 更新本地分支（ff-only）\n"
            )
            + f"触发构建（目标分支：{flow.target_branch}）并等待完成\n"
            + f"触发发布并监控所选阶段\n\nrepo_path={local_path}",
        )
        if not ok:
            return

        import queue
        import threading
        import subprocess
        import shlex

        # stop support
        self._stop_event = threading.Event()
        self._running = True
        self._running_task = flow_id

        q: queue.Queue[tuple[str, str]] = queue.Queue()
        # ('log'|'error'|'done', payload)

        def ui_call(fn):
            QtCore.QTimer.singleShot(0, fn)

        def emit_log(text: str) -> None:
            q.put(("log", text))

        def should_stop() -> bool:
            return bool(self._stop_event and self._stop_event.is_set())

        def notify_telegram(text: str) -> None:
            try:
                from app_ado.store import load_ui_settings
                from app_ado.secrets import get_telegram_token
                from app_ado.notifier_telegram import send_telegram_message

                s = load_ui_settings()
                token = get_telegram_token()
                if not s.telegram_chat_id or not token:
                    return
                send_telegram_message(bot_token=token, chat_id=s.telegram_chat_id, text=text)
            except Exception:
                # never break the flow because of notification
                return

        def emit_error(title: str, details: str) -> None:
            # final result notification (fail)
            notify_telegram(
                "❌ 任务失败\n"
                f"{flow.repo_name or ''} {flow.source_branch}->{flow.target_branch}\n"
                f"{title}\n{details}"
            )
            q.put(("error", title + "\n" + details))

        def worker() -> None:
            try:
                emit_log("运行：合并并推送 + 构建")
                emit_log(f"repo_path={local_path}")
                emit_log(f"source={flow.source_branch} target={flow.target_branch}")

                notify_telegram(
                    "🚀 开始执行任务\n"
                    f"{flow.repo_name or ''} {flow.source_branch}->{flow.target_branch}\n"
                    f"targets={len(targets)}"
                )

                def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
                    line = "$ " + " ".join(shlex.quote(x) for x in cmd)
                    emit_log(line)
                    cp = subprocess.run(cmd, cwd=local_path, capture_output=True, text=True)
                    if cp.stdout:
                        emit_log(cp.stdout.strip())
                    if cp.stderr:
                        emit_log(cp.stderr.strip())
                    return cp

                if should_stop():
                    emit_log("已停止：用户取消")
                    return

                # verify git repo
                cp = run_cmd(["git", "rev-parse", "--is-inside-work-tree"])
                if cp.returncode != 0 or "true" not in (cp.stdout or "").lower():
                    emit_error("错误", f"不是有效的 git 仓库：{local_path}")
                    return

                # workspace must be clean
                cp = run_cmd(["git", "status", "--porcelain"])
                if cp.returncode != 0:
                    emit_error("错误", "git status 失败")
                    return
                dirty = (cp.stdout or "").strip()
                if dirty:
                    emit_error("工作区未清理", "检测到未提交改动，请先处理后再运行：\n\n" + dirty)
                    return

                # fetch + update branches
                if flow_id == "sync_merge_build_release":
                    cp = run_cmd(["git", "fetch", "--prune", "origin", flow.source_branch, flow.target_branch])
                    if cp.returncode != 0:
                        emit_error("错误", "fetch 失败")
                        return

                    for br in [flow.source_branch, flow.target_branch]:
                        if should_stop():
                            emit_log("已停止：用户取消")
                            return
                        cp = run_cmd(["git", "checkout", br])
                        if cp.returncode != 0:
                            emit_error("错误", f"checkout 失败: {br}")
                            return
                        cp = run_cmd(["git", "pull", "--ff-only"])
                        if cp.returncode != 0:
                            emit_error("错误", f"pull 失败: {br}")
                            return

                    # merge source into target
                    cp = run_cmd(["git", "checkout", flow.target_branch])
                    if cp.returncode != 0:
                        emit_error("错误", f"checkout 失败: {flow.target_branch}")
                        return

                    cp = run_cmd(["git", "merge", f"origin/{flow.source_branch}"])
                    if cp.returncode != 0:
                        cp2 = run_cmd(["git", "diff", "--name-only", "--diff-filter=U"])
                        conflicts = (cp2.stdout or "").strip()
                        emit_error(
                            "合并失败（可能存在冲突）",
                            "merge 失败。请手动处理冲突后再运行。\n\n冲突文件：\n" + (conflicts or "(未检测到冲突文件列表)"),
                        )
                        return

                    cp = run_cmd(["git", "push", "origin", flow.target_branch])
                    if cp.returncode != 0:
                        emit_error("推送失败", f"push 失败，请检查权限/分支保护。\n\nbranch={flow.target_branch}")
                        return

                    cp = run_cmd(["git", "rev-parse", "HEAD"])
                    head = (cp.stdout or "").strip() if cp.returncode == 0 else ""
                    emit_log(
                        f"✅ 合并并推送完成：{flow.source_branch} -> {flow.target_branch}"
                        + (f"\nHEAD={head}" if head else "")
                    )
                else:
                    cp = run_cmd(["git", "fetch", "--prune", "origin", flow.target_branch])
                    if cp.returncode != 0:
                        emit_error("错误", "fetch 失败")
                        return

                    cp = run_cmd(["git", "checkout", flow.target_branch])
                    if cp.returncode != 0:
                        emit_error("错误", f"checkout 失败: {flow.target_branch}")
                        return

                    cp = run_cmd(["git", "pull", "--ff-only"])
                    if cp.returncode != 0:
                        emit_error("错误", f"pull 失败: {flow.target_branch}")
                        return

                    cp = run_cmd(["git", "rev-parse", "HEAD"])
                    head = (cp.stdout or "").strip() if cp.returncode == 0 else ""
                    emit_log(f"✅ 同步完成：{flow.target_branch}" + (f"\nHEAD={head}" if head else ""))
                # notification policy: only start + final result

                if should_stop():
                    emit_log("已停止：用户取消")
                    return

                # ---- Build+Release for each target (serial) ----
                from app_ado.store import load_ui_settings
                from app_ado.secrets import get_pat
                from app_ado.ado_build_http import (
                    get_pipeline_run,
                    trigger_build_definition,
                    trigger_pipeline_run,
                    wait_build,
                    wait_pipeline,
                )

                settings = load_ui_settings()
                proj = next((p for p in settings.projects if p.id == flow.project_id), None)
                if not proj:
                    emit_error("错误", "找不到项目配置（project_id）")
                    return
                lib = next((l for l in settings.libraries if l.id == proj.library_id), None)
                if not lib:
                    emit_error("错误", "找不到代码库配置（library_id）")
                    return
                pat = get_pat(lib.id)
                if not pat:
                    emit_error("错误", "该代码库未保存 PAT")
                    return

                # ---- Build+Release for each target (serial) ----
                from app_ado.ado_release_http import create_release_from_build
                from app_ado.ado_release_http import extract_envs, get_release, start_release_environment
                import time

                branch = flow.target_branch

                for ti, tgt in enumerate(targets, start=1):
                    if not getattr(tgt, "enabled", True):
                        emit_log(f"\n--- Target[{ti}] {tgt.name}: skipped (disabled) ---")
                        continue

                    if should_stop():
                        emit_log("已停止：用户取消")
                        return

                    emit_log(f"\n=== Target[{ti}] {tgt.name} ===")
                    emit_log(f"--- Build: kind={tgt.build_kind} id={tgt.build_id} branch={branch} ---")

                    build_run_id: str | None = None

                    if tgt.build_kind == "pipeline":
                        pr = trigger_pipeline_run(lib.base_url, proj.collection, proj.project, tgt.build_id, branch=branch, pat=pat)
                        build_run_id = pr.run_id
                        emit_log(f"已触发 Pipeline：run_id={pr.run_id} state={pr.state} url={pr.url or ''}")
                        deadline = time.time() + 30 * 60
                        pr2 = None
                        while time.time() < deadline:
                            if should_stop():
                                emit_log("已停止：用户取消（构建已触发，停止后不会回滚）")
                                return
                            pr_cur = get_pipeline_run(lib.base_url, proj.collection, proj.project, tgt.build_id, pr.run_id, pat=pat)
                            if (pr_cur.state or "").lower() == "completed":
                                pr2 = pr_cur
                                break
                            time.sleep(4.0)
                        if pr2 is None:
                            emit_error("构建超时", f"Pipeline run timeout (run_id={pr.run_id})")
                            return
                        emit_log(f"Pipeline 完成：state={pr2.state} result={pr2.result} url={pr2.url or ''}")
                        if (pr2.result or "").lower() not in ("succeeded", "success"):
                            emit_error("构建失败", f"Pipeline result={pr2.result}\n{pr2.url or ''}")
                            return
                    else:
                        brn = trigger_build_definition(lib.base_url, proj.collection, proj.project, tgt.build_id, branch=branch, pat=pat)
                        build_run_id = brn.build_id
                        emit_log(f"已触发 Build：build_id={brn.build_id} status={brn.status} url={brn.url or ''}")
                        br2 = wait_build(lib.base_url, proj.collection, proj.project, brn.build_id, pat=pat, timeout_min=30)
                        emit_log(f"Build 完成：status={br2.status} result={br2.result} url={br2.url or ''}")
                        if (br2.result or "").lower() not in ("succeeded", "success", "partiallysucceeded"):
                            emit_error("构建失败", f"Build result={br2.result}\n{br2.url or ''}")
                            return

                    emit_log("✅ 构建成功，开始触发 Release ...")

                    if not build_run_id:
                        emit_error("错误", "未获得 build_id/run_id，无法创建 Release")
                        return

                    stage_ids = list(getattr(tgt, "release_stage_ids", []) or [])
                    emit_log(f"--- Release: def_id={tgt.release_id} build_id={build_run_id} stages={','.join(stage_ids)} ---")

                    try:
                        rel = create_release_from_build(
                            lib.base_url,
                            proj.collection,
                            proj.project,
                            tgt.release_id,
                            build_id=build_run_id,
                            pat=pat,
                            api_version="6.0",
                        )
                    except Exception:
                        rel = create_release_from_build(
                            lib.base_url,
                            proj.collection,
                            proj.project,
                            tgt.release_id,
                            build_id=build_run_id,
                            pat=pat,
                            api_version="7.0",
                        )

                    emit_log(f"已创建 Release：id={rel.id} name={rel.name or ''} url={rel.url or ''}")

                    def fetch_envs() -> list:
                        try:
                            data = get_release(lib.base_url, proj.collection, proj.project, rel.id, pat=pat, api_version="6.0")
                        except Exception:
                            data = get_release(lib.base_url, proj.collection, proj.project, rel.id, pat=pat, api_version="7.0")
                        return extract_envs(data)

                    def is_done(status: str) -> bool:
                        s = (status or "").lower()
                        return s in {"succeeded", "rejected", "canceled", "failed"}

                    want_ids = set(stage_ids)
                    want_names = set(getattr(tgt, "release_stage_names", []) or [])
                    deadline = time.time() + 60 * 60
                    last_line = ""

                    def select_envs(envs):
                        by_def_id = [e for e in envs if (e.definition_environment_id or "") in want_ids]
                        if by_def_id:
                            return by_def_id, "definitionEnvironmentId"
                        by_name = [e for e in envs if e.name in want_names]
                        if by_name:
                            return by_name, "name"
                        return [], "none"

                    while time.time() < deadline:
                        if should_stop():
                            emit_log("已停止：用户取消（发布已触发，停止后不会回滚）")
                            return

                        envs = fetch_envs()
                        selected, mode = select_envs(envs)
                        parts = [f"{e.name}(defEnvId={e.definition_environment_id}, envId={e.id})={e.status}" for e in selected]
                        line = f"监控[{tgt.name}](mode={mode})：" + " | ".join(parts) if parts else f"监控[{tgt.name}]：等待阶段进入 release"
                        if line != last_line:
                            emit_log(line)
                            last_line = line

                        for e in selected:
                            if (e.status or "").lower() == "notstarted":
                                emit_log(f"触发部署：{e.name} (envId={e.id}, defEnvId={e.definition_environment_id})")
                                start_release_environment(lib.base_url, proj.collection, proj.project, rel.id, e.id, pat=pat)

                        if selected and all(is_done(e.status) for e in selected):
                            failed = [e for e in selected if (e.status or "").lower() not in ("succeeded",)]
                            if failed:
                                msg = "Release 完成但存在失败阶段：\n" + "\n".join([f"- {e.name} ({e.id}) status={e.status}" for e in failed])
                                emit_error("发布失败", msg + (f"\n\n{rel.url or ''}"))
                                return
                            emit_log(f"✅ Target {tgt.name} Release 成功")
                            break

                        for _ in range(10):
                            if should_stop():
                                emit_log("已停止：用户取消（发布已触发，停止后不会回滚）")
                                return
                            time.sleep(1.0)

                    else:
                        emit_error("发布超时", f"Release 监控超时（60min）：{rel.url or ''}")
                        return

                # all targets done
                last_url = rel.url if 'rel' in locals() and rel else ""
                notify_telegram(
                    "✅ 任务成功\n"
                    f"{flow.repo_name or ''} {flow.source_branch}->{flow.target_branch}\n"
                    f"targets={len(targets)}\n"
                    f"{last_url}"
                )
                return

                def fetch_envs() -> list:
                    # prefer 6.0, fallback 7.0
                    try:
                        data = get_release(
                            lib.base_url,
                            proj.collection,
                            proj.project,
                            rel.id,
                            pat=pat,
                            api_version="6.0",
                        )
                    except Exception:
                        data = get_release(
                            lib.base_url,
                            proj.collection,
                            proj.project,
                            rel.id,
                            pat=pat,
                            api_version="7.0",
                        )
                    return extract_envs(data)

                def is_done(status: str) -> bool:
                    s = (status or "").lower()
                    return s in {"succeeded", "rejected", "canceled", "failed"}

                want_ids = set(stage_ids)
                want_names = set(flow.release_stage_names or [])
                deadline = time.time() + 60 * 60
                last_line = ""
                printed_debug = False

                def select_envs(envs):
                    # IMPORTANT: release environment id != definition environment id.
                    # The selected stage ids are definition environment ids.
                    by_def_id = [e for e in envs if (e.definition_environment_id or "") in want_ids]
                    if by_def_id:
                        return by_def_id, "definitionEnvironmentId"
                    by_name = [e for e in envs if e.name in want_names]
                    if by_name:
                        return by_name, "name"
                    return [], "none"

                while time.time() < deadline:
                    try:
                        envs = fetch_envs()
                    except Exception as e:
                        emit_error("监控失败", str(e))
                        return

                    selected, mode = select_envs(envs)
                    if not selected:
                        line = "监控：等待阶段进入 release（环境列表尚未出现/未匹配）"
                        if not printed_debug:
                            avail = "\n".join(
                                [
                                    f"- {e.name} (envId={e.id}, defEnvId={e.definition_environment_id}) status={e.status}"
                                    for e in envs
                                ]
                            )
                            emit_log("调试：期望阶段IDs=" + ",".join(sorted(want_ids)))
                            if want_names:
                                emit_log("调试：期望阶段Names=" + " | ".join(flow.release_stage_names or []))
                            emit_log("调试：当前Release environments：\n" + (avail or "(空)"))
                            printed_debug = True
                    else:
                        parts = [
                            f"{e.name}(defEnvId={e.definition_environment_id}, envId={e.id})={e.status}"
                            for e in selected
                        ]
                        line = f"监控(mode={mode})：" + " | ".join(parts)

                    # avoid spamming identical lines
                    if line != last_line:
                        emit_log(line)
                        last_line = line

                    # auto-start notStarted environments
                    for e in selected:
                        if (e.status or '').lower() == 'notstarted':
                            try:
                                emit_log(f"触发部署：{e.name} (envId={e.id}, defEnvId={e.definition_environment_id})")
                                start_release_environment(
                                    lib.base_url,
                                    proj.collection,
                                    proj.project,
                                    rel.id,
                                    e.id,
                                    pat=pat,
                                )
                            except Exception as ex:
                                emit_error("触发部署失败", str(ex))
                                return

                    if selected and all(is_done(e.status) for e in selected):
                        failed = [e for e in selected if e.status.lower() not in ("succeeded",)]
                        if failed:
                            msg = "Release 完成但存在失败阶段：\n" + "\n".join(
                                [f"- {e.name} ({e.id}) status={e.status}" for e in failed]
                            )
                            emit_error("发布失败", msg + (f"\n\n{rel.url or ''}"))
                            return

                        emit_log("✅ Release 成功（所选阶段全部 succeeded）")
                        emit_log(rel.url or "")
                        notify_telegram(
                            "✅ 任务成功\n"
                            f"{flow.repo_name or ''} {flow.source_branch}->{flow.target_branch}\n"
                            f"Build: {flow.build_name or flow.build_id}\n"
                            f"Release: {flow.release_name or flow.release_id}\n"
                            f"{rel.url or ''}"
                        )
                        return

                    # sleep in small steps so Stop reacts quickly
                    for _ in range(10):
                        if should_stop():
                            emit_log("已停止：用户取消（发布已触发，停止后不会回滚）")
                            # notification policy: only start + final result
                            return
                        time.sleep(1.0)

                emit_error("发布超时", f"Release 监控超时（60min）：{rel.url or ''}")
                return

            except Exception as e:
                emit_error("运行异常", str(e))
            finally:
                q.put(("done", ""))

        # UI init
        card.set_actions_enabled(False)
        self._clear_run_log(card)
        log = RunLogDialog(self.window(), title="运行：合并并推送 + 构建")
        log.show()

        def flush():
            finished = False
            try:
                while True:
                    kind, payload = q.get_nowait()
                    if kind == "log":
                        self._append_run_log(card, payload)
                        log.log(payload)
                    elif kind == "error":
                        # payload = title + '\n' + details
                        parts = payload.split("\n", 1)
                        title = parts[0]
                        details = parts[1] if len(parts) > 1 else ""
                        show_error_dialog(self.window(), title, details)
                    elif kind == "done":
                        finished = True
            except Exception:
                pass

            if finished:
                card.set_actions_enabled(True)
                self._running = False
                self._running_task = ""
                return
            QtCore.QTimer.singleShot(120, flush)

        th = threading.Thread(target=worker, daemon=True)
        th.start()
        QtCore.QTimer.singleShot(120, flush)

    def _stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
            # stop applies to current running task; log into both cards if present
            try:
                self.flow_card.append_log("收到停止请求：将尽快停止（不回滚已触发的构建/发布）")
            except Exception:
                pass
            try:
                self.sync_card.append_log("收到停止请求：将尽快停止（不回滚已触发的构建/发布）")
            except Exception:
                pass
