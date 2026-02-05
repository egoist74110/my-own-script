from __future__ import annotations

from PySide6 import QtWidgets

from app_ado.store import load_ui_settings, save_ui_settings
from app_ado.ui.acl_dialogs import AclGroupDialog, AclMemberDialog
from app_ado.ui.dialogs import show_error_dialog, toast


class TelegramAclMixin:
    def _refresh_acl_ui(self):
        self._settings = load_ui_settings()

        groups = list(self._settings.telegram_acl_groups or [])
        members = list(self._settings.telegram_acl_members or [])

        # groups
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        for g in groups:
            self.group_combo.addItem(g.get("name") or "(unnamed)", userData=g.get("id"))
        if groups:
            self.group_combo.setCurrentIndex(0)
        self.group_combo.blockSignals(False)

        self._refresh_members_for_group()
        self.group_combo.currentIndexChanged.connect(self._refresh_members_for_group)

    def _refresh_members_for_group(self):
        gid = self.group_combo.currentData()
        self._settings = load_ui_settings()
        members = [m for m in (self._settings.telegram_acl_members or []) if m.get("group_id") == gid]

        self.member_combo.blockSignals(True)
        self.member_combo.clear()
        for m in members:
            label = m.get("label") or m.get("username") or m.get("chat_id") or "(member)"
            self.member_combo.addItem(label, userData=m.get("id"))
        if members:
            self.member_combo.setCurrentIndex(0)
        self.member_combo.blockSignals(False)

    def _new_group(self):
        dlg = AclGroupDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        g = dlg.result_group()
        if not g:
            return
        s = load_ui_settings()
        # unique name
        if any(x.get("name") == g.get("name") for x in (s.telegram_acl_groups or [])):
            show_error_dialog(self, "错误", f"权限组名称重复：{g.get('name')}")
            return
        s.telegram_acl_groups.append(g)
        save_ui_settings(s)
        toast(self, "已新增", f"权限组：{g.get('name')}")
        self._refresh_acl_ui()

    def _edit_group(self):
        gid = self.group_combo.currentData()
        s = load_ui_settings()
        g0 = next((x for x in (s.telegram_acl_groups or []) if x.get("id") == gid), None)
        if not g0:
            show_error_dialog(self, "错误", "请先选择权限组")
            return
        dlg = AclGroupDialog(self, existing=g0)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        g = dlg.result_group()
        if not g:
            return
        # unique name
        for x in (s.telegram_acl_groups or []):
            if x.get("id") == g.get("id"):
                continue
            if x.get("name") == g.get("name"):
                show_error_dialog(self, "错误", f"权限组名称重复：{g.get('name')}")
                return
        s.telegram_acl_groups = [g if x.get("id") == g.get("id") else x for x in (s.telegram_acl_groups or [])]
        save_ui_settings(s)
        toast(self, "已保存", "权限组已保存")
        self._refresh_acl_ui()

    def _del_group(self):
        gid = self.group_combo.currentData()
        s = load_ui_settings()
        g0 = next((x for x in (s.telegram_acl_groups or []) if x.get("id") == gid), None)
        if not g0:
            show_error_dialog(self, "错误", "请先选择权限组")
            return
        ok = QtWidgets.QMessageBox.question(self, "确认删除", f"删除权限组：{g0.get('name')} ？\n（会同时删除该组成员）")
        if ok != QtWidgets.QMessageBox.Yes:
            return
        s.telegram_acl_groups = [x for x in (s.telegram_acl_groups or []) if x.get("id") != gid]
        s.telegram_acl_members = [m for m in (s.telegram_acl_members or []) if m.get("group_id") != gid]
        save_ui_settings(s)
        toast(self, "已删除", "权限组已删除")
        self._refresh_acl_ui()

    def _new_member(self):
        gid = self.group_combo.currentData()
        s = load_ui_settings()
        g0 = next((x for x in (s.telegram_acl_groups or []) if x.get("id") == gid), None)
        if not g0:
            show_error_dialog(self, "错误", "请先选择权限组")
            return
        dlg = AclMemberDialog(self, group_name=g0.get("name") or "")
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        m = dlg.result_member()
        if not m:
            return
        m["group_id"] = gid
        # unique chat_id/username
        for x in (s.telegram_acl_members or []):
            if m.get("chat_id") and x.get("chat_id") and str(x.get("chat_id")) == str(m.get("chat_id")):
                show_error_dialog(self, "错误", f"chat_id 已存在：{m.get('chat_id')}")
                return
            if m.get("username") and x.get("username") and str(x.get("username")).lower() == str(m.get("username")).lower():
                show_error_dialog(self, "错误", f"username 已存在：{m.get('username')}")
                return
        s.telegram_acl_members.append(m)
        save_ui_settings(s)
        toast(self, "已新增", "成员已新增")
        self._refresh_acl_ui()

    def _edit_member(self):
        mid = self.member_combo.currentData()
        s = load_ui_settings()
        m0 = next((x for x in (s.telegram_acl_members or []) if x.get("id") == mid), None)
        if not m0:
            show_error_dialog(self, "错误", "请先选择成员")
            return
        gid = m0.get("group_id")
        g0 = next((x for x in (s.telegram_acl_groups or []) if x.get("id") == gid), None)
        dlg = AclMemberDialog(self, group_name=g0.get("name") if g0 else "", existing=m0)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        m = dlg.result_member()
        if not m:
            return
        m["group_id"] = gid
        # unique chat_id/username
        for x in (s.telegram_acl_members or []):
            if x.get("id") == m.get("id"):
                continue
            if m.get("chat_id") and x.get("chat_id") and str(x.get("chat_id")) == str(m.get("chat_id")):
                show_error_dialog(self, "错误", f"chat_id 已存在：{m.get('chat_id')}")
                return
            if m.get("username") and x.get("username") and str(x.get("username")).lower() == str(m.get("username")).lower():
                show_error_dialog(self, "错误", f"username 已存在：{m.get('username')}")
                return
        s.telegram_acl_members = [m if x.get("id") == m.get("id") else x for x in (s.telegram_acl_members or [])]
        save_ui_settings(s)
        toast(self, "已保存", "成员已保存")
        self._refresh_acl_ui()

    def _del_member(self):
        mid = self.member_combo.currentData()
        s = load_ui_settings()
        m0 = next((x for x in (s.telegram_acl_members or []) if x.get("id") == mid), None)
        if not m0:
            show_error_dialog(self, "错误", "请先选择成员")
            return
        ok = QtWidgets.QMessageBox.question(self, "确认删除", f"删除成员：{m0.get('label') or m0.get('username') or m0.get('chat_id')} ？")
        if ok != QtWidgets.QMessageBox.Yes:
            return
        s.telegram_acl_members = [x for x in (s.telegram_acl_members or []) if x.get("id") != mid]
        save_ui_settings(s)
        toast(self, "已删除", "成员已删除")
        self._refresh_acl_ui()
