/**
 * lark-mcp single-flight 注入补丁
 * =================================
 * 通过 `NODE_OPTIONS=--require <此文件>` 在 lark-mcp 进程启动时注入,给
 * `LarkMcpTool.prototype.ensureGetUserAccessToken` 包一层「单飞锁」。
 *
 * 根治的问题:
 *   lark-mcp 内部只有一个共享内存态 user_access_token,且 ensureGetUserAccessToken
 *   没有任何刷新去重。当 UAT 过期后,一波**并发**工具调用会各自拿同一个会轮换的
 *   refresh_token 去刷新 —— 第一个刷成功并把 refresh_token 轮换掉,其余的拿着已作废
 *   的旧值 → Lark 错误码 20038(refresh token invalid)。表现为「挂一段时间后第一次
 *   用就掉线、必须重登」。
 *
 * 修法:
 *   同一时刻只允许一个 ensureGetUserAccessToken 真正执行(发起刷新),并发的其余调用
 *   复用这同一个 in-flight Promise,拿同一个刷新结果。Token 没过期时该函数本就秒返,
 *   去重无副作用;只有「过期后那一瞬的并发」会被收敛成一次刷新 —— 自残从根上消失。
 *
 * 设计要点:
 *   - 在 LarkMcpTool 这一层打补丁(高于 oauth/oidc provider),OAuth 与 OIDC 两种
 *     domain 都覆盖。
 *   - 方法名不在(上游改版)就静默跳过,绝不让补丁本身把 server 带挂。
 *   - 锁状态挂在实例上(单实例场景=全局单飞)。
 */
'use strict';

const Module = require('module');

const TARGET_SUFFIX = 'mcp-tool/mcp-tool.js';
let patched = false;

const origLoad = Module._load;
Module._load = function (request, parent, isMain) {
  const exported = origLoad.apply(this, arguments);
  // 先用 request 字符串廉价过滤,避免对每个无关模块(尤其循环依赖中途)去摸 .LarkMcpTool
  // 触发 Node 的 circular-dependency 警告。
  if (patched || typeof request !== 'string' || request.indexOf('mcp-tool') === -1) {
    return exported;
  }
  if (!exported || !exported.LarkMcpTool) {
    return exported;
  }
  let filename = '';
  try {
    filename = Module._resolveFilename(request, parent, isMain);
  } catch (_) {
    return exported;
  }
  if (filename.replace(/\\/g, '/').endsWith(TARGET_SUFFIX) && filename.includes('lark-mcp')) {
    try {
      applyPatch(exported.LarkMcpTool);
      patched = true;
    } catch (e) {
      // 补丁失败也要让 server 正常起来,只打一行日志
      console.error('[lark-mcp singleflight] patch failed, run without it:', e && e.message);
    }
  }
  return exported;
};

function applyPatch(LarkMcpTool) {
  const proto = LarkMcpTool && LarkMcpTool.prototype;
  const orig = proto && proto.ensureGetUserAccessToken;
  if (typeof orig !== 'function') {
    console.error('[lark-mcp singleflight] ensureGetUserAccessToken not found, skip (upstream changed?)');
    return;
  }
  if (orig.__singleFlight) {
    return;
  }
  function wrapped() {
    // 已有在途调用 → 复用,不再发起第二次刷新
    if (this.__sfInflight) {
      return this.__sfInflight;
    }
    const args = arguments;
    let p;
    try {
      p = Promise.resolve(orig.apply(this, args));
    } catch (e) {
      return Promise.reject(e);
    }
    this.__sfInflight = p;
    const clear = () => { this.__sfInflight = null; };
    p.then(clear, clear);
    return p;
  }
  wrapped.__singleFlight = true;
  proto.ensureGetUserAccessToken = wrapped;
  console.error('[lark-mcp singleflight] ensureGetUserAccessToken patched (concurrent refresh collapsed to single-flight)');
}
