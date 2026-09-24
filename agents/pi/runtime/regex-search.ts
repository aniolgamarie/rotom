// V8正则在可终止线程中运行，不能阻塞 supervisor 的撤权与终止核验。
import { Worker } from "node:worker_threads";
import { reject } from "./managed-types.ts";

export async function searchText(request, { createWorker = (url, options) => new Worker(url, options), timeout = 1000 } = {}) {
  if (typeof request.pattern !== "string" || !request.pattern || request.pattern.length > 4096
      || typeof request.text !== "string" || request.text.length > 1024 * 1024
      || !Number.isSafeInteger(request.limit) || request.limit < 1 || request.limit > 1000
      || !Number.isSafeInteger(request.context) || request.context < 0 || request.context > 100) reject("SEARCH_ARGUMENT_INVALID", 2);
  const worker = createWorker(new URL("./regex-worker.ts", import.meta.url), { workerData: request });
  let timer;
  try {
    return await new Promise((resolve, fail) => {
      timer = setTimeout(() => fail(new Error("SEARCH_TIMEOUT")), timeout);
      worker.once("message", result => result?.ok === true ? resolve(result.matches) : fail(new Error("SEARCH_PATTERN_INVALID")));
      worker.once("error", () => fail(new Error("SEARCH_WORKER_FAILED")));
      worker.once("exit", code => { if (code !== 0) fail(new Error("SEARCH_WORKER_FAILED")); });
    });
  } finally { clearTimeout(timer); await worker.terminate(); }
}
