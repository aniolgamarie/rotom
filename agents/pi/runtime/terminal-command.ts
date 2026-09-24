// 只转发已批准 PTY 的输入／屏幕／尺寸；不在父进程启动编辑器。
import { reject } from "./managed-types.ts";

export async function runTerminalCommand(runtime, ticket, { input = process.stdin, output = process.stdout,
    pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)) } = {}) {
  if (!ticket.terminal_size || !input.isTTY || !output.isTTY) {
    await runtime.ordinaryOperations.abort(ticket);
    reject("EDITOR_TERMINAL_REQUIRED", 5);
  }
  const oldRaw = input.isRaw === true, oldFlowing = input.readableFlowing;
  const decoder = new TextDecoder("utf8", { fatal: true });
  let cursor = 0, stopped = false, attached = false, failed = false, serial = Promise.resolve(), pump;
  const fail = () => {
    if (stopped || failed) return;
    failed = true;
    void runtime.ordinaryOperations.abort(ticket).catch(() => {});
  };
  const send = async text => {
    let data = "", bytes = 0;
    const flush = async () => {
      for (let attempt = 0; ; attempt++) {
        if (stopped || failed) return;
        try {
          const result = await runtime.supervisor.call("ordinary_command_stdin", { operation_id: ticket.operation_id, data, end: false });
          if (result.accepted_bytes !== bytes || result.stdin_closed) reject("EDITOR_INPUT_UNCONFIRMED", 5);
          break;
        } catch (error) {
          if (error.message !== "ORDINARY_STDIN_BACKPRESSURE" || attempt >= 99) throw error;
          await pause(50);
        }
      }
      data = ""; bytes = 0;
    };
    for (const character of text) {
      const length = Buffer.byteLength(character);
      if (bytes + length > 512) await flush();
      data += character; bytes += length;
    }
    if (data) await flush();
  };
  const onData = chunk => {
    if (stopped || failed) return;
    try {
      const text = decoder.decode(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk), { stream: true });
      serial = serial.then(() => send(text)).catch(fail);
    } catch { fail(); }
  };
  const onResize = () => {
    if (stopped || failed) return;
    serial = serial.then(() => runtime.supervisor.call("ordinary_command_resize", { operation_id: ticket.operation_id,
      rows: output.rows ?? 24, columns: output.columns ?? 80 })).catch(fail);
  };
  const drain = async () => {
    while (!stopped && !failed) {
      const value = await runtime.supervisor.call("ordinary_command_output", { operation_id: ticket.operation_id, cursor });
      if (value.dropped || !Number.isSafeInteger(value.next_cursor) || value.next_cursor < cursor) reject("EDITOR_OUTPUT_LOST", 5);
      for (const event of value.events) {
        if (!["stdout", "stderr"].includes(event.stream)) reject("EDITOR_OUTPUT_INVALID", 5);
        const bytes = Buffer.from(event.data_b64, "base64");
        if (bytes.toString("base64") !== event.data_b64) reject("EDITOR_OUTPUT_INVALID", 5);
        if (!stopped) output.write(bytes);
      }
      cursor = value.next_cursor;
      if (value.complete && !value.has_more) return;
      if (!value.has_more) await pause(25);
    }
  };
  try {
    const result = await runtime.ordinaryOperations.write(ticket, null, null, undefined, { onStarted: proof => {
      if (proof.lease_id !== ticket.lease_id || !Number.isSafeInteger(proof.process_identity?.pid) || proof.process_identity.pid <= 0) reject("EDITOR_PROCESS_UNVERIFIED", 4);
      input.setRawMode(true); attached = true;
      input.on("data", onData); output.on("resize", onResize);
      input.resume();
      pump = drain().catch(fail);
    } });
    await pump;
    if (failed || result.terminationConfirmed !== true) reject("EDITOR_EXECUTION_UNVERIFIED", 5);
    // 私人存档允许截断；终端显示已逐块传递，物理终止另由 supervisor 证明。
    return result.exitCode;
  } finally {
    stopped = true;
    if (attached) {
      input.off("data", onData); output.off("resize", onResize);
      input.setRawMode(oldRaw);
      if (oldFlowing === false) input.pause();
    }
    await serial;
    await pump;
  }
}
