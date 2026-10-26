// 仅供受控候选核验：调用公开 stat 读取 header，不创建 Agent/句柄或证明加载。
// 调用方仍须核验完整运行包、配置/root/租约并提供隔离环境；此脚本不构成能力准入。
import { realpath } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const absolute = value => typeof value === "string" && value.length > 0 && value.length <= 4096
  && !value.includes("\0") && path.isAbsolute(value) && path.normalize(value) === value;
const sessionId = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(value);
const unavailable = () => ({ status: "unavailable" });

export async function queryMetadata(api, root, id) {
  if (!absolute(root) || !sessionId(id)) return unavailable();
  let context;
  let result = unavailable();
  try {
    context = new api.Context();
    await context.plugin(api.JsonlSessionPersistence, { root });
    const snapshot = await context.sessionPersistence.stat(api.SessionId(id));
    const header = snapshot?.header;
    if (header?.id === id && absolute(header.cwd)) {
      // 不复制标题、事件、revision原文或其它不需要的原生字段；无实际run可在此关联。
      result = { status: "metadata", session_id: id, cwd: header.cwd, source: "session-persistence-stat" };
    }
  } catch {
    // 缺失、损坏、重复ID或服务失败均保持不可核实；绝不回显原生异常正文。
    result = unavailable();
  } finally {
    if (context) {
      try { await context.fiber.dispose(); } catch { result = unavailable(); }
    }
  }
  return result;
}

export async function queryFromRuntime(runtimeRoot, root, id) {
  if (!absolute(runtimeRoot) || !absolute(root) || !sessionId(id)) return unavailable();
  try {
    const modules = await realpath(path.join(runtimeRoot, "node_modules"));
    const require = createRequire(path.join(runtimeRoot, "package.json"));
    const load = async name => {
      // 只使用公开 package export；不允许 Node 向上回落到另一棵安装树。
      const resolved = await realpath(require.resolve(name));
      const relative = path.relative(modules, resolved);
      if (!relative || relative.startsWith(".." + path.sep) || path.isAbsolute(relative)) throw Error("unavailable");
      return import(pathToFileURL(resolved).href);
    };
    const { Context } = await load("@deepseek-ai/cordis");
    const { SessionId } = await load("@deepseek-ai/dsh-session");
    const JsonlSessionPersistence = await load("@deepseek-ai/dsh-session-persistence-jsonl");
    return queryMetadata({ Context, SessionId, JsonlSessionPersistence }, root, id);
  } catch {
    return unavailable();
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const result = args.length === 3 ? await queryFromRuntime(...args) : unavailable();
  process.stdout.write(JSON.stringify(result) + "\n");
  process.exitCode = result.status === "metadata" ? 0 : 5;
}
