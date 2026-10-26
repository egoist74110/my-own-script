/**
 * Lark MCP Runtime Patches (loaded via NODE_OPTIONS="--require .../lark_mcp_patches.js")
 *
 * Patches:
 *   1. mcp_tool: LarkMcpTool.prototype.ensureGetUserAccessToken single-flight
 *   2. auth_store: AuthStore.prototype.{getToken,storeToken,removeToken} supersession grace
 *   3. oidc: LarkOIDC2Provider.prototype.{verifyAccessToken,exchangeRefreshToken}
 *
 * S6-LEAD-001 fix: Always resolve filename via Module._resolveFilename(request, parent, isMain)
 * before checking if the module belongs to lark-mcp, so relative requires such as
 * require("./oidc") from dist/auth/provider/index.js are matched reliably.
 */

"use strict";

const Module = require("module");
const origLoad = Module._load;

const SUPERSEDE_GRACE_MS = 60 * 1000;
const RefreshState = {
  inflightByApp: new Map(),
  superseded: new Map(),
  lastRefreshDoneAt: 0,
};

const emittedMarkers = new Set();

function emitMarker(name, status) {
  const key = `${name}=${status}`;
  if (emittedMarkers.has(name)) {
    return;
  }
  emittedMarkers.add(name);
  process.stderr.write(`[toolbox-lark-patch] ${key}\n`);
}

function patchMcpTool(exportsObj) {
  try {
    const Tool = exportsObj && exportsObj.LarkMcpTool;
    if (!Tool || !Tool.prototype || typeof Tool.prototype.ensureGetUserAccessToken !== "function") {
      emitMarker("mcp_tool", "skipped");
      return;
    }
    if (Tool.prototype.ensureGetUserAccessToken.__toolboxPatched) {
      return;
    }
    const origFn = Tool.prototype.ensureGetUserAccessToken;
    const inflight = new WeakMap();
    const wrapped = function (...args) {
      let pending = inflight.get(this);
      if (pending) {
        return pending;
      }
      pending = Promise.resolve()
        .then(() => origFn.apply(this, args))
        .finally(() => {
          inflight.delete(this);
        });
      inflight.set(this, pending);
      return pending;
    };
    wrapped.__toolboxPatched = true;
    Tool.prototype.ensureGetUserAccessToken = wrapped;
    emitMarker("mcp_tool", "applied");
  } catch (_err) {
    emitMarker("mcp_tool", "failed");
  }
}

function patchAuthStore(exportsObj) {
  try {
    const Store = exportsObj && exportsObj.AuthStore;
    if (
      !Store ||
      !Store.prototype ||
      typeof Store.prototype.getToken !== "function" ||
      typeof Store.prototype.storeToken !== "function" ||
      typeof Store.prototype.removeToken !== "function"
    ) {
      emitMarker("auth_store", "skipped");
      return;
    }
    if (Store.prototype.getToken.__toolboxPatched) {
      return;
    }

    const origGetToken = Store.prototype.getToken;
    const origStoreToken = Store.prototype.storeToken;
    const origRemoveToken = Store.prototype.removeToken;

    const getTokenWrapped = async function (accessToken) {
      const record = await origGetToken.call(this, accessToken);
      if (record) {
        return record;
      }
      const entry = RefreshState.superseded.get(accessToken);
      if (!entry) {
        return undefined;
      }
      if (Date.now() > entry.until) {
        RefreshState.superseded.delete(accessToken);
        return undefined;
      }
      const redirected = await origGetToken.call(this, entry.newToken);
      if (redirected) {
        return redirected;
      }
      return entry.tokenData;
    };
    getTokenWrapped.__toolboxPatched = true;
    Store.prototype.getToken = getTokenWrapped;

    Store.prototype.storeToken = async function (tokenData) {
      let prevToken;
      try {
        const appId = tokenData && tokenData.extra && tokenData.extra.appId;
        if (appId && typeof this.getLocalAccessToken === "function") {
          prevToken = await this.getLocalAccessToken(appId);
        }
      } catch (_err) {
        // ignore
      }
      const result = await origStoreToken.call(this, tokenData);
      if (prevToken && tokenData && tokenData.token && prevToken !== tokenData.token) {
        RefreshState.superseded.set(prevToken, {
          newToken: tokenData.token,
          tokenData,
          until: Date.now() + SUPERSEDE_GRACE_MS,
        });
        RefreshState.lastRefreshDoneAt = Date.now();
      }
      return result;
    };

    Store.prototype.removeToken = async function (accessToken) {
      const entry = RefreshState.superseded.get(accessToken);
      if (entry && Date.now() <= entry.until) {
        try {
          if (this.storage && this.storage.tokens && this.storage.tokens[accessToken]) {
            entry.tokenData = this.storage.tokens[accessToken];
          }
        } catch (_err) {
          // ignore
        }
      }
      return origRemoveToken.call(this, accessToken);
    };

    emitMarker("auth_store", "applied");
  } catch (_err) {
    emitMarker("auth_store", "failed");
  }
}

function patchOidcProvider(exportsObj, parent) {
  try {
    const Provider = exportsObj && exportsObj.LarkOIDC2Provider;
    if (
      !Provider ||
      !Provider.prototype ||
      typeof Provider.prototype.verifyAccessToken !== "function" ||
      typeof Provider.prototype.exchangeRefreshToken !== "function"
    ) {
      emitMarker("oidc", "skipped");
      return;
    }
    if (Provider.prototype.verifyAccessToken.__toolboxPatched) {
      return;
    }

    let authStoreRef = null;
    try {
      const storeFilename = Module._resolveFilename("../store", parent, false);
      const storeMod = origLoad.call(Module, storeFilename, parent, false);
      authStoreRef = storeMod && storeMod.authStore;
    } catch (_err) {
      // ignore if store cannot be resolved relative to parent
    }

    const origVerify = Provider.prototype.verifyAccessToken;
    const origRefresh = Provider.prototype.exchangeRefreshToken;

    const verifyWrapped = async function (token) {
      try {
        if (authStoreRef && typeof authStoreRef.getToken === "function") {
          const tokenData = await authStoreRef.getToken(token);
          if (tokenData) {
            const nowSec = Math.floor(Date.now() / 1000);
            const expired = Boolean(tokenData.expiresAt && tokenData.expiresAt < nowSec);
            const hasRefreshToken = Boolean(tokenData.extra && tokenData.extra.refreshToken);
            if (expired && hasRefreshToken) {
              const savedExpiresAt = tokenData.expiresAt;
              tokenData.expiresAt = nowSec + 60;
              try {
                return await origVerify.call(this, token);
              } finally {
                tokenData.expiresAt = savedExpiresAt;
              }
            }
          }
        }
      } catch (_err) {
        // fall through to original verify
      }
      return origVerify.call(this, token);
    };
    verifyWrapped.__toolboxPatched = true;
    Provider.prototype.verifyAccessToken = verifyWrapped;

    Provider.prototype.exchangeRefreshToken = function (tokenData, ...rest) {
      const appId = (tokenData && tokenData.extra && tokenData.extra.appId) || "__default__";
      const existing = RefreshState.inflightByApp.get(appId);
      if (existing) {
        return existing;
      }
      const promise = Promise.resolve()
        .then(async () => {
          const sinceLast = Date.now() - RefreshState.lastRefreshDoneAt;
          if (sinceLast >= 0 && sinceLast < SUPERSEDE_GRACE_MS && authStoreRef) {
            try {
              const latestKey = await authStoreRef.getLocalAccessToken(appId);
              if (latestKey && tokenData && latestKey !== tokenData.token) {
                const latestData = await authStoreRef.getToken(latestKey);
                if (
                  latestData &&
                  (!latestData.expiresAt ||
                    latestData.expiresAt > Math.floor(Date.now() / 1000) + 60)
                ) {
                  return latestData;
                }
              }
            } catch (_err) {
              // proceed with refresh
            }
          }
          return origRefresh.call(this, tokenData, ...rest);
        })
        .finally(() => {
          RefreshState.inflightByApp.delete(appId);
        });
      RefreshState.inflightByApp.set(appId, promise);
      return promise;
    };

    emitMarker("oidc", "applied");
  } catch (_err) {
    emitMarker("oidc", "failed");
  }
}

Module._load = function (request, parent, isMain) {
  const result = origLoad.apply(this, arguments);
  let resolved = "";
  try {
    resolved = Module._resolveFilename(request, parent, isMain);
  } catch (_err) {
    return result;
  }
  const normalized = String(resolved).replace(/\\/g, "/");
  if (!normalized.includes("lark-mcp")) {
    return result;
  }
  if (normalized.endsWith("mcp-tool/mcp-tool.js")) {
    patchMcpTool(result);
  } else if (normalized.endsWith("auth/store.js")) {
    patchAuthStore(result);
  } else if (normalized.endsWith("auth/provider/oidc.js")) {
    patchOidcProvider(result, parent);
  }
  return result;
};
