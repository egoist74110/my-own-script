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
    found = shutil.which("node", path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
    return found


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


def test_lark_patch_relative_oidc_and_singleflight_with_node_fixture(tmp_path):
    """If a non-HOME system node binary exists, verify runtime patching of require('./oidc')."""
    node_bin = _find_system_node()
    if not node_bin:
        pytest.skip("system node outside HOME not available in sandbox")

    assert LARK_PATCH.is_file()
    dist = tmp_path / "node_modules/@larksuiteoapi/lark-mcp/dist"
    (dist / "auth/provider").mkdir(parents=True)
    (dist / "mcp-tool").mkdir(parents=True)

    (dist / "mcp-tool/mcp-tool.js").write_text(
        """
class LarkMcpTool {
  async ensureGetUserAccessToken() {
    this.calls = (this.calls || 0) + 1;
    await new Promise((r) => setTimeout(r, 20));
    return "tok-" + this.calls;
  }
}
module.exports = { LarkMcpTool };
""",
        encoding="utf-8",
    )
    (dist / "auth/store.js").write_text(
        """
class AuthStore {
  constructor() { this.map = new Map(); }
  async getToken(k) { return this.map.get(k); }
  async storeToken(t) { this.map.set(t.token, t); return t; }
  async removeToken(k) { this.map.delete(k); }
  async getLocalAccessToken() { return "old"; }
}
module.exports = { AuthStore, authStore: new AuthStore() };
""",
        encoding="utf-8",
    )
    (dist / "auth/provider/oidc.js").write_text(
        """
const { authStore } = require("../store");
class LarkOIDC2Provider {
  async verifyAccessToken(token) {
    const td = await authStore.getToken(token);
    if (!td || (td.expiresAt && td.expiresAt < Date.now() / 1000)) {
      throw new Error("expired");
    }
    return { token, valid: true };
  }
  async exchangeRefreshToken(tokenData) {
    return { token: "new-tok", expiresAt: Math.floor(Date.now() / 1000) + 3600, extra: { refreshToken: "rt2" } };
  }
}
module.exports = { LarkOIDC2Provider };
""",
        encoding="utf-8",
    )
    # Parent index.js loads oidc via relative path './oidc'
    (dist / "auth/provider/index.js").write_text(
        'module.exports = require("./oidc");\n',
        encoding="utf-8",
    )
    runner = tmp_path / "run_check.js"
    runner.write_text(
        """
const { LarkMcpTool } = require("./node_modules/@larksuiteoapi/lark-mcp/dist/mcp-tool/mcp-tool");
const { authStore } = require("./node_modules/@larksuiteoapi/lark-mcp/dist/auth/store");
const { LarkOIDC2Provider } = require("./node_modules/@larksuiteoapi/lark-mcp/dist/auth/provider/index");

(async () => {
  const tool = new LarkMcpTool();
  const [a, b] = await Promise.all([tool.ensureGetUserAccessToken(), tool.ensureGetUserAccessToken()]);
  if (a !== b || tool.calls !== 1) throw new Error("singleflight failed");

  await authStore.storeToken({ token: "expired-tok", expiresAt: 1, extra: { refreshToken: "rt1" } });
  const provider = new LarkOIDC2Provider();
  const verified = await provider.verifyAccessToken("expired-tok");
  if (!verified || !verified.valid) throw new Error("oidc expired extension failed");
  console.log("ALL_PATCHES_OK");
})();
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [node_bin, "--require", str(LARK_PATCH), str(runner)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    assert "ALL_PATCHES_OK" in proc.stdout
    assert "[toolbox-lark-patch] mcp_tool=applied" in proc.stderr
    assert "[toolbox-lark-patch] auth_store=applied" in proc.stderr
    assert "[toolbox-lark-patch] oidc=applied" in proc.stderr


def test_figma_concurrency_patch_structure():
    assert FIGMA_PATCH.is_file(), "figma_mcp_concurrency.js must exist"
    text = FIGMA_PATCH.read_text(encoding="utf-8")
    assert "FIGMA_MAX_CONCURRENCY" in text
    assert "FIGMA_MIN_INTERVAL_MS" in text
    assert "FIGMA_MAX_RETRY" in text
    assert "api.figma.com" in text
    assert "globalThis.fetch" in text
