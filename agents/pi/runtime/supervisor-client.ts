// SDK/worker 仅通过已授予的私有通道访问监督者；不根据环境任意寻找全局宿主。
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { isAbsolute } from "node:path";
import { canonical, closed, ProtocolError, reject, text } from "./managed-types.ts";

const maxFrame = 1024 * 1024;
const codexAdmissionCodes = new Set(["CODEX_SYSTEM_CONFIG_PRESENT", "CODEX_SYSTEM_CONFIG_UNVERIFIED",
  "CODEX_MANAGED_PREFERENCES_PRESENT", "CODEX_MANAGED_PREFERENCES_UNVERIFIED", "CODEX_ACCOUNT_CONFIG_UNVERIFIED",
  "CODEX_ORGANIZATION_ACCOUNT_UNSUPPORTED", "CODEX_CONFIG_PLATFORM_UNSUPPORTED", "CODEX_LOGIN_CONFIG_UNVERIFIED"]);

function invokeProcess({ python, client, endpoint, capability, request, timeout }) {
  return new Promise((resolveDone, rejectDone) => {
    const child = spawn(python, ["-I", client], { stdio: ["pipe", "pipe", "pipe"],
      env: { HOME: process.env.HOME ?? "/", PATH: process.env.PATH ?? "/usr/bin:/bin",
        AGENTCFG_SUPERVISOR_ENDPOINT: endpoint, AGENTCFG_SUPERVISOR_CAPABILITY: capability } });
    const chunks = [];
    let bytes = 0, failed = false;
    const fail = () => {
      if (failed) return;
      failed = true;
      child.kill();
      rejectDone(new ProtocolError("PI_CONTROL_UNAVAILABLE", 4));
    };
    const timer = setTimeout(fail, timeout);
    child.stdout.on("data", chunk => { bytes += chunk.length; if (bytes > maxFrame) fail(); else chunks.push(chunk); });
    child.stderr.on("data", () => {});
    child.on("error", fail);
    child.stdin.on("error", fail);
    child.on("close", code => {
      clearTimeout(timer);
      if (failed) return;
      if (code !== 0) { fail(); return; }
      resolveDone(Buffer.concat(chunks).toString("utf8"));
    });
    child.stdin.end(canonical(request) + "\n");
  });
}

export class SupervisorClient {
  constructor({ python, client, endpoint, capability, invoke = invokeProcess, timeout = 30000 }) {
    if (![python, client, endpoint].every(value => text(value) && isAbsolute(value)) || !text(capability)
        || !Number.isSafeInteger(timeout) || timeout < 1 || timeout > 30000) reject();
    this.options = { python, client, endpoint, capability, timeout };
    this.invoke = invoke;
  }
  async call(method, args) {
    if (!text(method)) reject();
    const request = { schema_version: 1, request_id: randomUUID(), method, args };
    if (Buffer.byteLength(canonical(request)) + 1 > maxFrame) reject("PI_CONTROL_FRAME_LIMIT", 2);
    let response;
    try { response = JSON.parse(await this.invoke({ ...this.options, request })); }
    catch { throw new ProtocolError("PI_CONTROL_UNAVAILABLE", 4); }
    if (response?.ok === true) {
      closed(response, ["schema_version", "ok", "result"]);
      if (response.schema_version !== 1) reject();
      return response.result;
    }
    if (response?.ok === false) {
      closed(response, ["schema_version", "ok", "exit_code", "error"]);
      if (response.schema_version !== 1 || ![2, 3, 4, 5, 6].includes(response.exit_code)) reject();
      throw new ProtocolError(codexAdmissionCodes.has(response.error) || response.error === "ORDINARY_STDIN_BACKPRESSURE" ? response.error : "PI_CONTROL_REJECTED", response.exit_code);
    }
    reject("PI_CONTROL_UNAVAILABLE", 4);
  }
}
