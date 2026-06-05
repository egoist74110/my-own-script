"""读取 lark-mcp 真实的 token 过期状态，给 UI 做"过期检测/提醒"。

lark-mcp 把 OAuth token 存在 env-paths('lark-mcp').data/storage.json，内容是
``iv:ciphertext`` 的 AES-256-CBC 密文；AES key(hex)存在系统钥匙串
service=``lark-mcp`` account=``encryption-key``(它用 keytar 写，等价于本机 keyring)。

我们不引入新的 Python 加密依赖，直接用项目已就位的 Node 运行时(lark-mcp 本来就靠它)
按同样的 ``aes-256-cbc`` 解密——key 与密文经 stdin 传给 node，不进进程参数，避免泄漏。

注意:这里只"读"，不动 lark-mcp 的任何文件/进程。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import keyring

from app_lark.node_bootstrap import _node_path_beside, env_for_npx, find_npx
from app_lark.store import load_lark_login_state


LARK_KEYCHAIN_SERVICE = "lark-mcp"
LARK_AES_KEY_NAME = "encryption-key"

# Lark user_access_token 官方有效期约 2 小时；refresh_token 约 30 天(每次刷新轮换)。
# 见 https://open.larksuite.com/document/.../authen-v1/oidc-refresh_access_token/create
REFRESH_TOKEN_DAYS = 30


def _data_dir() -> Path:
    """镜像 npm 包 env-paths('lark-mcp').data 的解析规则。"""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "lark-mcp-nodejs"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / "lark-mcp-nodejs" / "Data"
    base = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return Path(base) / "lark-mcp-nodejs"


def _log_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Logs" / "lark-mcp-nodejs"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / "lark-mcp-nodejs" / "Log"
    base = os.environ.get("XDG_STATE_HOME") or str(home / ".local" / "state")
    return Path(base) / "lark-mcp-nodejs"


def _storage_path() -> Path:
    return _data_dir() / "storage.json"


# node 端解密脚本:从 stdin 读 {key, enc}，按 aes-256-cbc 解出明文写 stdout。
_DECRYPT_JS = r"""
let s='';process.stdin.setEncoding('utf8');
process.stdin.on('data',d=>s+=d);
process.stdin.on('end',()=>{
  try{
    const {key,enc}=JSON.parse(s);
    const crypto=require('crypto');
    const i=enc.indexOf(':');
    if(i<0){throw new Error('bad format');}
    const ivHex=enc.slice(0,i), ctHex=enc.slice(i+1);
    const dc=crypto.createDecipheriv('aes-256-cbc',Buffer.from(key,'hex'),Buffer.from(ivHex,'hex'));
    let out=dc.update(ctHex,'hex','utf8')+dc.final('utf8');
    process.stdout.write(out);
  }catch(e){ process.stderr.write(String((e&&e.message)||e)); process.exit(1); }
});
"""


def _decrypt_with_node(key_hex: str, enc_text: str, timeout: float = 8.0) -> str:
    npx = find_npx()
    if npx is None:
        raise RuntimeError("未找到 Node 运行时")
    node = _node_path_beside(npx)
    node_exe = str(node) if node.exists() else "node"
    payload = json.dumps({"key": key_hex, "enc": enc_text})
    cp = subprocess.run(
        [node_exe, "-e", _DECRYPT_JS],
        input=payload,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env_for_npx(npx),
    )
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or "").strip() or "node 解密失败")
    return cp.stdout


def _count_running_instances() -> int:
    """统计当前活着的 lark-mcp server 进程数(暴露"多实例并发"这个续期失败主因)。"""
    if os.name == "nt":
        return 0
    try:
        cp = subprocess.run(
            ["ps", "-axo", "command"], capture_output=True, text=True, timeout=4
        )
    except Exception:
        return 0
    n = 0
    for ln in cp.stdout.splitlines():
        if "lark-mcp" not in ln or " mcp" not in ln:
            continue
        if "npm exec" in ln or "grep" in ln:
            continue  # 只数真正的 node server 进程，跳过 npm exec 包装层
        n += 1
    return n


def _refresh_is_failing(login_iso: str | None) -> bool:
    """扫最近的 lark-mcp 日志:若"最后一次刷新相关事件"是失败(20038)，判定续期已坏。

    用"最后一条相关日志的成败"判断，避开本地时区与 UTC 日志时间戳的换算坑;
    登录(exchange authorization code)成功会把状态翻回正常。best-effort，读不到就当不失败。
    """
    try:
        logs = sorted(_log_dir().glob("lark-mcp-*.log"))
    except Exception:
        return False
    if not logs:
        return False
    last_fail = -1
    last_ok = -1
    for path in logs[-2:]:  # 只看最近两天，够判断当前状态
        try:
            lines = path.read_text("utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for idx, ln in enumerate(lines):
            if "20038" in ln or "Failed to refreshToken" in ln or "Token refresh failed" in ln:
                last_fail = idx
            elif "Successfully exchanged authorization code" in ln or "Successfully refreshed" in ln:
                last_ok = idx
    return last_fail > last_ok


def lark_token_status() -> dict:
    """返回 Lark 凭证的真实过期状态。

    keys: available(bool), logged_in(bool), level('ok'|'warn'|'error'|'unknown'),
          label(str), access_expires_at(float|None), refresh_failing(bool),
          instances(int)
    """
    state = load_lark_login_state()
    logged_in = bool(state.get("logged_in_at"))
    out: dict = {
        "available": False,
        "logged_in": logged_in,
        "level": "unknown",
        "label": "",
        "access_expires_at": None,
        "refresh_failing": False,
        "instances": 0,
    }
    if not logged_in:
        out["label"] = "未登录"
        return out

    out["instances"] = _count_running_instances()

    p = _storage_path()
    if not p.exists():
        out["label"] = "无法读取（找不到 lark-mcp token 缓存）"
        return out
    try:
        key = keyring.get_password(LARK_KEYCHAIN_SERVICE, LARK_AES_KEY_NAME)
        if not key:
            out["label"] = "无法读取（钥匙串里没有 lark-mcp 加密密钥）"
            return out
        enc = p.read_text("utf-8").strip()
        data = json.loads(_decrypt_with_node(key, enc))
    except Exception as e:  # 解密/解析失败:降级提示，不抛
        out["label"] = f"无法读取（{e}）"
        return out

    tokens = (data.get("tokens") or {}) if isinstance(data, dict) else {}
    access_exp: float | None = None
    for v in tokens.values():
        if not isinstance(v, dict):
            continue
        ea = v.get("expiresAt")
        if isinstance(ea, (int, float)):
            access_exp = ea if access_exp is None else max(access_exp, ea)

    out["available"] = True
    out["access_expires_at"] = access_exp

    now = time.time()
    n = out["instances"]

    # 真实 token 状态优先:访问令牌还在有效期内(刚登录/刚刷新)就是正常,
    # 不被历史失败日志(可能是修复前的旧 20038)误判成"已失效"。
    if access_exp and access_exp > now:
        out["refresh_failing"] = False
        mins = int((access_exp - now) // 60)
        out["level"] = "ok"
        out["label"] = f"正常 · 访问令牌约 {mins} 分钟后续期"
    else:
        # 令牌已过期 / 读不到 → 这时才看刷新是否在失败
        refresh_failing = _refresh_is_failing(state.get("logged_in_at"))
        out["refresh_failing"] = refresh_failing
        if refresh_failing:
            out["level"] = "error"
            out["label"] = "续期失败(20038)，点右侧「重新登录」一键修复"
        elif access_exp is None:
            out["level"] = "warn"
            out["label"] = "已登录，读不到访问令牌有效期"
        else:
            out["level"] = "warn"
            out["label"] = "访问令牌已过期，下次调用将自动续期"

    if n >= 3:
        # 多实例并发抢同一个会轮换的 refresh_token，是续期失败的根因，必须显式警告
        if out["level"] == "ok":
            out["level"] = "warn"
        out["label"] += f" · {n}个lark-mcp并发"

    return out


__all__ = ["lark_token_status", "REFRESH_TOKEN_DAYS"]
