// 用户批次命令的私有传输端点；所有执行仍提交给现有管理者。
import net from "node:net";
import { chmodSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, rmdirSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { canonical, closed, digest, isProtocolError, reject } from "./managed-types.ts";
import { writePrivate } from "./launch.ts";

export async function externalControl({ runtime, bridge, root, createServer = net.createServer, socketRoot = "/tmp" }) {
  mkdirSync(root, { recursive: true, mode: 0o700 });
  const directory = mkdtempSync(join(socketRoot, "agentcfg-delegate-")); chmodSync(directory, 0o700);
  const socket = join(directory, "control.sock"), capability = randomBytes(32).toString("hex"), owner = bridge.owner;
  const connections = new Set();
  const server = createServer(connection => {
    connections.add(connection);
    connection.once("close", () => connections.delete(connection));
    connection.on("error", () => connection.destroy());
    let text = "", finished = false, bytes = 0;
    const decoder = new TextDecoder("utf8", { fatal: true });
    connection.setTimeout(30000, () => connection.destroy());
    connection.on("data", chunk => {
      if (finished) return;
      bytes += chunk.length;
      try { text += decoder.decode(chunk, { stream: true }); } catch { connection.destroy(); return; }
      if (bytes > 1024 * 1024) { connection.destroy(); return; }
      if (!text.endsWith("\n")) return;
      finished = true;
      void (async () => {
        try {
          const request = JSON.parse(text); closed(request, ["capability", "method", "args"]);
          const supplied = Buffer.from(typeof request.capability === "string" ? request.capability : "");
          if (supplied.length !== capability.length || !timingSafeEqual(supplied, Buffer.from(capability))) reject("OWNER_MISMATCH", 4);
          await bridge.authorize(owner);
          let result;
          if (request.method === "submit") {
            closed(request.args, ["batch_id", "items"]);
            const { batch_id, items } = request.args;
            if (!Array.isArray(items)) reject();
            result = await bridge.submit_batch(owner, batch_id, items.map((backend_request, index) => ({ request_id: digest([batch_id, index]),
              idempotency_key: "batch-" + digest([batch_id, index]), instance_id: owner.instance_id, policy_digest: digest(runtime.manifest.permission_policy),
              request_digest: digest(backend_request), backend_request })));
          } else if (["status", "cancel"].includes(request.method)) {
            closed(request.args, ["batch_id"]);
            result = request.method === "status" ? await bridge.get_batch(owner, request.args.batch_id) : await bridge.cancel_batch(owner, request.args.batch_id);
          } else reject();
          const { parent_owner, ...summary } = result;
          connection.end(JSON.stringify({ ok: true, result: summary }) + "\n");
        } catch (error) {
          connection.end(JSON.stringify({ ok: false, error: isProtocolError(error) ? error.code : "DELEGATE_BATCH_FAILED", exit_code: isProtocolError(error) ? error.exitCode : 6 }) + "\n");
        }
      })();
    });
  });
  try {
    await new Promise((resolve, fail) => { server.once("error", fail); server.listen(socket, () => { server.off("error", fail); resolve(); }); });
    chmodSync(socket, 0o600);
  } catch (error) {
    server.close();
    try { unlinkSync(socket); } catch { /* 本次未完成绑定。 */ }
    try { rmdirSync(directory); } catch { /* 保留未知内容。 */ }
    throw error;
  }
  server.on("error", () => {});
  const identity = lstatSync(socket, { bigint: true }), path = join(root, "control.json");
  const record = { schema_version: 2, instance_id: owner.instance_id, manager_activation_id: owner.manager_activation_id,
    socket, socket_identity: { device: String(identity.dev), inode: String(identity.ino) }, capability };
  try { writePrivate(path, canonical(record) + "\n"); }
  catch (error) { server.close(); try { unlinkSync(socket); rmdirSync(directory); } catch {} throw error; }
  return async () => {
    for (const connection of connections) connection.destroy();
    await new Promise(resolve => server.close(() => resolve()));
    try { if (canonical(JSON.parse(readFileSync(path, "utf8"))) === canonical(record)) unlinkSync(path); } catch { /* 新端点不属于本次关闭。 */ }
    try { const current = lstatSync(socket, { bigint: true }); if (current.dev === identity.dev && current.ino === identity.ino) unlinkSync(socket); } catch { /* 已关闭。 */ }
    try { rmdirSync(directory); } catch { /* 不删除未知内容。 */ }
  };
}
