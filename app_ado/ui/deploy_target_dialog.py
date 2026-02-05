from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import ComboBox, LineEdit, PushButton

from app_ado.ado_http import BuildPipeline, list_build_definitions, list_build_pipelines
from app_ado.ado_release_http import ReleaseDefinition, ReleaseStage, get_release_stages, list_release_definitions
from app_ado.models import DeployTarget
from app_ado.secrets import get_pat
from app_ado.ui.dialogs import show_error_dialog


class DeployTargetDialog(QtWidgets.QDialog):
    """Edit one DeployTarget (build + release + stages)."""

    def __init__(self, parent, *, base_url: str, collection: str, project: str, pat: str, target: DeployTarget):
        super().__init__(parent)
        self._base_url = base_url
        self._collection = collection
        self._project = project
        self._pat = pat
        self._target = target
        self._result: DeployTarget | None = None

        self.setWindowTitle("编辑发布目标")
        self.setModal(True)
        self.resize(760, 520)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        root.addLayout(form)

        def combo() -> ComboBox:
            cb = ComboBox(); cb.setFixedWidth(260)
            return cb

        self.name = LineEdit(); self.name.setFixedWidth(260)
        self.name.setText(target.name)

        self.build_combo = combo()
        self.release_combo = combo()

        self.stage_list = QtWidgets.QListWidget(); self.stage_list.setFixedHeight(200)

        self.btn_refresh_build = PushButton("刷新构建列表")
        self.btn_refresh_release = PushButton("刷新发布/阶段")

        self.btn_refresh_build.clicked.connect(self._refresh_builds)
        self.btn_refresh_release.clicked.connect(self._refresh_releases)

        form.addRow("名称", self.name)
        form.addRow("构建", self._row(self.build_combo, self.btn_refresh_build))
        form.addRow("发布", self._row(self.release_combo, self.btn_refresh_release))
        form.addRow("阶段（多选）", self.stage_list)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # prefill echo
        if target.build_name:
            self.build_combo.addItem(target.build_name, userData=BuildPipeline(id=target.build_id or "", name=target.build_name, kind=target.build_kind or "pipeline"))
            self.build_combo.setCurrentIndex(0)
        if target.release_name:
            self.release_combo.addItem(target.release_name, userData=ReleaseDefinition(id=target.release_id or "", name=target.release_name))
            self.release_combo.setCurrentIndex(0)
        for sid, sname in zip(target.release_stage_ids or [], target.release_stage_names or [], strict=False):
            it = QtWidgets.QListWidgetItem(sname)
            it.setData(QtCore.Qt.UserRole, sid)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked)
            self.stage_list.addItem(it)

    def _row(self, a: QtWidgets.QWidget, b: QtWidgets.QWidget) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(a)
        h.addWidget(b)
        h.addStretch(1)
        return w

    def result_target(self) -> DeployTarget | None:
        return self._result

    def _set_loading(self, on: bool, msg: str = "") -> None:
        self.btn_refresh_build.setEnabled(not on)
        self.btn_refresh_release.setEnabled(not on)
        if msg:
            self.status.setText(msg)

    def _refresh_builds(self) -> None:
        self._set_loading(True, "刷新构建列表...")
        import threading

        result: dict | Exception | None = None

        def run():
            nonlocal result
            try:
                try:
                    items = list_build_pipelines(self._base_url, self._collection, self._project, pat=self._pat)
                except Exception:
                    items = list_build_definitions(self._base_url, self._collection, self._project, pat=self._pat)
                result = {"items": items}
            except Exception as e:
                result = e

        th = threading.Thread(target=run, daemon=True); th.start()

        def finish():
            nonlocal result
            if th.is_alive():
                QtCore.QTimer.singleShot(80, finish)
                return
            self._set_loading(False)
            if isinstance(result, Exception):
                show_error_dialog(self, "刷新失败", str(result))
                return
            items: list[BuildPipeline] = (result or {}).get("items") or []
            self.build_combo.clear()
            for it in items:
                self.build_combo.addItem(it.name, userData=it)
            want = self._target.build_id
            if items:
                idx = 0
                if want:
                    for i in range(self.build_combo.count()):
                        bb: BuildPipeline = self.build_combo.itemData(i)
                        if bb and bb.id == want:
                            idx = i
                            break
                self.build_combo.setCurrentIndex(idx)
            kinds = {it.kind for it in items}
            self.status.setText(f"刷新完成：builds={len(items)} ({', '.join(sorted(kinds))})")

        QtCore.QTimer.singleShot(80, finish)

    def _fill_stages(self, stages: list[ReleaseStage]) -> None:
        want_ids = set(self._target.release_stage_ids or [])
        self.stage_list.clear()
        for s in stages:
            it = QtWidgets.QListWidgetItem(s.name)
            it.setData(QtCore.Qt.UserRole, s.id)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if s.id in want_ids else QtCore.Qt.Unchecked)
            self.stage_list.addItem(it)

    def _refresh_releases(self) -> None:
        current_def: ReleaseDefinition | None = self.release_combo.currentData()
        want_release_id = (current_def.id if current_def and current_def.id else None) or self._target.release_id

        self._set_loading(True, "刷新发布/阶段...")
        import threading

        result: dict | Exception | None = None

        def run():
            nonlocal result
            try:
                try:
                    defs = list_release_definitions(self._base_url, self._collection, self._project, pat=self._pat, api_version="7.0")
                    api_used = "7.0"
                except Exception:
                    defs = list_release_definitions(self._base_url, self._collection, self._project, pat=self._pat, api_version="6.0")
                    api_used = "6.0"
                rid = want_release_id or (defs[0].id if defs else None)
                stages: list[ReleaseStage] = []
                if rid:
                    try:
                        stages = get_release_stages(self._base_url, self._collection, self._project, rid, pat=self._pat, api_version=api_used)
                    except Exception:
                        stages = get_release_stages(self._base_url, self._collection, self._project, rid, pat=self._pat, api_version="6.0")
                result = {"defs": defs, "rid": rid, "stages": stages}
            except Exception as e:
                result = e

        th = threading.Thread(target=run, daemon=True); th.start()

        def finish():
            nonlocal result
            if th.is_alive():
                QtCore.QTimer.singleShot(80, finish)
                return
            self._set_loading(False)
            if isinstance(result, Exception):
                show_error_dialog(self, "刷新失败", str(result))
                return
            defs: list[ReleaseDefinition] = (result or {}).get("defs") or []
            rid = (result or {}).get("rid")
            stages: list[ReleaseStage] = (result or {}).get("stages") or []

            self.release_combo.clear()
            for d in defs:
                self.release_combo.addItem(d.name, userData=d)

            if defs:
                idx = 0
                if rid:
                    for i in range(self.release_combo.count()):
                        dd: ReleaseDefinition = self.release_combo.itemData(i)
                        if dd and dd.id == rid:
                            idx = i
                            break
                self.release_combo.setCurrentIndex(idx)

            self._fill_stages(stages)
            self.status.setText(f"刷新完成：releases={len(defs)} stages={len(stages)}")

        QtCore.QTimer.singleShot(80, finish)

    def accept(self) -> None:
        name = self.name.text().strip()
        if not name:
            show_error_dialog(self, "表单未完整", "名称不能为空")
            return

        bp: BuildPipeline | None = self.build_combo.currentData()
        rd: ReleaseDefinition | None = self.release_combo.currentData()

        stage_ids: list[str] = []
        stage_names: list[str] = []
        for i in range(self.stage_list.count()):
            it = self.stage_list.item(i)
            if it.checkState() == QtCore.Qt.Checked:
                sid = str(it.data(QtCore.Qt.UserRole) or "")
                if sid:
                    stage_ids.append(sid)
                    stage_names.append(it.text())

        missing: list[str] = []
        if not bp or not getattr(bp, "id", ""):
            missing.append("- 请选择构建（可先点：刷新构建列表）")
        if not rd or not getattr(rd, "id", ""):
            missing.append("- 请选择发布（可先点：刷新发布/阶段）")
        if not stage_ids:
            missing.append("- 至少选择一个阶段（可先点：刷新发布/阶段）")
        if missing:
            show_error_dialog(self, "表单未完整", "\n".join(missing))
            return

        self._result = DeployTarget(
            name=name,
            enabled=True,
            build_kind=bp.kind,
            build_id=bp.id,
            build_name=bp.name,
            release_id=rd.id,
            release_name=rd.name,
            release_stage_ids=stage_ids,
            release_stage_names=stage_names,
        )
        super().accept()
