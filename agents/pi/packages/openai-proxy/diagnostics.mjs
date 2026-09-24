import { Dispatcher } from "undici";

function counters() {
  return { requests: 0, completed: 0, failures: 0, cancellations: 0, uploadBytes: 0, downloadBytes: 0, upgrades: 0, statuses: {}, hosts: [], lastError: null };
}

export function createDiagnostics() {
  return { total: counters(), active: null, last: null };
}

export function beginRound(diagnostics) {
  // Retries may start another agent loop before the user request has settled.
  diagnostics.active ??= { ...counters(), startedAt: Date.now() };
  return diagnostics.active;
}

export function finishRound(diagnostics) {
  if (!diagnostics.active) return null;
  const round = diagnostics.active;
  diagnostics.active = null;
  diagnostics.last = round;
  return { ...snapshot(round), durationMs: Date.now() - round.startedAt };
}

export function snapshot(stats) {
  return { ...stats, statuses: { ...stats.statuses }, hosts: [...stats.hosts], pending: stats.requests - stats.completed };
}

function safeErrorCode(error) {
  let code = "NETWORK_ERROR";
  for (let current = error, depth = 0; current && depth < 8; current = current.cause, depth++) {
    if (typeof current.code === "string" && /^[A-Z][A-Z0-9_]{0,63}$/.test(current.code)) code = current.code;
  }
  return code;
}

function isCancellation(error) {
  for (let current = error, depth = 0; current && depth < 8; current = current.cause, depth++) {
    if (current.name === "AbortError" || current.code === "UND_ERR_ABORTED") return true;
  }
  return false;
}

/** Count bytes at Undici's body callbacks, without reading or cloning streams. */
export class MeteredProxyDispatcher extends Dispatcher {
  constructor(proxy, diagnostics) {
    super();
    this.proxy = proxy;
    this.diagnostics = diagnostics;
  }

  dispatch(options, handler) {
    // Bind the request to the round in which it STARTED. Late callbacks never
    // leak into the next round. Background requests only contribute to total.
    const targets = [this.diagnostics.total, this.diagnostics.active].filter(Boolean);
    const host = new URL(options.origin).hostname;
    const add = (field, amount = 1) => { for (const stats of targets) stats[field] += amount; };
    for (const stats of targets) {
      stats.requests++;
      if (!stats.hosts.includes(host) && stats.hosts.length < 8) stats.hosts.push(host);
    }
    let finished = false;
    let status = 0;
    const finish = (error) => {
      if (finished) return;
      finished = true;
      add("completed");
      // Pi cancels the reader after response.completed, before HTTP EOF. That
      // is normal SSE cleanup, indistinguishable here from a user cancellation.
      const cancelled = error && isCancellation(error);
      if (cancelled) add("cancellations");
      if ((error && !cancelled) || status >= 400) add("failures");
      if (error && !cancelled) for (const stats of targets) stats.lastError = safeErrorCode(error);
    };
    const wrapped = {
      onRequestStart: (...args) => handler.onRequestStart?.(...args),
      onResponseStarted: (...args) => handler.onResponseStarted?.(...args),
      onBodySent: (chunk) => {
        add("uploadBytes", Buffer.byteLength(chunk));
        return handler.onBodySent?.(chunk);
      },
      onRequestSent: (...args) => handler.onRequestSent?.(...args),
      onResponseStart: (controller, code, ...rest) => {
        status = code;
        for (const stats of targets) stats.statuses[code] = (stats.statuses[code] ?? 0) + 1;
        return handler.onResponseStart?.(controller, code, ...rest);
      },
      onResponseData: (controller, chunk) => {
        add("downloadBytes", Buffer.byteLength(chunk));
        return handler.onResponseData?.(controller, chunk);
      },
      onResponseEnd: (...args) => {
        finish();
        return handler.onResponseEnd?.(...args);
      },
      onResponseError: (controller, error) => {
        finish(error);
        return handler.onResponseError?.(controller, error);
      },
      onRequestUpgrade: (...args) => {
        add("upgrades");
        finish();
        return handler.onRequestUpgrade?.(...args);
      },
    };
    try {
      return this.proxy.dispatch(options, wrapped);
    } catch (error) {
      finish(error);
      throw error;
    }
  }

  close(...args) { return this.proxy.close(...args); }
  destroy(...args) { return this.proxy.destroy(...args); }
}

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 ** 2).toFixed(2)} MiB`;
}

export function formatSummary(stats, label = "本轮") {
  if (!stats.requests) return `OpenAI 代理 · ${label}未观测到代理请求`;
  const statuses = Object.entries(stats.statuses).map(([code, count]) => `${code}×${count}`).join(" / ");
  return [
    `OpenAI 代理 · ${label} ${stats.requests} 请求`,
    `↑ ${formatBytes(stats.uploadBytes)} ↓ ${formatBytes(stats.downloadBytes)}（HTTP 正文）`,
    statuses ? `HTTP ${statuses}` : "未收到 HTTP 响应",
    stats.failures ? `失败 ${stats.failures}${stats.lastError ? `（${stats.lastError}）` : ""}` : null,
    stats.pending ? `未结束 ${stats.pending}` : null,
    stats.upgrades ? "WebSocket 帧流量未计入" : null,
  ].filter(Boolean).join(" · ");
}
