// 只核对 SSE 完整性和服务返回的模型身份；不把响应正文写入进度。
import { reject } from "./managed-types.ts";

export function observeDelegateResponse(response, selected, api = "openai-completions") {
  if (!["openai-completions", "openai-responses", "openai-codex-responses"].includes(api)) reject("DELEGATE_MODEL_UNSUPPORTED", 5);
  const observation = { done: false, model: null, failed: false };
  if (!response.ok) { observation.done = true; observation.failed = true; return { response, observation }; }
  if (!response.body) return { response, observation };
  const reader = response.body.getReader(), decoder = new TextDecoder("utf8", { fatal: true });
  let pending = "", data = [], eventBytes = 0;
  const event = () => {
    if (!data.length) return;
    const text = data.join("\n"); data = []; eventBytes = 0;
    if (text === "[DONE]") {
      if (api !== "openai-completions" && !observation.done) reject("DELEGATE_STREAM_INVALID", 5);
      observation.done = true; return;
    }
    if (observation.done) reject("DELEGATE_STREAM_INVALID", 5);
    let value;
    try { value = JSON.parse(text); } catch { reject("DELEGATE_STREAM_INVALID", 5); }
    if (!value || typeof value !== "object") reject("DELEGATE_STREAM_INVALID", 5);
    const observed = api !== "openai-completions" ? value.response?.model : value.model;
    if (observed !== undefined) {
      if (observed !== selected.model_id) reject("DELEGATE_MODEL_MISMATCH", 5);
      observation.model = { ...selected };
    }
    if (api !== "openai-completions") {
      if (["response.failed", "response.incomplete", "error"].includes(value.type)) reject("DELEGATE_STREAM_INCOMPLETE", 5);
      if (value.type === "response.completed" || api === "openai-codex-responses" && value.type === "response.done") {
        if (!value.response || value.response.status !== "completed" && !(api === "openai-codex-responses" && value.response.status === undefined)) reject("DELEGATE_STREAM_INVALID", 5);
        observation.done = true;
      }
    }
  };
  const scan = text => {
    pending += text;
    if (pending.length > 1024 * 1024) reject("DELEGATE_STREAM_OVERSIZE", 5);
    let at;
    while ((at = pending.indexOf("\n")) >= 0) {
      const line = pending.slice(0, at).replace(/\r$/, ""); pending = pending.slice(at + 1);
      if (!line) event();
      else if (line.startsWith("data:")) {
        eventBytes += line.length;
        if (eventBytes > 1024 * 1024) reject("DELEGATE_STREAM_OVERSIZE", 5);
        data.push(line.slice(5).replace(/^ /, ""));
      }
    }
  };
  const stream = new ReadableStream({
    async pull(controller) {
      try {
        const chunk = await reader.read();
        if (chunk.done) {
          scan(decoder.decode()); event();
          if (!observation.done) reject("DELEGATE_STREAM_INCOMPLETE", 5);
          controller.close(); return;
        }
        scan(decoder.decode(chunk.value, { stream: true })); controller.enqueue(chunk.value);
      } catch (error) { await reader.cancel().catch(() => {}); controller.error(error); }
    },
    async cancel(reason) { await reader.cancel(reason); },
  });
  return { response: new Response(stream, { status: response.status, headers: response.headers }), observation };
}
