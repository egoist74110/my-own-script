/**
 * Lark MCP runtime patches (loaded via NODE_OPTIONS="--require .../lark_mcp_patches.js").
 *
 * Ported from the old app's lark_mcp_singleflight.js (proven against lark-mcp 0.5.1; targets
 * re-verified in S6-0). Targets and shapes are taken from the real package, not invented:
 *   - auth/store.js          exports the singleton `authStore`; storeToken/removeToken are
 *                            prototype methods, entries live in `storageDataCache.tokens`.
 *   - auth/provider/oidc.js  exports `LarkOIDC2OAuthServerProvider` (async verifyAccessToken).
 *   - mcp-tool/mcp-tool.js   exports `LarkMcpTool` (ensureGetUserAccessToken).
 *
 * S6-LEAD-001: the module filename is always resolved (Module._resolveFilename) before the
 * "does it belong to lark-mcp" check; there is no request-string pre-filter, so relative
 * requires such as require("./oidc") from auth/provider/index.js are matched.
 *
 * Each patch reports exactly one stderr marker: `[toolbox-lark-patch] <name>=applied|skipped|failed`
 * (names: auth_store, oidc, mcp_tool). A missing target is `skipped`; it never takes the server down.
 */

"use strict";

const Module = require("module");

/** oldToken -> newToken supersession map (updated after every refresh). */
const supersededBy = new Map();
/** Latest token entry written by storeToken, consumed by the next removeToken (TTL guarded). */
let pendingNewToken = null;
let pendingNewTokenAt = 0;
const PENDING_TTL_MS = 10000;

const SUFFIX_MCP_TOOL = "mcp-tool/mcp-tool.js";
const SUFFIX_AUTH_STORE = "auth/store.js";
const SUFFIX_OIDC = "auth/provider/oidc.js";

const reported = new Set();
function mark(name, status) {
  if (reported.has(name)) return false;
  reported.add(name);
  try {
    process.stderr.write(`[toolbox-lark-patch] ${name}=${status}\n`);
  } catch (_err) {
    // stderr closed: nothing to report to
  }
  return true;
}

function patchAuthStore(store) {
  const proto = Object.getPrototypeOf(store);
  const origStore = proto && proto.storeToken;
  const origRemove = proto && proto.removeToken;
  if (typeof origStore !== "function" || typeof origRemove !== "function") {
    mark("auth_store", "skipped");
    return;
  }
  if (origStore.__tbPatched || origRemove.__tbPatched) return;

  proto.storeToken = async function (tokenData) {
    const result = await origStore.call(this, tokenData);
    if (tokenData && tokenData.token) {
      pendingNewToken = tokenData;
      pendingNewTokenAt = Date.now();
    }
    return result;
  };
  proto.storeToken.__tbPatched = true;

  // A refresh stores the new token then removes the old one. Keep the old entry alive (carrying
  // the new expiry/refresh token) and remember old -> new, so a client's old bearer keeps working.
  proto.removeToken = async function (oldToken) {
    const age = Date.now() - pendingNewTokenAt;
    const newData = age < PENDING_TTL_MS ? pendingNewToken : null;
    pendingNewToken = null;

    const isSupersession =
      newData &&
      newData.token &&
      newData.token !== oldToken &&
      newData.extra &&
      newData.extra.refreshToken;

    if (isSupersession) {
      try {
        const cache = this.storageDataCache && this.storageDataCache.tokens;
        const existing = cache && cache[oldToken];
        if (existing) {
          existing.expiresAt = newData.expiresAt;
          existing.extra = existing.extra || {};
          existing.extra.refreshToken = newData.extra.refreshToken;
          if (newData.extra.appId) existing.extra.appId = newData.extra.appId;
          if (newData.extra.appSecret) existing.extra.appSecret = newData.extra.appSecret;
        }
        supersededBy.set(oldToken, newData.token);
        if (typeof this.saveToStorage === "function") {
          await this.saveToStorage();
        }
        return;
      } catch (_err) {
        // fall through to the original removal
      }
    }
    return origRemove.call(this, oldToken);
  };
  proto.removeToken.__tbPatched = true;
  mark("auth_store", "applied");
}

function patchOidc(Provider) {
  const proto = Provider && Provider.prototype;
  const orig = proto && proto.verifyAccessToken;
  if (typeof orig !== "function") {
    mark("oidc", "skipped");
    return;
  }
  if (orig.__tbPatched) return;

  // The HTTP bearer middleware rejects an expired token before ensureGetUserAccessToken could
  // refresh it. For an expired token that still has a refresh token, report "2 minutes left" to
  // the middleware only; the stored expiresAt stays untouched so the refresh path still triggers.
  proto.verifyAccessToken = async function (token) {
    const result = await orig.call(this, token);
    if (!result) return result;
    const now = Date.now() / 1000;
    const expired = result.expiresAt && result.expiresAt < now;
    const hasRefreshToken = result.extra && result.extra.refreshToken;
    if (expired && hasRefreshToken) {
      return Object.assign({}, result, { expiresAt: now + 120 });
    }
    return result;
  };
  proto.verifyAccessToken.__tbPatched = true;
  mark("oidc", "applied");
}

function patchMcpTool(Tool) {
  const proto = Tool && Tool.prototype;
  const orig = proto && proto.ensureGetUserAccessToken;
  if (typeof orig !== "function") {
    mark("mcp_tool", "skipped");
    return;
  }
  if (orig.__tbPatched) return;

  // Layer 1: single-flight, so concurrent calls share one refresh (avoids Lark error 20038).
  function singleFlight() {
    if (this.__tbInflight) return this.__tbInflight;
    let p;
    try {
      p = Promise.resolve(orig.apply(this, arguments));
    } catch (err) {
      return Promise.reject(err);
    }
    this.__tbInflight = p;
    const clear = () => {
      this.__tbInflight = null;
    };
    p.then(clear, clear);
    return p;
  }

  // Layer 2: follow the supersession chain so an old bearer resolves to the current token.
  proto.ensureGetUserAccessToken = async function () {
    const result = await singleFlight.apply(this, arguments);
    if (result && result.userAccessToken) {
      let current = result.userAccessToken;
      let hops = 0;
      while (supersededBy.has(current) && hops++ < 20) {
        current = supersededBy.get(current);
      }
      if (current !== result.userAccessToken) {
        return Object.assign({}, result, { userAccessToken: current });
      }
    }
    return result;
  };
  proto.ensureGetUserAccessToken.__tbPatched = true;
  mark("mcp_tool", "applied");
}

function apply(name, fn, target) {
  try {
    fn(target);
  } catch (_err) {
    mark(name, "failed");
  }
}

const origLoad = Module._load;
Module._load = function (request, parent, isMain) {
  const exported = origLoad.apply(this, arguments);
  if (typeof request !== "string" || !exported) return exported;

  let filename = "";
  try {
    filename = Module._resolveFilename(request, parent, isMain);
  } catch (_err) {
    return exported;
  }
  const normalized = String(filename).replace(/\\/g, "/");
  if (!normalized.includes("lark-mcp")) return exported;

  if (normalized.endsWith(SUFFIX_MCP_TOOL)) {
    if (exported.LarkMcpTool) apply("mcp_tool", patchMcpTool, exported.LarkMcpTool);
    else mark("mcp_tool", "skipped");
  } else if (normalized.endsWith(SUFFIX_AUTH_STORE)) {
    if (exported.authStore) apply("auth_store", patchAuthStore, exported.authStore);
    else mark("auth_store", "skipped");
  } else if (normalized.endsWith(SUFFIX_OIDC)) {
    if (exported.LarkOIDC2OAuthServerProvider) {
      apply("oidc", patchOidc, exported.LarkOIDC2OAuthServerProvider);
    } else {
      mark("oidc", "skipped");
    }
  }
  return exported;
};
