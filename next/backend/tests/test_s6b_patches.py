"""S6-B regression tests for Lark MCP patches (S6-LEAD-001) and Figma MCP concurrency patch."""

import shutil
import subprocess
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
LARK_PATCH = BACKEND_DIR / "resources/mcp/lark_mcp_patches.js"
FIGMA_PATCH = BACKEND_DIR / "resources/mcp/figma_mcp_concurrency.js"


def _find_system_node() -> str | None:
    for candidate in ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"):
        if Path(candidate).is_file():
            return candidate
    # node is used here only as a JS interpreter on fixture files (never npx/npm/lark-mcp).
    return shutil.which("node", path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin") or shutil.which(
        "node"
    )


def test_lark_patch_resolves_relative_oidc_without_request_prefilter(tmp_path):
    """S6-LEAD-001: Module._load hook must resolve filename first so require('./oidc') hits."""
    assert LARK_PATCH.is_file(), "lark_mcp_patches.js must exist"
    text = LARK_PATCH.read_text(encoding="utf-8")

    # Must not pre-filter by request string containing 'lark-mcp' before _resolveFilename
    assert "typeof request !== 'string' || !request.includes('lark-mcp')" not in text
    assert 'typeof request !== "string" || !request.includes("lark-mcp")' not in text
    assert "Module._resolveFilename" in text

    # Must check resolved path against all three target suffixes
    assert "mcp-tool/mcp-tool.js" in text
    assert "auth/store.js" in text
    assert "auth/provider/oidc.js" in text

    # Must emit [toolbox-lark-patch] <name>=applied|skipped|failed markers for all 3 patches
    for patch_name in ("auth_store", "oidc", "mcp_tool"):
        assert patch_name in text
    assert "[toolbox-lark-patch]" in text
    for status in ("applied", "skipped", "failed"):
        assert status in text

    # Simulate the resolution matcher in Python against a fake @larksuiteoapi/lark-mcp tree
    # where auth/provider/index.js calls require('./oidc')
    dist = tmp_path / "node_modules/@larksuiteoapi/lark-mcp/dist"
    provider_dir = dist / "auth/provider"
    store_dir = dist / "auth"
    tool_dir = dist / "mcp-tool"
    provider_dir.mkdir(parents=True)
    tool_dir.mkdir(parents=True)

    oidc_file = provider_dir / "oidc.js"
    store_file = store_dir / "store.js"
    tool_file = tool_dir / "mcp-tool.js"
    for f in (oidc_file, store_file, tool_file):
        f.write_text("module.exports = {};\n", encoding="utf-8")

    # Simulate parent = dist/auth/provider/index.js requiring "./oidc"
    request = "./oidc"
    resolved = str((provider_dir / request).resolve()) + ".js"
    normalized = resolved.replace("\\", "/")
    assert "lark-mcp" in normalized
    assert normalized.endswith("auth/provider/oidc.js")


REAL_SHAPE_TREE = {
    # Shapes mirror lark-mcp 0.5.1 (S6-0, and the old app's proven patch): auth/store.js exports
    # the singleton `authStore`, oidc.js exports LarkOIDC2OAuthServerProvider, mcp-tool.js
    # exports LarkMcpTool. S6-ACC-001: an earlier fixture invented other names and so hid that the
    # patch matched nothing in the real package.
    "mcp-tool/mcp-tool.js": """
class LarkMcpTool {
  async ensureGetUserAccessToken() {
    this.calls = (this.calls || 0) + 1;
    await new Promise((r) => setTimeout(r, 20));
    return { userAccessToken: this.nextToken || "tok-" + this.calls };
  }
}
module.exports = { LarkMcpTool };
""",
    "auth/store.js": """
class Store {
  constructor() { this.storageDataCache = { tokens: {} }; this.saved = 0; }
  async storeToken(t) { this.storageDataCache.tokens[t.token] = t; }
  async removeToken(k) { delete this.storageDataCache.tokens[k]; }
  async saveToStorage() { this.saved += 1; }
}
module.exports = { authStore: new Store() };
""",
    "auth/provider/oidc.js": """
class LarkOIDC2OAuthServerProvider {
  async verifyAccessToken(token) {
    return { token, expiresAt: this.expiresAt, extra: this.extra };
  }
}
module.exports = { LarkOIDC2OAuthServerProvider };
""",
    # The real package loads the provider through a relative request.
    "auth/provider/index.js": 'module.exports = require("./oidc");\n',
}

REAL_SHAPE_RUNNER = """
const root = "./node_modules/@larksuiteoapi/lark-mcp/dist/";
const { LarkMcpTool } = require(root + "mcp-tool/mcp-tool");
const { authStore } = require(root + "auth/store");
const { LarkOIDC2OAuthServerProvider } = require(root + "auth/provider/index");
(async () => {
  const tool = new LarkMcpTool();
  const [a, b] = await Promise.all([tool.ensureGetUserAccessToken(), tool.ensureGetUserAccessToken()]);
  if (a !== b || tool.calls !== 1) throw new Error("single-flight failed");

  // expired token with a refresh token: the HTTP middleware must still see it as valid
  const provider = new LarkOIDC2OAuthServerProvider();
  provider.expiresAt = 1; provider.extra = { refreshToken: "rt" };
  const verified = await provider.verifyAccessToken("old");
  if (!(verified.expiresAt > Date.now() / 1000)) throw new Error("expired token not extended");
  if (provider.expiresAt !== 1) throw new Error("stored expiry must stay untouched");
  provider.extra = {};  // no refresh token: untouched
  if ((await provider.verifyAccessToken("old")).expiresAt !== 1) throw new Error("must not extend");

  // refresh: storeToken(new) then removeToken(old) keeps old alive and maps old -> new
  await authStore.storeToken({ token: "old", expiresAt: 1, extra: { refreshToken: "rt0" } });
  await authStore.storeToken({ token: "new", expiresAt: 9e9, extra: { refreshToken: "rt1" } });
  await authStore.removeToken("old");
  const kept = authStore.storageDataCache.tokens.old;
  if (!kept || kept.expiresAt !== 9e9 || kept.extra.refreshToken !== "rt1") throw new Error("old entry not carried");
  if (authStore.saved !== 1) throw new Error("not persisted");
  // a client still presenting the old bearer is answered with the current token
  const fresh = new LarkMcpTool();
  fresh.nextToken = "old";
  if ((await fresh.ensureGetUserAccessToken()).userAccessToken !== "new") throw new Error("chain not followed");
  console.log("ALL_PATCHES_OK");
})().catch((e) => { console.error(e.message); process.exit(1); });
"""


def _write_tree(tmp_path, tree):
    dist = tmp_path / "node_modules/@larksuiteoapi/lark-mcp/dist"
    for rel, text in tree.items():
        target = dist / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _run_node(node_bin, tmp_path, runner_text):
    runner = tmp_path / "run_check.js"
    runner.write_text(runner_text, encoding="utf-8")
    return subprocess.run(
        [node_bin, "--require", str(LARK_PATCH), str(runner)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin"},
    )


def test_lark_patch_applies_to_real_shaped_modules_via_relative_oidc(tmp_path):
    """S6-LEAD-001 + S6-ACC-001: all three patches apply, oidc through require('./oidc')."""
    node_bin = _find_system_node()
    if not node_bin:
        pytest.skip("node not available")
    _write_tree(tmp_path, REAL_SHAPE_TREE)
    proc = _run_node(node_bin, tmp_path, REAL_SHAPE_RUNNER)
    assert proc.returncode == 0, proc.stderr
    assert "ALL_PATCHES_OK" in proc.stdout
    for name in ("mcp_tool", "auth_store", "oidc"):
        assert f"[toolbox-lark-patch] {name}=applied" in proc.stderr
    assert "skipped" not in proc.stderr and "failed" not in proc.stderr


def test_lark_patch_reports_skipped_when_targets_are_missing(tmp_path):
    node_bin = _find_system_node()
    if not node_bin:
        pytest.skip("node not available")
    tree = dict(REAL_SHAPE_TREE)
    tree["auth/store.js"] = "module.exports = { SomethingElse: class {} };\n"
    tree["auth/provider/oidc.js"] = "module.exports = { LarkOIDC2Provider: class {} };\n"
    tree["mcp-tool/mcp-tool.js"] = "class LarkMcpTool {}\nmodule.exports = { LarkMcpTool };\n"
    _write_tree(tmp_path, tree)
    runner = (
        'require("./node_modules/@larksuiteoapi/lark-mcp/dist/mcp-tool/mcp-tool");'
        'require("./node_modules/@larksuiteoapi/lark-mcp/dist/auth/store");'
        'require("./node_modules/@larksuiteoapi/lark-mcp/dist/auth/provider/index");'
        'console.log("SERVER_STILL_UP");'
    )
    proc = _run_node(node_bin, tmp_path, runner)
    assert proc.returncode == 0, proc.stderr
    assert "SERVER_STILL_UP" in proc.stdout
    for name in ("mcp_tool", "auth_store", "oidc"):
        assert f"[toolbox-lark-patch] {name}=skipped" in proc.stderr


def test_figma_concurrency_patch_structure():
    assert FIGMA_PATCH.is_file(), "figma_mcp_concurrency.js must exist"
    text = FIGMA_PATCH.read_text(encoding="utf-8")
    assert "FIGMA_MAX_CONCURRENCY" in text
    assert "FIGMA_MIN_INTERVAL_MS" in text
    assert "FIGMA_MAX_RETRY" in text
    assert "api.figma.com" in text
    assert "globalThis.fetch" in text
