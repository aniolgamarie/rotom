import { spawn } from "node:child_process";
import { readFileSync, readlinkSync, readdirSync, writeSync } from "node:fs";
import { Socket } from "node:net";

// Only the supervisor starts this entry. The trusted command gets no control channel descriptors.
const [nonce, parentNamespace, executable, ...args] = process.argv.slice(2);
const namespace = readlinkSync(`/proc/${process.pid}/ns/pid`);
const report = (value: object) => writeSync(4, JSON.stringify({ nonce, ...value }) + "\n");
if (!nonce || namespace === parentNamespace) { report({ type: "invalid_namespace" }); process.exit(125); }
report({ type: "ready", namespace });
const gate = new Socket({ fd: 5, readable: true, writable: false });
let input = "", started = false;
gate.on("data", data => { input += data.toString(); if (input.length > 200) process.exit(125); });
gate.on("end", () => {
  if (started || input !== nonce) process.exit(125); started = true; gate.destroy();
  const child = spawn(executable, args, { shell: false, stdio: ["ignore", "inherit", "inherit"], env: process.env });
  child.once("error", error => { report({ type: "spawn_error", code: (error as NodeJS.ErrnoException).code ?? "unknown" }); process.exit(126); });
  child.once("exit", (code, signal) => {
    // PID 1 is bubblewrap's reaper. Everything else belongs to this verifier namespace.
    const live = readdirSync("/proc").filter(id => /^\d+$/.test(id) && Number(id) !== 1 && Number(id) !== process.pid).filter(id => {
      try { const text = readFileSync(`/proc/${id}/stat`, "utf8"), state = text.slice(text.lastIndexOf(")") + 2).split(" ")[0]; return !["Z", "X"].includes(state); }
      catch { return false; }
    });
    report({ type: "finished", code, signal, lingering: live.length });
    // Exiting ends PID 1's supervised command; the kernel kills remaining namespace processes.
    process.exit(live.length ? 124 : code ?? 128);
  });
});
gate.on("error", () => process.exit(125));
