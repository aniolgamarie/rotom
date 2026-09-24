import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join, resolve } from "node:path";
import { homedir } from "node:os";
import { existsSync } from "node:fs";
import { readConfigForDirectory } from "../src/config.ts";

const root = fileURLToPath(new URL("..", import.meta.url)), args = process.argv.slice(2);
const position = args.indexOf("--config");
const configPath = position >= 0 ? resolve(args[position + 1] ?? "") : process.env.PI_TASK_KEEPER_CONFIG ?? join(process.env.PI_CODING_AGENT_DIR ?? join(homedir(), ".pi/agent"), "task-keeper.json");
if (position >= 0) { if (!args[position + 1]) throw new Error("--config requires a path"); args.splice(position, 2); }
const cwdPosition = args.indexOf("--cwd");
const cwd = cwdPosition >= 0 ? resolve(args[cwdPosition + 1] ?? "") : process.cwd();
if (cwdPosition >= 0) { if (!args[cwdPosition + 1]) throw new Error("--cwd requires a path"); args.splice(cwdPosition, 2); }
const config = readConfigForDirectory(configPath, cwd);
const cli = join(root, "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js");
if (!existsSync(cli)) throw new Error("Install the pinned development runtime with npm ci, then npm run prepare:adapters.");
const extensions = config.enabled && config.features.managedWorkflows ? ["-e", join(root, "node_modules/pi-subagents/index.ts")] : [];
const controlled = new Set(["-e", "--extension", "--extensions", "--no-extensions", "-ne"]);
if (args.some((arg) => controlled.has(arg) || arg.startsWith("--extension="))) throw new Error("This launcher owns the tested extension set; use a separate Pi launch for other profiles.");
const child = spawn(process.execPath, [cli, "--no-extensions", ...extensions, "-e", join(root, "index.ts"), ...args], {
  cwd, stdio: "inherit", env: { ...process.env, PI_TASK_KEEPER_CONFIG: configPath },
});
for (const signal of ["SIGINT", "SIGTERM"] as const) process.on(signal, () => child.kill(signal));
child.on("error", (error) => { console.error(error.message); process.exitCode = 1; });
child.on("exit", (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0); });
