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

        # One task card for now; can add more later.
        self.flow_card = TaskCard(
            title="同步/合并 + 构建 + 发布",
            subtitle="把源分支合并到目标分支，然后构建并发布（后续会接入ADO流水线）",
        )
        self.flow_card.config_clicked.connect(self._edit)
        self.flow_card.run_clicked.connect(self._run)
        self.add_widget(self.flow_card)

    def _clear_run_log(self) -> None:
        self.flow_card.clear_log()

    def _append_run_log(self, text: str) -> None:
        self.flow_card.append_log(text)

    def _edit(self) -> None:
        ts = load_task_settings()
        flow = next((f for f in ts.flows if f.id == "sync_merge_build_release"), None)
        if flow is None:
            from app_ado.models import FlowTaskConfig

            flow = FlowTaskConfig()
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

    def _run(self) -> None:
        """Run in a background Python thread to keep UI responsive."""
        ts = load_task_settings()
        flow = next((f for f in ts.flows if f.id == "sync_merge_build_release"), None)
        if not flow:
            self._edit()
            ts = load_task_settings()
            flow = next((f for f in ts.flows if f.id == "sync_merge_build_release"), None)
        if not flow:
            return

        # basic config validation (UI thread)
        missing: list[str] = []
        if not flow.local_repo_path:
            missing.append("- 本地仓库路径")
        if not flow.source_branch:
            missing.append("- 源分支")
        if not flow.target_branch:
            missing.append("- 目标分支")
        if not flow.build_id or not flow.build_kind:
            missing.append("- 构建")
        if not flow.release_id:
            missing.append("- 发布")
        if not (flow.release_stage_ids or []):
            missing.append("- 阶段（至少选择一个）")
        if missing:
            show_error_dialog(self.window(), "配置不完整", "请先在【配置】中补齐：\n" + "\n".join(missing))
            return

        local_path = flow.local_repo_path

        ok = show_confirm_dialog(
            self.window(),
            "确认执行合并并推送 + 构建？",
            "将执行以下操作：\n"
            f"1) fetch origin {flow.source_branch} / {flow.target_branch}\n"
            f"2) 更新本地分支（ff-only）\n"
            f"3) merge origin/{flow.source_branch} -> {flow.target_branch}\n"
            f"4) push origin {flow.target_branch}\n"
            f"5) 触发构建（目标分支：{flow.target_branch}）并等待完成\n\n"
            f"repo_path={local_path}",
        )
        if not ok:
            return

        import queue
        import threading
        import subprocess
        import shlex

        q: queue.Queue[tuple[str, str]] = queue.Queue()
        # ('log'|'error'|'done', payload)

        def ui_call(fn):
            QtCore.QTimer.singleShot(0, fn)

        def emit_log(text: str) -> None:
            q.put(("log", text))

        def emit_error(title: str, details: str) -> None:
            q.put(("error", title + "\n" + details))

        def worker() -> None:
            try:
                emit_log("运行：合并并推送 + 构建")
                emit_log(f"repo_path={local_path}")
                emit_log(f"source={flow.source_branch} target={flow.target_branch}")

                def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
                    line = "$ " + " ".join(shlex.quote(x) for x in cmd)
                    emit_log(line)
                    cp = subprocess.run(cmd, cwd=local_path, capture_output=True, text=True)
                    if cp.stdout:
                        emit_log(cp.stdout.strip())
                    if cp.stderr:
                        emit_log(cp.stderr.strip())
                    return cp

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
                cp = run_cmd(["git", "fetch", "--prune", "origin", flow.source_branch, flow.target_branch])
                if cp.returncode != 0:
                    emit_error("错误", "fetch 失败")
                    return

                for br in [flow.source_branch, flow.target_branch]:
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
                    f"✅ 合并并推送完成：{flow.source_branch} -> {flow.target_branch}" + (f"\nHEAD={head}" if head else "")
                )

                # ---- Build (v3) ----
                from app_ado.store import load_ui_settings
                from app_ado.secrets import get_pat
                from app_ado.ado_build_http import (
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

                branch = flow.target_branch
                emit_log(f"\n--- Build: kind={flow.build_kind} id={flow.build_id} branch={branch} ---")

                build_run_id: str | None = None

                if flow.build_kind == "pipeline":
                    pr = trigger_pipeline_run(lib.base_url, proj.collection, proj.project, flow.build_id, branch=branch, pat=pat)
                    build_run_id = pr.run_id
                    emit_log(f"已触发 Pipeline：run_id={pr.run_id} state={pr.state} url={pr.url or ''}")
                    pr2 = wait_pipeline(lib.base_url, proj.collection, proj.project, flow.build_id, pr.run_id, pat=pat, timeout_min=30)
                    emit_log(f"Pipeline 完成：state={pr2.state} result={pr2.result} url={pr2.url or ''}")
                    if (pr2.result or '').lower() not in ('succeeded', 'success'):
                        emit_error("构建失败", f"Pipeline result={pr2.result}\n{pr2.url or ''}")
                        return
                else:
                    br = trigger_build_definition(lib.base_url, proj.collection, proj.project, flow.build_id, branch=branch, pat=pat)
                    build_run_id = br.build_id
                    emit_log(f"已触发 Build：build_id={br.build_id} status={br.status} url={br.url or ''}")
                    br2 = wait_build(lib.base_url, proj.collection, proj.project, br.build_id, pat=pat, timeout_min=30)
                    emit_log(f"Build 完成：status={br2.status} result={br2.result} url={br2.url or ''}")
                    if (br2.result or '').lower() not in ('succeeded', 'success', 'partiallysucceeded'):
                        emit_error("构建失败", f"Build result={br2.result}\n{br2.url or ''}")
                        return

                emit_log("✅ 构建成功，开始触发 Release ...")

                # ---- Release (v4) ----
                from app_ado.ado_release_http import create_release_from_build

                if not build_run_id:
                    emit_error("错误", "未获得 build_id/run_id，无法创建 Release")
                    return

                stage_ids = flow.release_stage_ids or []
                emit_log(
                    f"\n--- Release: def_id={flow.release_id} build_id={build_run_id} stages={','.join(stage_ids)} ---"
                )

                rel = None
                # try api-version 6.0 first, fallback to 7.0 if needed
                try:
                    rel = create_release_from_build(
                        lib.base_url,
                        proj.collection,
                        proj.project,
                        flow.release_id,
                        build_id=build_run_id,
                        pat=pat,
                        api_version="6.0",
                    )
                except Exception:
                    rel = create_release_from_build(
                        lib.base_url,
                        proj.collection,
                        proj.project,
                        flow.release_id,
                        build_id=build_run_id,
                        pat=pat,
                        api_version="7.0",
                    )

                emit_log(f"已创建 Release：id={rel.id} name={rel.name or ''} url={rel.url or ''}")

                # Monitor selected stages with progress logs every ~10s
                from app_ado.ado_release_http import extract_envs, get_release, start_release_environment
                import time

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
                        return

                    time.sleep(10.0)

                emit_error("发布超时", f"Release 监控超时（60min）：{rel.url or ''}")
                return

            except Exception as e:
                emit_error("运行异常", str(e))
            finally:
                q.put(("done", ""))

        # UI init
        self.flow_card.set_actions_enabled(False)
        self._clear_run_log()
        log = RunLogDialog(self.window(), title="运行：合并并推送 + 构建")
        log.show()

        def flush():
            finished = False
            try:
                while True:
                    kind, payload = q.get_nowait()
                    if kind == "log":
                        self._append_run_log(payload)
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
                self.flow_card.set_actions_enabled(True)
                return
            QtCore.QTimer.singleShot(120, flush)

        th = threading.Thread(target=worker, daemon=True)
        th.start()
        QtCore.QTimer.singleShot(120, flush)
