/**
 * lark-mcp 注入补丁集
 * ===================
 * 通过 `NODE_OPTIONS=--require <此文件>` 在 lark-mcp 进程启动时注入。
 *
 * 解决的两个问题：
 *
 * 问题 A — 并发 20038（已有补丁，保留）
 *   UAT 过期后，一波并发工具调用各自拿同一个会轮换的 refresh_token 去刷新，
 *   第一个成功、其余拿旧值 → Lark 20038。
 *   修法：single-flight 锁，并发只允许一次真正刷新，其余复用同一个 Promise。
 *
 * 问题 B — 120 分钟后被要求重新登录（本次新增补丁）
 *   lark-mcp --oauth 模式在 UAT 过期后，HTTP 鉴权中间件（requireBearerAuth）先于
 *   ensureGetUserAccessToken 检测到 token 过期，向 MCP 客户端（Claude Code 等）返回
 *   401 + OAuth challenge → 客户端弹浏览器要求用户重新授权。
 *   ensureGetUserAccessToken 里已有用 refresh_token 静默刷新的路径，但被 HTTP 层拦
 *   截，从未被执行。
 *
 *   三段补丁：
 *
 *   补丁 1 — verifyAccessToken（OIDC provider）：
 *     若 token 已过期但存有 refreshToken，对 HTTP 中间件返回伪造的"未过期"时间戳，
 *     让请求顺利到达 ensureGetUserAccessToken 发起静默刷新。
 *     注意：只骗 HTTP 层；authStore 里存的 expiresAt 原值不变，
 *     ensureGetUserAccessToken 读 isTokenValid 仍拿到"真实过期"，正常触发刷新路径。
 *
 *   补丁 2 — authStore.storeToken / removeToken：
 *     刷新后 handler.refreshToken 会调 storeToken(newToken) 再调 removeToken(oldToken)。
 *     我们截住 removeToken，改为：把 newToken 的 expiresAt + refreshToken 写进旧条目
 *     (tokens[oldToken])，建立接替映射 _supersededBy: oldToken → newToken。
 *     旧 token 不从 store 删除，authStore 的文件监视器也不会因此产生问题。
 *
 *   补丁 3 — ensureGetUserAccessToken 外层 wrapper（supersession 追踪）：
 *     函数返回 {userAccessToken: T0} 时，沿接替链找到当前有效 token Tn，改为返回
 *     {userAccessToken: Tn}。这样 Claude Code 的旧 bearer T0 可以永久使用：
 *       - T0 未过期  → verifyAccessToken(T0) 正常放行，wrapper 把 T0 换成 Tn
 *       - T0 已过期  → verifyAccessToken 伪装放行，ensureGetUserAccessToken
 *                      再次触发刷新拿到 Tn+1，_supersededBy 更新，wrapper 返回 Tn+1
 *
 * 设计安全守则：
 *   - 任何目标方法不存在（上游改版），静默跳过，绝不把 server 带挂。
 *   - 所有补丁均有 try/catch 包裹。
 *   - 只打一次（patched 标志），幂等。
 */
'use strict';

const Module = require('module');

// ─── 跨补丁共享状态 ─────────────────────────────────────────────────────────
/** oldToken → newToken 接替映射（每次刷新后更新） */
const _supersededBy = new Map();
/** storeToken 最近写入的 token 条目，供 removeToken 补丁读取（TTL 10s 保护） */
let _pendingNewToken = null;
let _pendingNewTokenAt = 0;
const PENDING_TTL_MS = 10000;

// ─── 模块路径标识 ────────────────────────────────────────────────────────────
const SUFFIX_MCP_TOOL  = 'mcp-tool/mcp-tool.js';
const SUFFIX_AUTH_STORE = 'auth/store.js';
const SUFFIX_OIDC      = 'auth/provider/oidc.js';

let patchedMcpTool   = false;
let patchedAuthStore = false;
let patchedOidc      = false;

// ─── Module._load 拦截 ───────────────────────────────────────────────────────
const origLoad = Module._load;
Module._load = function (request, parent, isMain) {
  const exported = origLoad.apply(this, arguments);

  if (typeof request !== 'string') return exported;

  // 廉价字符串预过滤，避免对每个无关模块解析文件名（循环依赖保护）
  const probablyLark = request.indexOf('lark-mcp') !== -1 ||
                       request.indexOf('mcp-tool') !== -1 ||
                       request.indexOf('auth')     !== -1;
  if (!probablyLark) return exported;

  if (!exported) return exported;

  let filename = '';
  try {
    filename = Module._resolveFilename(request, parent, isMain).replace(/\\/g, '/');
  } catch (_) {
    return exported;
  }

  if (!filename.includes('lark-mcp')) return exported;

  if (!patchedMcpTool && filename.endsWith(SUFFIX_MCP_TOOL) && exported.LarkMcpTool) {
    try {
      patchMcpTool(exported.LarkMcpTool);
      patchedMcpTool = true;
    } catch (e) {
      console.error('[lark-mcp patch] mcp-tool patch failed:', e && e.message);
    }
  }

  if (!patchedAuthStore && filename.endsWith(SUFFIX_AUTH_STORE) && exported.authStore) {
    try {
      patchAuthStore(exported.authStore);
      patchedAuthStore = true;
    } catch (e) {
      console.error('[lark-mcp patch] authStore patch failed:', e && e.message);
    }
  }

  if (!patchedOidc && filename.endsWith(SUFFIX_OIDC) && exported.LarkOIDC2OAuthServerProvider) {
    try {
      patchOidc(exported.LarkOIDC2OAuthServerProvider);
      patchedOidc = true;
    } catch (e) {
      console.error('[lark-mcp patch] oidc patch failed:', e && e.message);
    }
  }

  return exported;
};

// ─── 补丁 1 · authStore（storeToken + removeToken） ─────────────────────────
function patchAuthStore(store) {
  const proto = Object.getPrototypeOf(store);
  if (!proto) return;

  // storeToken：记录最近写入的 token 条目（供 removeToken 补丁读取）
  const origStore = proto.storeToken;
  if (typeof origStore !== 'function' || origStore.__sfPatched) return;

  proto.storeToken = async function (tokenData) {
    const result = await origStore.call(this, tokenData);
    if (tokenData && tokenData.token) {
      _pendingNewToken = tokenData;
      _pendingNewTokenAt = Date.now();
    }
    return result;
  };
  proto.storeToken.__sfPatched = true;

  // removeToken：刷新时不删旧 token，改为更新其 expiresAt + refreshToken 并建立接替映射
  const origRemove = proto.removeToken;
  if (typeof origRemove !== 'function' || origRemove.__sfPatched) return;

  proto.removeToken = async function (oldToken) {
    // 读取并清空 _pendingNewToken（TTL 10s 保护，防止使用过期的 stale 值）
    const age = Date.now() - _pendingNewTokenAt;
    const newData = (age < PENDING_TTL_MS) ? _pendingNewToken : null;
    _pendingNewToken = null;

    const isSupersession = newData &&
      newData.token &&
      newData.token !== oldToken &&
      newData.extra && newData.extra.refreshToken;

    if (isSupersession) {
      try {
        const cache = this.storageDataCache && this.storageDataCache.tokens;
        const existing = cache && cache[oldToken];
        if (existing) {
          existing.expiresAt = newData.expiresAt;
          existing.extra = existing.extra || {};
          existing.extra.refreshToken = newData.extra.refreshToken;
          // 保留 appId/appSecret（oidc refreshToken 路径需要）
          if (newData.extra.appId) existing.extra.appId = newData.extra.appId;
          if (newData.extra.appSecret) existing.extra.appSecret = newData.extra.appSecret;
        }
        _supersededBy.set(oldToken, newData.token);
        // 持久化（让 lark-mcp 的文件监视器看到一致的状态）
        if (typeof this.saveToStorage === 'function') {
          await this.saveToStorage();
        }
        console.error(
          '[lark-mcp patch] token superseded:', oldToken.slice(0,8) + '…',
          '→', newData.token.slice(0,8) + '…'
        );
        return;  // 不真正删除旧条目
      } catch (e) {
        console.error('[lark-mcp patch] removeToken patch error, falling through:', e && e.message);
      }
    }

    return origRemove.call(this, oldToken);
  };
  proto.removeToken.__sfPatched = true;

  console.error('[lark-mcp patch] authStore patched (storeToken + removeToken)');
}

// ─── 补丁 2 · LarkOIDC2OAuthServerProvider.verifyAccessToken ────────────────
function patchOidc(LarkOIDCProvider) {
  const proto = LarkOIDCProvider && LarkOIDCProvider.prototype;
  const orig = proto && proto.verifyAccessToken;
  if (typeof orig !== 'function' || orig.__sfPatched) return;

  proto.verifyAccessToken = async function (token) {
    const result = await orig.call(this, token);
    if (!result) return result;

    const now = Date.now() / 1000;
    const isExpired = result.expiresAt && result.expiresAt < now;
    const hasRefreshToken = result.extra && result.extra.refreshToken;

    if (isExpired && hasRefreshToken) {
      // 对 HTTP 鉴权中间件伪装成"还有 2 分钟过期"，让请求通过
      // authStore 里的真实 expiresAt 不变，ensureGetUserAccessToken 仍能正确触发刷新
      return Object.assign({}, result, { expiresAt: now + 120 });
    }

    return result;
  };
  proto.verifyAccessToken.__sfPatched = true;

  console.error('[lark-mcp patch] LarkOIDC2OAuthServerProvider.verifyAccessToken patched (allow refresh via middleware)');
}

// ─── 补丁 3 · LarkMcpTool.ensureGetUserAccessToken ──────────────────────────
function patchMcpTool(LarkMcpTool) {
  const proto = LarkMcpTool && LarkMcpTool.prototype;
  const orig = proto && proto.ensureGetUserAccessToken;
  if (typeof orig !== 'function') {
    console.error('[lark-mcp patch] ensureGetUserAccessToken not found, skip (upstream changed?)');
    return;
  }
  if (orig.__singleFlight) return;

  // 第一层：single-flight 锁（防并发 20038）
  function sfWrapped() {
    if (this.__sfInflight) return this.__sfInflight;
    let p;
    try {
      p = Promise.resolve(orig.apply(this, arguments));
    } catch (e) {
      return Promise.reject(e);
    }
    this.__sfInflight = p;
    const clear = () => { this.__sfInflight = null; };
    p.then(clear, clear);
    return p;
  }
  sfWrapped.__singleFlight = true;

  // 第二层：supersession wrapper（把旧 bearer token 换成当前有效 token）
  proto.ensureGetUserAccessToken = async function () {
    const result = await sfWrapped.apply(this, arguments);
    if (result && result.userAccessToken) {
      let current = result.userAccessToken;
      let hops = 0;
      while (_supersededBy.has(current) && hops++ < 20) {
        current = _supersededBy.get(current);
      }
      if (current !== result.userAccessToken) {
        return Object.assign({}, result, { userAccessToken: current });
      }
    }
    return result;
  };
  proto.ensureGetUserAccessToken.__singleFlight = true;  // 标记防重入

  console.error('[lark-mcp patch] ensureGetUserAccessToken patched (single-flight + supersession chain)');
}
