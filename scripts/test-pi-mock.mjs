#!/usr/bin/env node
// 默认插件测试只允许显式测试文件和临时 HOME；不运行 Pi 宿主。
import { existsSync, mkdtempSync, mkdirSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const names = process.argv.slice(2);
if (!names.length) {
  process.stderr.write("Provide explicit mock test paths.\n");
  process.exit(2);
}
const files = names.map(name => realpathSync(resolve(root, name)));
if (files.some(file => {
  const rel = relative(root, file);
  return isAbsolute(rel) || rel.startsWith("..") || !/\.test\.(mjs|js|ts)$/.test(file);
})) {
  process.stderr.write("Mock tests must be repository test files.\n");
  process.exit(2);
}
const temporary = mkdtempSync(join(tmpdir(), "agentcfg-pi-mock-"));
const home = join(temporary, "home");
mkdirSync(home, { mode: 0o700 });
const env = {
  HOME: home, PATH: join(temporary, "empty-bin"), TMPDIR: temporary,
  PI_CODING_AGENT_DIR: join(home, "pi"), PI_CODING_AGENT_SESSION_DIR: join(home, "sessions"),
  CODEX_HOME: join(home, "codex"), DSH_HOME: join(home, "dsh"),
  XDG_CONFIG_HOME: join(home, "config"), XDG_DATA_HOME: join(home, "data"),
  XDG_STATE_HOME: join(home, "state"), XDG_CACHE_HOME: join(home, "cache"),
};
let result;
try {
  const entry = ["--import", join(root, "tests/fixtures/pi/mock-guard.mjs"),
    join(root, "tests/fixtures/pi/mock-entry.mjs"), ...files];
  if (process.platform === "linux" && existsSync("/usr/bin/bwrap")) {
    // 新版 Node 权限模式禁止 fsync/symlink；由 OS 保持更窄的文件边界，再允许这些真实临时文件操作。
    const mounts = ["--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"];
    for (const path of ["/usr", "/bin", "/lib", "/lib64"]) if (existsSync(path)) mounts.push("--ro-bind", path, path);
    if (existsSync("/etc/ld.so.cache")) mounts.push("--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache");
    const node = realpathSync(process.execPath);
    mounts.push("--ro-bind", root, root, "--ro-bind", node, node, "--bind", temporary, temporary, "--chdir", temporary);
    result = spawnSync("/usr/bin/bwrap", [...mounts, "--", node, ...entry],
      { cwd: temporary, env, stdio: "inherit" });
  } else {
    result = spawnSync(process.execPath, ["--permission", `--allow-fs-read=${root}`,
      `--allow-fs-read=${temporary}`, `--allow-fs-write=${temporary}`, ...entry], { cwd: temporary, env, stdio: "inherit" });
  }
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
process.exit(result?.status ?? 1);
