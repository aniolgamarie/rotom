// 实网工作流只操作显式准备的合成项目；源码标记不符时不派发模型请求。
import { randomUUID } from "node:crypto";
import { constants, openSync, fstatSync, readFileSync, closeSync } from "node:fs";
import { join } from "node:path";
import { privateFile, writePrivate } from "./launch.ts";
import { nativeCommand } from "./native-validation.ts";
import { reject } from "./managed-types.ts";

async function until(read, ready, milliseconds = 600000) {
  const deadline = Date.now() + milliseconds;
  while (Date.now() < deadline) { const value = await read(); if (ready(value)) return value; await new Promise(resolve => setTimeout(resolve, 250)); }
  reject("SERVICE_VALIDATION_MANAGED_TIMEOUT", 5);
}

function candidateText(path) {
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.nlink !== 1 || info.uid !== process.getuid() || info.size > 1024 || (info.mode & 0o022)) reject("SERVICE_VALIDATION_FIX_UNVERIFIED", 5);
    return readFileSync(fd, "utf8");
  } finally { closeSync(fd); }
}

export async function exerciseManaged(host, input) {
  const project = input.project, source = join(project, "code.txt");
  const marker = JSON.parse(privateFile(join(project, "agentcfg-live-project.json")));
  if (marker.schema_version !== 1 || marker.kind !== "agentcfg-live-managed" || privateFile(source) !== "changed\n") reject("SERVICE_VALIDATION_PROBE_PROJECT", 4);
  const runner = host.session.extensionRunner, tool = runner.getToolDefinition("kernel_task"), command = runner.getCommand("orch");
  const entry = globalThis[Symbol.for("agentcfg.pi.managed.v1")];
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!tool || !command || !entry?.manager) reject("SERVICE_VALIDATION_TASKKEEPER_MISSING", 5);
  const status = async id => (await tool.execute(randomUUID(), { action: "status", ...(id ? { jobId: id } : {}) }, new AbortController().signal, undefined, runner.createContext())).details;
  const control = text => nativeCommand(host.session, runner, command, text);
  const jobs = [];
  let changed = false, completed = false;
  const dispatch = async (text, reviewId) => {
    const before = new Set((await status()).map(row => row.id));
    await control(text);
    const created = (await status()).filter(row => !before.has(row.id));
    if (created.length !== 1) reject("SERVICE_VALIDATION_MANAGED_SUBMISSION", 5);
    jobs.push(created[0].id);
    const result = await until(() => status(created[0].id), value => ["COMPLETED", "BLOCKED", "PARTIAL", "CANCELLED", "WAITING_QUOTA"].includes(value.status));
    const checks = runtime.manifest.options.task_keeper.check_ids;
    if (result.status !== "COMPLETED" || !result.receipt || result.receipt.snapshot !== result.snapshot || !checks?.length
        || checks.some(id => !result.checks?.some(row => row.checkId === id && row.source === "verifier" && row.snapshot === result.snapshot
          && row.status === "passed" && row.artifactId))) reject("SERVICE_VALIDATION_MANAGED_RECEIPT", 5);
    if (!result.checks.some(row => row.checkId === reviewId && row.source === "reviewer" && row.status === "passed"
        && row.snapshot === result.snapshot && row.specVersion === result.receipt.specVersion && row.artifactId)) reject("SERVICE_VALIDATION_MANAGED_REVIEW", 5);
    await until(async () => entry.manager.hasRunning(), running => !running, 30000);
    return result;
  };
  try {
    await dispatch("inspect -- Inspect code.txt and verify the configured checks. Do not modify files. Use the required structured result.", "scope-evidence-review");
    if (privateFile(source) !== "changed\n") reject("SERVICE_VALIDATION_SOURCE_CHANGED", 4);
    // 此文件由显式 prepare-live-project 创建；所有任务停止后才进入下一组已知坏输入。
    writePrivate(source, "original\n"); changed = true;
    const result = await dispatch("fix" + (input.variant === "second-view" ? " --second-opinion" : "")
      + " -- The tests require code.txt to contain exactly changed followed by a newline. Fix only code.txt, run the configured checks, and complete required review with structured evidence.", "independent-review");
    if (candidateText(join(result.cwd, "code.txt")) !== "changed\n" || privateFile(source) !== "original\n") reject("SERVICE_VALIDATION_FIX_UNVERIFIED", 5);
    if (input.variant === "second-view" && result.secondOpinion?.agreementCurrent !== true) reject("SERVICE_VALIDATION_SECOND_VIEW", 5);
    completed = true;
    return { sdk_session: true, capability: "task-keeper", inspect_verified: true, fix_verified: true, checks_verified: true,
      review_verified: true, second_view_verified: input.variant === "second-view", job_count: jobs.length };
  } finally {
    if (!completed) {
      for (const id of jobs) {
        try { if (!["COMPLETED", "CANCELLED"].includes((await status(id)).status)) await control("stop " + id); } catch {}
      }
    }
    await until(async () => entry.manager.hasRunning(), running => !running, 30000);
    if (changed) {
      if (privateFile(source) !== "original\n") reject("SERVICE_VALIDATION_SOURCE_CHANGED", 4);
      writePrivate(source, "changed\n");
    }
  }
}
