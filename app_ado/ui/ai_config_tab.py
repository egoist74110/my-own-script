from __future__ import annotations

import shlex
import subprocess
import threading
import uuid
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import CardWidget, ComboBox, InfoBar, InfoBarPosition, PushButton

from app_ado.ai_policy import load_ai_change_policy
from app_ado.model_collaboration_rules import (
    apply_rule_to_global,
    apply_rule_to_repo,
    global_rule_path,
    inspect_rule_target,
    inspect_template_target,
    remove_rule_from_global,
    remove_rule_from_repo,
    repo_rule_path,
)
from app_ado.models import (
    AiCliProfile,
    AiPolicyConfig,
)
from app_ado.store import load_ui_settings, save_ui_settings
from app_ado.ui.confirm import show_confirm_dialog
from app_ado.ui.dialogs import (
    show_error_dialog,
    show_text_result_dialog,
)
from ok.gui.widget.Tab import Tab


class AiProfileDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__(parent)
        self._result: AiCliProfile | None = None
        self.setWindowTitle("新增 AI 配置")
        self.setModal(True)
        self.resize(520, 180)

        root = QtWidgets.QFormLayout(self)
        root.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.name_edit = QtWidgets.QLineEdit()
        self.command_edit = QtWidgets.QLineEdit()
        self.command_edit.setPlaceholderText("例如：my-ai-cli")
        root.addRow("名称", self.name_edit)
        root.addRow("启动命令", self.command_edit)

        row = QtWidgets.QHBoxLayout()
        self.btn_cancel = PushButton("取消")
        self.btn_ok = PushButton("保存")
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        root.addRow(row)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._on_ok)

    def result_profile(self) -> AiCliProfile | None:
        return self._result

    def _on_ok(self) -> None:
        name = self.name_edit.text().strip()
        command = self.command_edit.text().strip()
        if not name:
            show_error_dialog(self, "错误", "名称不能为空")
            return
        if not command:
            show_error_dialog(self, "错误", "启动命令不能为空")
            return
        self._result = AiCliProfile(id=f"custom:{uuid.uuid4()}", name=name, command=command, builtin=False)
        self.accept()


class AiConfigTab(Tab):
    icon = None
    name = "AI配置"
    _project_root = Path(__file__).resolve().parents[2]

    def __init__(self):
        super().__init__()
        self._settings = load_ui_settings()
        self._builtin_policy = load_ai_change_policy()
        self._migrate_and_seed_profiles()

        self._build_tool_card()
        self._build_scope_card()
        self._build_policy_card()
        self._load_all()

    def _toast(self, title: str, content: str, ok: bool = True) -> None:
        if ok:
            InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
        else:
            InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def _default_profiles(self) -> list[AiCliProfile]:
        return [
            AiCliProfile(id="codex", name="Codex", command="codex", builtin=True),
            AiCliProfile(id="claude_code", name="Claude Code", command="claude", builtin=True),
        ]

    def _migrate_and_seed_profiles(self) -> None:
        tool = self._settings.ai.tool
        existing = {x.id: x for x in (tool.profiles or [])}
        changed = False
        for profile in self._default_profiles():
            cur = existing.get(profile.id)
            if cur is None:
                existing[profile.id] = profile
                changed = True
                continue
            if not cur.builtin:
                cur.builtin = True
                changed = True
            if not cur.command.strip():
                cur.command = profile.command
                changed = True
            if not cur.name.strip():
                cur.name = profile.name
                changed = True

        if not tool.profiles:
            targets = list(self._settings.ai.targets or [])
            target = None
            if self._settings.ai.default_target_id:
                target = next((x for x in targets if x.id == self._settings.ai.default_target_id), None)
            if target is None and targets:
                target = targets[0]
            if target is not None and target.command.strip():
                existing[f"custom:{uuid.uuid4()}"] = AiCliProfile(
                    id=f"custom:{uuid.uuid4()}",
                    name=(target.name or "迁移的自定义AI"),
                    command=target.command,
                    builtin=False,
                )
                changed = True

        tool.profiles = list(existing.values())
        if not tool.selected_profile_id or tool.selected_profile_id not in existing:
            tool.selected_profile_id = "codex"
            changed = True

        if changed:
            save_ui_settings(self._settings)
            self._settings = load_ui_settings()

    def _build_tool_card(self) -> None:
        w = CardWidget(self)
        form = QtWidgets.QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.profile_combo = ComboBox()
        self.profile_combo.setFixedWidth(280)
        self.command_edit = QtWidgets.QLineEdit()
        self.command_edit.setPlaceholderText("启动命令")

        self.btn_save_tool = PushButton("保存工具配置")
        self.btn_test_tool = PushButton("测试工具")
        self.btn_add_profile = PushButton("新增")
        self.btn_delete_profile = PushButton("删除")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_save_tool)
        row.addWidget(self.btn_test_tool)
        row.addWidget(self.btn_add_profile)
        row.addWidget(self.btn_delete_profile)
        row.addStretch(1)

        form.addRow("AI工具", self.profile_combo)
        form.addRow("启动命令", self.command_edit)
        form.addRow(row)

        self.profile_combo.currentIndexChanged.connect(self._load_selected_profile)
        self.profile_combo.currentIndexChanged.connect(self._remember_selected_profile)
        self.btn_save_tool.clicked.connect(self._save_tool)
        self.btn_test_tool.clicked.connect(self._test_tool)
        self.btn_add_profile.clicked.connect(self._add_profile)
        self.btn_delete_profile.clicked.connect(self._delete_profile)

        self.add_card("AI工具接入", w)

    def _build_policy_card(self) -> None:
        w = CardWidget(self)
        form = QtWidgets.QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.chk_policy_enabled = QtWidgets.QCheckBox("启用 AI 策略检查")
        self.chk_require_policy_check = QtWidgets.QCheckBox("改代码前必须先做策略评估")
        self.chk_allow_direct_code_change = QtWidgets.QCheckBox("允许 AI 直接改代码")

        self.prompt_template = QtWidgets.QPlainTextEdit()
        self.prompt_template.setFixedHeight(120)
        self.prompt_template.setPlaceholderText("这里填默认 Prompt。会作为发给 AI 的底层约束。")

        self.forbidden_paths = QtWidgets.QPlainTextEdit()
        self.forbidden_paths.setFixedHeight(100)
        self.forbidden_paths.setPlaceholderText("每行一个路径，例如：app_ado/secrets.py")

        self.deny_keywords = QtWidgets.QPlainTextEdit()
        self.deny_keywords.setFixedHeight(100)
        self.deny_keywords.setPlaceholderText("每行一个高风险关键词，例如：支付、权限、token")

        self.btn_save_policy = PushButton("保存默认约束")
        self.btn_reset_policy = PushButton("恢复内置默认")
        self.btn_copy_prompt = PushButton("复制当前默认Prompt")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_save_policy)
        row.addWidget(self.btn_reset_policy)
        row.addWidget(self.btn_copy_prompt)
        row.addStretch(1)

        form.addRow(self.chk_policy_enabled)
        form.addRow(self.chk_require_policy_check)
        form.addRow(self.chk_allow_direct_code_change)
        form.addRow("默认Prompt", self.prompt_template)
        form.addRow("禁止修改路径", self.forbidden_paths)
        form.addRow("高风险关键词", self.deny_keywords)
        form.addRow(row)

        self.btn_save_policy.clicked.connect(self._save_policy)
        self.btn_reset_policy.clicked.connect(self._reset_policy)
        self.btn_copy_prompt.clicked.connect(self._copy_prompt)

        self.add_card("默认Prompt与限制逻辑", w)

    def _build_scope_card(self) -> None:
        w = CardWidget(self)
        form = QtWidgets.QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.model_rule_combo = ComboBox()
        self.model_rule_combo.setFixedWidth(280)
        self.model_rule_combo.addItem("Claude", userData="claude")
        self.model_rule_combo.addItem("Codex", userData="codex")
        self.model_rule_combo.addItem("Gemini", userData="gemini")

        self.apply_target_combo = ComboBox()
        self.apply_target_combo.setFixedWidth(280)
        self.apply_target_combo.addItem("全局", userData="global")
        self.apply_target_combo.addItem("本地仓库", userData="repo")

        self.repo_target_combo = ComboBox()
        self.repo_target_combo.setFixedWidth(360)

        self.deploy_status = QtWidgets.QLabel("")
        self.deploy_status.setWordWrap(True)

        self.btn_apply_rule = PushButton("部署")
        self.btn_remove_rule = PushButton("删除")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_apply_rule)
        row.addWidget(self.btn_remove_rule)
        row.addStretch(1)

        form.addRow("模型切换", self.model_rule_combo)
        form.addRow("模型应用切换", self.apply_target_combo)
        form.addRow("本地仓库", self.repo_target_combo)
        form.addRow("规则状态", self.deploy_status)
        form.addRow(row)

        self.model_rule_combo.currentIndexChanged.connect(self._refresh_rule_status)
        self.apply_target_combo.currentIndexChanged.connect(self._update_scope_widgets)
        self.apply_target_combo.currentIndexChanged.connect(self._refresh_rule_status)
        self.repo_target_combo.currentIndexChanged.connect(self._refresh_rule_status)
        self.btn_apply_rule.clicked.connect(self._apply_selected_rule)
        self.btn_remove_rule.clicked.connect(self._remove_selected_rule)

        self.add_card("规则部署", w)

    def _load_all(self) -> None:
        self._settings = load_ui_settings()
        tool = self._settings.ai.tool
        self._refresh_profile_combo()
        self._refresh_scope_options()

        merged = self._merge_policy(self._builtin_policy, self._settings.ai.default_policy.model_dump())
        self.chk_policy_enabled.setChecked(bool(self._settings.ai.enabled))
        self.chk_require_policy_check.setChecked(bool(self._settings.ai.require_policy_check_before_code_change))
        self.chk_allow_direct_code_change.setChecked(bool(self._settings.ai.allow_direct_code_change))
        self.prompt_template.setPlainText(tool.prompt_template)
        self.forbidden_paths.setPlainText("\n".join(merged.get("forbidden_paths") or []))
        self.deny_keywords.setPlainText("\n".join(merged.get("deny_keywords") or []))
        self._update_scope_widgets()
        self._refresh_rule_status()

    def _refresh_profile_combo(self) -> None:
        self._settings = load_ui_settings()
        selected = self._settings.ai.tool.selected_profile_id
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        idx = 0
        for i, profile in enumerate(self._settings.ai.tool.profiles or []):
            self.profile_combo.addItem(profile.name, userData=profile.id)
            if profile.id == selected:
                idx = i
        if self.profile_combo.count() > 0:
            self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)
        self._load_selected_profile()

    def _refresh_scope_options(self) -> None:
        self.repo_target_combo.blockSignals(True)
        self.repo_target_combo.clear()
        self.repo_target_combo.addItem("未选择", userData="")
        for repo in self._settings.local_repos or []:
            label = f"{repo.name} ({repo.path})"
            self.repo_target_combo.addItem(label, userData=repo.id)
        self.repo_target_combo.blockSignals(False)

    def _selected_profile(self) -> AiCliProfile | None:
        pid = self.profile_combo.currentData()
        return next((x for x in (self._settings.ai.tool.profiles or []) if x.id == pid), None)

    def _load_selected_profile(self) -> None:
        self._settings = load_ui_settings()
        profile = self._selected_profile()
        if profile is None:
            self.command_edit.setText("")
            self.btn_delete_profile.setEnabled(False)
            return
        self.command_edit.setText(profile.command)
        self.btn_delete_profile.setEnabled(not bool(profile.builtin))

    def _remember_selected_profile(self) -> None:
        self._settings = load_ui_settings()
        pid = self.profile_combo.currentData()
        if not pid:
            return
        if self._settings.ai.tool.selected_profile_id == pid:
            return
        self._settings.ai.tool.selected_profile_id = str(pid)
        save_ui_settings(self._settings)

    def _merge_policy(self, base: dict, override: dict) -> dict:
        out = dict(base)
        for key in ("forbidden_paths", "deny_keywords"):
            value = override.get(key)
            if isinstance(value, list) and value:
                out[key] = list(value)
        return out

    def _selected_rule_model(self) -> str:
        return str(self.model_rule_combo.currentData() or "claude")

    def _selected_apply_target(self) -> str:
        return str(self.apply_target_combo.currentData() or "global")

    def _update_scope_widgets(self) -> None:
        self.repo_target_combo.setEnabled(self._selected_apply_target() == "repo")

    def _selected_repo_root(self) -> Path:
        repo_id = str(self.repo_target_combo.currentData() or "")
        repo = next((x for x in (self._settings.local_repos or []) if x.id == repo_id), None)
        if repo and repo.path.strip():
            return Path(repo.path).expanduser()
        return self._project_root

    def _refresh_rule_status(self) -> None:
        model_id = self._selected_rule_model()
        template_result = inspect_template_target(model_id)
        if self._selected_apply_target() == "repo":
            target_path = repo_rule_path(model_id, self._selected_repo_root())
            scope_label = "本地仓库"
        else:
            target_path = global_rule_path(model_id)
            scope_label = "全局"
        if not template_result.ok:
            self.deploy_status.setText(f"当前目标：{scope_label}\n模板缺失\n{target_path}")
            return
        deploy_result = inspect_rule_target(model_id, target_path)
        self.deploy_status.setText(f"当前目标：{scope_label}\n部署状态：{deploy_result.summary}\n{target_path}")

    def _save_tool(self) -> None:
        self._settings = load_ui_settings()
        profile = self._selected_profile()
        if profile is None:
            show_error_dialog(self, "错误", "请先选择 AI 工具")
            return
        command = self.command_edit.text().strip()
        if not command:
            show_error_dialog(self, "错误", "启动命令不能为空")
            return
        for item in self._settings.ai.tool.profiles:
            if item.id == profile.id:
                item.command = command
        self._settings.ai.tool.selected_profile_id = profile.id
        self._settings.ai.tool.prompt_template = self.prompt_template.toPlainText().strip()
        save_ui_settings(self._settings)
        self._refresh_profile_combo()
        self._toast("已保存", "AI 工具配置已保存")

    def _show_rule_result(self, result) -> None:
        show_text_result_dialog(self, result.title, result.summary, result.details)
        self._toast("已完成", result.summary, ok=bool(result.ok))
        self._refresh_rule_status()

    def _apply_selected_rule(self) -> None:
        model_id = self._selected_rule_model()
        template_status = inspect_template_target(model_id)
        if not template_status.ok:
            show_error_dialog(self, "保存失败", template_status.details)
            return
        if self._selected_apply_target() == "repo":
            result = apply_rule_to_repo(model_id, self._selected_repo_root())
        else:
            result = apply_rule_to_global(model_id)
        self._show_rule_result(result)

    def _confirm_remove(self, scope_label: str, details: str) -> bool:
        if not show_confirm_dialog(self, f"确认删除{scope_label}规则", details):
            return False
        return show_confirm_dialog(self, f"再次确认删除{scope_label}规则", "只会删除当前模型写入的受控片段，不会删除其它已有内容。确认继续？")

    def _remove_selected_rule(self) -> None:
        model_id = self._selected_rule_model()
        if self._selected_apply_target() == "repo":
            scope_label = "仓库"
            details = f"将从仓库规则文件中删除 {model_id} 的受控片段：\n{self._selected_repo_root()}\n不会删除其它内容。"
        else:
            scope_label = "全局"
            details = f"将从全局规则文件中删除 {model_id} 的受控片段。不会删除其它内容。"
        if not self._confirm_remove(scope_label, details):
            return
        if self._selected_apply_target() == "repo":
            result = remove_rule_from_repo(model_id, self._selected_repo_root())
        else:
            result = remove_rule_from_global(model_id)
        self._show_rule_result(result)

    def _test_tool(self) -> None:
        command = self.command_edit.text().strip()
        if not command:
            show_error_dialog(self, "测试失败", "请先填写启动命令")
            return
        parts = shlex.split(command)
        if not parts:
            show_error_dialog(self, "测试失败", "命令格式无效")
            return

        self._toast("测试中", "正在检测命令是否可用")
        result: dict[str, object] = {}

        def run() -> None:
            try:
                cp = subprocess.run(parts + ["--help"], capture_output=True, text=True, timeout=15)
                result["ok"] = cp.returncode == 0
            except Exception as e:
                result["ok"] = False
                result["message"] = str(e)

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish() -> None:
            if th.is_alive():
                QtCore.QTimer.singleShot(80, finish)
                return
            if bool(result.get("ok")):
                QtWidgets.QMessageBox.information(self, "测试结果", "测试正常")
            else:
                QtWidgets.QMessageBox.warning(self, "测试结果", str(result.get("message") or "命令不可用"))

        QtCore.QTimer.singleShot(80, finish)

    def _add_profile(self) -> None:
        dlg = AiProfileDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        profile = dlg.result_profile()
        if profile is None:
            return
        self._settings = load_ui_settings()
        self._settings.ai.tool.profiles.append(profile)
        self._settings.ai.tool.selected_profile_id = profile.id
        save_ui_settings(self._settings)
        self._refresh_profile_combo()
        self._toast("已新增", f"AI 工具已创建：{profile.name}")

    def _delete_profile(self) -> None:
        self._settings = load_ui_settings()
        profile = self._selected_profile()
        if profile is None:
            return
        if profile.builtin:
            show_error_dialog(self, "提示", "默认配置不能删除")
            return
        ok = QtWidgets.QMessageBox.question(self, "确认删除", f"删除 AI 工具：{profile.name}？")
        if ok != QtWidgets.QMessageBox.Yes:
            return
        self._settings.ai.tool.profiles = [x for x in (self._settings.ai.tool.profiles or []) if x.id != profile.id]
        if self._settings.ai.tool.selected_profile_id == profile.id:
            self._settings.ai.tool.selected_profile_id = "codex"
        save_ui_settings(self._settings)
        self._refresh_profile_combo()
        self._toast("已删除", f"AI 工具已删除：{profile.name}")

    def _policy_from_form(self) -> AiPolicyConfig:
        def lines(box: QtWidgets.QPlainTextEdit) -> list[str]:
            return [x.strip() for x in box.toPlainText().splitlines() if x.strip()]

        return AiPolicyConfig(
            forbidden_paths=lines(self.forbidden_paths),
            deny_keywords=lines(self.deny_keywords),
        )

    def _save_policy(self) -> None:
        self._settings = load_ui_settings()
        self._settings.ai.enabled = bool(self.chk_policy_enabled.isChecked())
        self._settings.ai.require_policy_check_before_code_change = bool(self.chk_require_policy_check.isChecked())
        self._settings.ai.allow_direct_code_change = bool(self.chk_allow_direct_code_change.isChecked())
        self._settings.ai.default_policy = self._policy_from_form()
        self._settings.ai.tool.prompt_template = self.prompt_template.toPlainText().strip()
        save_ui_settings(self._settings)
        self._toast("已保存", "默认 Prompt 与限制逻辑已保存")

    def _reset_policy(self) -> None:
        self._settings = load_ui_settings()
        self._settings.ai.default_policy = AiPolicyConfig()
        save_ui_settings(self._settings)
        self._load_all()
        self._toast("已恢复", "已恢复为内置默认限制逻辑")

    def _copy_prompt(self) -> None:
        text = self.prompt_template.toPlainText().strip()
        if not text:
            show_error_dialog(self, "提示", "当前默认 Prompt 为空")
            return
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        app.clipboard().setText(text)
        self._toast("已复制", "默认 Prompt 已复制到剪贴板")
