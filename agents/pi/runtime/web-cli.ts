// 联网 CLI 复用 ordinary 命令监督；真实网络只由父进程的显式 Web 路线发出。
import { createHash, randomUUID } from "node:crypto";
import { mkdtemp, realpath, lstat, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, dirname, basename, resolve } from "node:path";
import { webConfig, webCredential, webCredentialDeclared } from "./web-config.ts";
import { createCliProxy } from "./web-cli-proxy.ts";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";

async function privateDirectory() {
  let base = await realpath(tmpdir());
  if (Buffer.byteLength(base) > 65) base = await realpath("/tmp");
  const path = await mkdtemp(join(base, "acw-")), identity = await lstat(path);
  return { path, async close() {
    let current;
    try { current = await lstat(path); } catch (error) { if (error.code === "ENOENT") return; throw error; }
    if (!current.isDirectory() || current.isSymbolicLink() || current.dev !== identity.dev || current.ino !== identity.ino) reject("WEB_CLI_DIRECTORY_CHANGED", 4);
    await rm(path, { recursive: true });
  } };
}

export async function webNetworkCommand(operation, input, { proxyFactory = createCliProxy, directoryFactory = privateDirectory,
    setTimer = setInterval, clearTimer = clearInterval } = {}) {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")], owner = runtime?.web?.current();
  requireOrdinaryHelper(runtime, "pi-web", owner?.id ?? null);
  if (!owner || !["youtube-info", "remote-frame", "git-clone"].includes(operation)) reject("WEB_CLI_OPERATION_INVALID", 2);
  const directory = await directoryFactory(); runtime.web.cleanup(() => directory.close());
  const service = operation === "git-clone" ? "github" : "public";
  const routeName = runtime.web.route(service, runtime.web.proxyScope?.getStore());
  const route = runtime.manifest.options.network?.routes?.[routeName];
  let authorization;
  if (route?.credential_ref) {
    authorization = process.env["AGENTCFG_PI_ROUTE_CREDENTIAL_" + createHash("sha256").update(routeName).digest("hex").slice(0, 16).toUpperCase()];
    if (!authorization || /[\x00-\x1f\x7f]/.test(authorization)) reject("WEB_PROXY_CREDENTIAL_REQUIRED", 3);
  }
  let ticket, timer, polling, stdout;
  const controller = new AbortController(), signal = AbortSignal.any([owner.controller.signal, controller.signal]);
  const authorizationState = async () => {
    const result = await runtime.supervisor.call("ordinary_web_cli_authorize", { operation_id: ticket.operation_id });
    if (typeof result.valid !== "boolean" || typeof result.revoked !== "boolean") reject("WEB_CLI_AUTHORIZATION_INVALID", 5);
    if (result.revoked) controller.abort();
    return result;
  };
  const authorize = async () => !!ticket && (await authorizationState()).valid === true;
  const proxy = await proxyFactory(runtime, service, join(directory.path, "proxy.sock"), { routeName, authorization, authorize });
  try {
    const configured = operation === "git-clone" ? webConfig().githubToken : null;
    const credential = webCredentialDeclared(configured) ? "Basic " + Buffer.from("x-access-token:" + webCredential(configured, signal)).toString("base64") : null;
    ticket = await runtime.supervisor.call("ordinary_web_cli_prepare", { operation_id: randomUUID(), operation, input, socket_path: proxy.socketPath, token: proxy.token,
      ...(operation === "git-clone" ? { cwd: runtime.cwd, ...(credential ? { github_authorization: credential } : {}) } : {}) });
    runtime.web.verifyExternal(async () => {
      const proof = await runtime.supervisor.call("reconcile", { lease_id: ticket.lease_id });
      return proof.lease_id === ticket.lease_id && !proof.protected && proof.termination_evidence?.verified === true;
    });
    runtime.web.cleanup(() => runtime.supervisor.call("ordinary_command_finish", { operation_id: ticket.operation_id }));
    const result = await runtime.web.track(runtime.ordinaryOperations.write(ticket, null, null, signal, {
      onCapture(value) { stdout = value.stdout; },
      onStarted() {
        timer = setTimer(() => {
          if (polling) return;
          polling = authorize().then(valid => { if (!valid) return proxy.close(); }).catch(() => {
            controller.abort(); return proxy.close();
          }).finally(() => { polling = null; });
          void polling.catch(() => {});
        }, 200);
        timer?.unref?.();
      },
    }));
    if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== runtime) reject("WEB_CLI_STALE", 4);
    runtime.web.current();
    await authorizationState();
    if (!result.terminationConfirmed || result.truncated || result.exitCode !== 0 || signal.aborted) reject("WEB_CLI_FAILED", 5);
    if (operation === "git-clone") {
      const binding = runtime.manifest.options.web?.github_clone;
      const root = runtime.manifest.options.paths?.roots?.[binding?.root_ref]?.path;
      if (typeof ticket.destination !== "string" || !root || dirname(ticket.destination) !== resolve(root)
          || !/^clone-[0-9a-f]{32}$/.test(basename(ticket.destination))) reject("WEB_GITHUB_DESTINATION_INVALID", 5);
    }
    return { ...result, bytes: stdout, ...(operation === "git-clone" ? { destination: ticket.destination } : {}) };
  } finally {
    clearTimer(timer);
    await proxy.close();
    await polling;
  }
}

export async function webYouTubeInfo(videoId) {
  const result = await webNetworkCommand("youtube-info", { video_id: videoId });
  let value;
  try { value = JSON.parse(result.stdout); } catch { reject("WEB_YOUTUBE_RESPONSE_INVALID", 5); }
  if (!value || typeof value.url !== "string" || value.url.length > 16384 || /[\x00-\x1f\x7f]/.test(value.url)
      || value.duration !== null && (typeof value.duration !== "number" || !Number.isFinite(value.duration) || value.duration < 0)) reject("WEB_YOUTUBE_RESPONSE_INVALID", 5);
  let url;
  try { url = new URL(value.url); } catch { reject("WEB_YOUTUBE_RESPONSE_INVALID", 5); }
  if (url.protocol !== "https:" || url.username || url.password || url.port && url.port !== "443" || url.hash) reject("WEB_YOUTUBE_RESPONSE_INVALID", 5);
  return { streamUrl: value.url, duration: value.duration };
}

export async function webRemoteFrame(url, seconds) {
  const result = await webNetworkCommand("remote-frame", { url, seconds }), bytes = result.bytes;
  if (!Buffer.isBuffer(bytes) || bytes.length < 4 || bytes.length > 5 * 1024 * 1024
      || bytes[0] !== 0xff || bytes[1] !== 0xd8 || bytes.at(-2) !== 0xff || bytes.at(-1) !== 0xd9) reject("WEB_MEDIA_FRAME_INVALID", 5);
  return { data: bytes.toString("base64"), mimeType: "image/jpeg" };
}

export async function webGitClone(owner, repo, ref) {
  return (await webNetworkCommand("git-clone", { owner, repo, ...(ref === undefined ? {} : { ref }) })).destination;
}

export async function webGitContent(directory, type, path = "") {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")], owner = runtime?.web?.current();
  requireOrdinaryHelper(runtime, "pi-web", owner?.id ?? null);
  const result = await runtime.supervisor.call("ordinary_web_git_content", { cwd: runtime.cwd, directory, type, path });
  runtime.web.current();
  if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== runtime || typeof result.content !== "string" || result.content.length > 1024 * 1024) reject("WEB_GITHUB_CONTENT_INVALID", 5);
  return result.content;
}
