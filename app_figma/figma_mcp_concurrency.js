// figma-developer-mcp 的并发/限流 preload(经 NODE_OPTIONS=--require 注入)。
//
// 背景:figma-developer-mcp@0.12 对 api.figma.com 既不限并发也不退避重试。AI 一次发
// 多个 tool call → 进程并发 N 个 fetch 打到 Figma REST → 命中按 token 的成本限流(尤其
// /images 渲染极严)→ 429 直接抛给 AI,整批失败。
//
// 这里把 globalThis.fetch 包一层:只对 api.figma.com 的请求
//   1) 走并发闸(默认串行 1,FIGMA_MAX_CONCURRENCY 可调);
//   2) 相邻请求保最小间隔(默认 350ms,FIGMA_MIN_INTERVAL_MS 可调),削突发;
//   3) 命中 429/5xx 时指数退避重试(默认 4 次),并尊重响应里的 Retry-After。
// 其余请求(遥测、本机等)原样透传,零影响。方法不在/环境不支持时静默跳过,不影响启动。

(function () {
  "use strict";

  var realFetch = globalThis.fetch;
  if (typeof realFetch !== "function") return; // 老 Node 无全局 fetch:放弃打补丁,不报错

  function intEnv(name, dflt) {
    var v = parseInt(process.env[name] || "", 10);
    return isNaN(v) ? dflt : v;
  }

  var MAX_CONC = Math.max(1, intEnv("FIGMA_MAX_CONCURRENCY", 1));
  var MIN_GAP_MS = Math.max(0, intEnv("FIGMA_MIN_INTERVAL_MS", 350));
  var MAX_RETRY = Math.max(0, intEnv("FIGMA_MAX_RETRY", 4));
  var BASE_BACKOFF_MS = 1000;
  var MAX_BACKOFF_MS = 30000;

  var active = 0;
  var lastStart = 0;
  var waiters = [];

  function isFigma(input) {
    try {
      var u =
        typeof input === "string"
          ? input
          : input && input.url
          ? input.url
          : String(input);
      return u.indexOf("api.figma.com") !== -1;
    } catch (e) {
      return false;
    }
  }

  function acquire() {
    return new Promise(function (resolve) {
      function run() {
        if (active < MAX_CONC) {
          active++;
          resolve();
        } else {
          waiters.push(run);
        }
      }
      run();
    });
  }

  function release() {
    if (active > 0) active--;
    var next = waiters.shift();
    if (next) next();
  }

  function sleep(ms) {
    return new Promise(function (r) {
      setTimeout(r, ms);
    });
  }

  // 全进程相邻请求保最小间隔(持锁状态下调用,天然不并发)
  async function gap() {
    if (!MIN_GAP_MS) return;
    var wait = lastStart + MIN_GAP_MS - Date.now();
    if (wait > 0) await sleep(wait);
    lastStart = Date.now();
  }

  function retryAfterMs(res) {
    try {
      var ra = res.headers && res.headers.get ? res.headers.get("retry-after") : null;
      if (!ra) return 0;
      var secs = parseInt(ra, 10);
      return isNaN(secs) ? 0 : Math.max(0, secs * 1000);
    } catch (e) {
      return 0;
    }
  }

  globalThis.fetch = function patchedFetch(input, init) {
    if (!isFigma(input)) return realFetch(input, init);

    return (async function () {
      await acquire();
      try {
        var attempt = 0;
        for (;;) {
          await gap();
          var res = await realFetch(input, init);
          // 仅对 429 / 5xx 退避重试;其余(含 4xx 鉴权错)立即返回交上游处理
          if (res.status !== 429 && res.status < 500) return res;
          if (attempt >= MAX_RETRY) return res; // 退避用尽:把原始响应交还,让上游报它的 429 文案

          var backoff = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * Math.pow(2, attempt));
          var waitMs = Math.max(backoff, retryAfterMs(res));
          attempt++;
          // 退避期间继续持锁:避免队列里其他请求此刻涌出,反而加重限流
          await sleep(waitMs);
        }
      } finally {
        release();
      }
    })();
  };
})();
