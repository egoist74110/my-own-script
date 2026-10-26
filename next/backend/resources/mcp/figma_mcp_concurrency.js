/**
 * Figma MCP Concurrency & Rate-Limit Wrapper
 * Loaded via NODE_OPTIONS="--require .../figma_mcp_concurrency.js"
 *
 * Wraps globalThis.fetch for api.figma.com:
 *   1. Limits concurrent requests (FIGMA_MAX_CONCURRENCY, default 2)
 *   2. Enforces minimum interval between requests (FIGMA_MIN_INTERVAL_MS, default 350)
 *   3. Retries 429 / 502 / 503 / 504 with Retry-After or exponential backoff (FIGMA_MAX_RETRY, default 4)
 */

"use strict";

(function () {
  if (typeof globalThis.fetch !== "function" || globalThis.fetch.__toolboxFigmaPatched) {
    return;
  }

  const MAX_CONCURRENCY = Math.max(
    1,
    parseInt(process.env.FIGMA_MAX_CONCURRENCY || "2", 10) || 2
  );
  const MIN_INTERVAL_MS = Math.max(
    0,
    parseInt(process.env.FIGMA_MIN_INTERVAL_MS || "350", 10) || 350
  );
  const MAX_RETRY = Math.max(
    0,
    parseInt(process.env.FIGMA_MAX_RETRY || "4", 10) || 4
  );
  const BASE_BACKOFF_MS = 1000;
  const MAX_BACKOFF_MS = 30000;

  const origFetch = globalThis.fetch.bind(globalThis);
  let active = 0;
  let lastStartAt = 0;
  const queue = [];

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function acquire() {
    return new Promise((resolve) => {
      queue.push(resolve);
      pump();
    });
  }

  function release() {
    active = Math.max(0, active - 1);
    pump();
  }

  function pump() {
    if (active >= MAX_CONCURRENCY || queue.length === 0) {
      return;
    }
    const now = Date.now();
    const waitMs = Math.max(0, lastStartAt + MIN_INTERVAL_MS - now);
    active += 1;
    const next = queue.shift();
    if (waitMs === 0) {
      lastStartAt = Date.now();
      next();
    } else {
      lastStartAt = now + waitMs;
      setTimeout(next, waitMs);
    }
  }

  function extractUrl(input) {
    if (typeof input === "string") {
      return input;
    }
    if (input && typeof input.url === "string") {
      return input.url;
    }
    if (input && typeof input.href === "string") {
      return input.href;
    }
    return "";
  }

  function isFigmaApi(input) {
    const url = extractUrl(input);
    return url.includes("api.figma.com");
  }

  function parseRetryAfterMs(headerVal) {
    if (!headerVal) {
      return 0;
    }
    const seconds = Number(headerVal);
    if (Number.isFinite(seconds) && seconds > 0) {
      return Math.min(MAX_BACKOFF_MS, Math.ceil(seconds * 1000));
    }
    const dateMs = Date.parse(headerVal);
    if (Number.isFinite(dateMs)) {
      const diff = dateMs - Date.now();
      if (diff > 0) {
        return Math.min(MAX_BACKOFF_MS, diff);
      }
    }
    return 0;
  }

  async function fetchWithRetry(input, init) {
    let attempt = 0;
    while (true) {
      await acquire();
      let response;
      try {
        response = await origFetch(input, init);
      } finally {
        release();
      }
      const status = response && response.status;
      const retryable =
        status === 429 || status === 502 || status === 503 || status === 504;
      if (!retryable || attempt >= MAX_RETRY) {
        return response;
      }
      let retryMs = 0;
      try {
        retryMs = parseRetryAfterMs(
          response.headers && response.headers.get && response.headers.get("retry-after")
        );
      } catch (_err) {
        // ignore
      }
      if (!retryMs) {
        const exp = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * Math.pow(2, attempt));
        const jitter = Math.floor(Math.random() * 250);
        retryMs = Math.min(MAX_BACKOFF_MS, exp + jitter);
      }
      attempt += 1;
      await sleep(retryMs);
    }
  }

  const wrappedFetch = function (input, init) {
    if (!isFigmaApi(input)) {
      return origFetch(input, init);
    }
    return fetchWithRetry(input, init);
  };
  wrappedFetch.__toolboxFigmaPatched = true;
  globalThis.fetch = wrappedFetch;
})();
