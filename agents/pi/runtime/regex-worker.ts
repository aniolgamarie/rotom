// 固定纯计算线程：模型只提供模式和文本，不能提供脚本或模块路径。
import { parentPort, workerData } from "node:worker_threads";
try {
  const { pattern, literal, ignoreCase, text, limit, context } = workerData;
  const regexp = literal ? null : new RegExp(pattern, ignoreCase ? "iu" : "u");
  const needle = ignoreCase ? pattern.toLocaleLowerCase() : pattern;
  const lines = text.split(/\r?\n/), matches = [];
  for (let index = 0; index < lines.length; index++) {
    const found = regexp ? regexp.test(lines[index]) : (ignoreCase ? lines[index].toLocaleLowerCase() : lines[index]).includes(needle);
    if (found) {
      matches.push({ line: index + 1, text: lines[index].slice(0, 2048), context: lines.slice(Math.max(0, index - context), index + context + 1).map(line => line.slice(0, 2048)) });
      if (matches.length >= limit) break;
    }
  }
  parentPort.postMessage({ ok: true, matches });
} catch { parentPort.postMessage({ ok: false, code: "SEARCH_PATTERN_INVALID" }); }
