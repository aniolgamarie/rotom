import { privacyWords } from "./standalone-shell-analysis";
import type { ContextValue } from "./worktree-analysis";

const MAX_BYTES = 24 * 1024;
const HISTORY_BYTES = 8 * 1024;
const MASK = "[REDACTED]";
const packets = new WeakSet<object>();
const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
const FIELD = "(?:[A-Za-z0-9_-]*(?:token|password|passwd|secret|api[_-]?key|credential|cookie)[A-Za-z0-9_-]*)";
const VALUE = "(?:'[^'\\n]*'|\"[^\"\\n]*\"|[^\\s;&|<>\"']+)";
const FLAG_FIELD = `(?:${FIELD}|authorization)`;
const secretField = new RegExp(`^${FIELD}$`, "iu");

export interface RawReviewInput {
  command: string;
  cwd: string;
  userMessages: string[];
  parameters?: { cwd?: string; timeout?: number };
  executionContext?: Record<string, ContextValue>;
}
export interface SanitizedReviewPacket {
  readonly command: string;
  readonly cwd: string;
  readonly parameters?: Readonly<{ cwd?: string; timeout?: number }>;
  readonly executionContext?: Readonly<Record<string, ContextValue>>;
  readonly genuineUserMessages: readonly string[];
  readonly privacy: Readonly<{ redacted: boolean; detection: "credential-slots-and-known-formats" }>;
  readonly contextSelection: Readonly<{ omittedMessages: number; authorizationHistoryComplete: boolean }>;
}
export type PreparedReviewPacket = { status: "ready"; packet: SanitizedReviewPacket } |
  { status: "input-too-large" | "invalid"; reasonCode: "INPUT_TOO_LARGE" | "INPUT_INVALID" };

export function isSanitizedReviewPacket(value: unknown): value is SanitizedReviewPacket {
  return !!value && typeof value === "object" && packets.has(value);
}

interface Redaction { start: number; end: number }
const placeholder = (value: string) => /^(?:\[?REDACTED\]?|<SECRET_\d+>)$/u.test(value);

// 检测已知凭据槽位与格式，不读取文件或环境，也不承诺识别未知秘密。
function plainRanges(text: string): Redaction[] {
  const ranges: Redaction[] = [];
  const find = (regex: RegExp, prefixGroup = false) => {
    for (const match of text.matchAll(regex)) {
      let start = match.index! + (prefixGroup ? match[1].length : 0), end = match.index! + match[0].length;
      if ((text[start] === "'" || text[start] === '"') && text[end - 1] === text[start]) { start++; end--; }
      if (!placeholder(text.slice(start, end))) ranges.push({ start, end });
    }
  };
  find(/-----BEGIN ([A-Z ]*PRIVATE KEY)-----[\s\S]*?-----END \1-----/gu);
  find(/\b(?:sk-[A-Za-z0-9_-]{16,}|gh[opusr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b/gu);
  // 用户信息只遮蔽 authority 内的值，保留协议和目标主机。
  for (const match of text.matchAll(/(\b[A-Za-z][A-Za-z0-9+.-]*:\/\/)([^\s/"'<>]+)@/gu)) {
    if (!placeholder(match[2])) ranges.push({ start: match.index! + match[1].length, end: match.index! + match[0].length - 1 });
  }
  find(new RegExp(`((?<![A-Za-z0-9_-])${FIELD}["']?\\s*[:=]\\s*)${VALUE}`, "giu"), true);
  find(new RegExp(`(--${FLAG_FIELD}(?:=|\\s+))${VALUE}`, "giu"), true);
  find(new RegExp(`(\\bAUTHORIZATION\\s*=\\s*)${VALUE}`, "giu"), true);
  find(new RegExp(`(\\b(?:Bearer|Basic)\\s+)${VALUE}`, "giu"), true);
  return ranges;
}

// 原始跨度映射只在栈内使用；拼接引号和转义仍保留选项/用途。
function foldedSpans(raw: string): { text: string; starts: number[]; ends: number[] } {
  let text = "", quote = "";
  const starts: number[] = [], ends: number[] = [];
  for (let i = 0; i < raw.length; i++) {
    const char = raw[i];
    if ((char === "'" || char === '"') && (!quote || quote === char)) { quote = quote ? "" : char; continue; }
    if (char === "\\" && quote !== "'" && i + 1 < raw.length) {
      if (raw[i + 1] === "\n") { i++; continue; }
      if (raw[i + 1] === "\r" && raw[i + 2] === "\n") { i += 2; continue; }
      starts.push(i); text += raw[++i]; ends.push(i + 1); continue;
    }
    starts.push(i); text += char; ends.push(i + 1);
  }
  return { text, starts, ends };
}

function credentialRanges(text: string, depth = 0): Redaction[] {
  const ranges = plainRanges(text);
  const words = privacyWords(text);
  let database = false, curl = false;
  const addValue = (start: number, end: number) => {
    if ((text[start] === "'" || text[start] === '"') && text[end - 1] === text[start]) { start++; end--; }
    if (!placeholder(text.slice(start, end))) ranges.push({ start, end });
  };
  for (let i = 0; i < words.length; i++) {
    const word = words[i];
    if (i && /[;&|\n\r]/u.test(text.slice(words[i - 1].end, word.start).replace(/\\\r?\n/gu, ""))) {
      database = false; curl = false;
    }
    if (/(?:^|[/\\])(?:mysql|mariadb|obclient)(?:\.exe)?$/u.test(word.value)) database = true;
    if (/(?:^|[/\\])curl(?:\.exe)?$/u.test(word.value)) curl = true;
    const previous = words[i - 1]?.value ?? "";
    const splitFlag = new RegExp(`^--${FLAG_FIELD}=?$`, "iu").test(previous) ||
      new RegExp(`^${FLAG_FIELD}=$`, "iu").test(previous) || /^(?:Bearer|Basic)$/iu.test(previous) ||
      (curl && /^(?:--user=?|--proxy-user=?|--oauth2-bearer=?|-[uU])$/u.test(previous));
    if (splitFlag) { addValue(word.start, word.end); continue; }
    const folded = foldedSpans(word.raw);
    const local = plainRanges(folded.text);
    // 只有真实 curl header 槽位把裸 Authorization 正文视为凭据；许可说明不属于该槽位。
    if (curl) {
      const header = /^(?:-H|--header)$/u.test(previous) ? /^(Authorization\s*:\s*)(.+)$/iu.exec(folded.text) :
        /^((?:-H|--header=)Authorization\s*:\s*)(.+)$/iu.exec(folded.text);
      if (header && !/^(?:Bearer|Basic)\s/iu.test(header[2]) && !placeholder(header[2]))
        local.push({ start: header[1].length, end: folded.text.length });
    }
    let prefix: string | undefined;
    if (database && /^-p.+/u.test(folded.text)) prefix = "-p";
    else if (curl) prefix = /^(?:-[uU]|--(?:user|proxy-user|oauth2-bearer)=)(?=.)/u.exec(folded.text)?.[0];
    if (prefix && !placeholder(folded.text.slice(prefix.length))) local.push({ start: prefix.length, end: folded.text.length });
    // 例如 echo 'obclient -pVALUE'：保留内嵌程序，仅处理凭据跨度。
    if (depth < 8 && folded.text !== word.raw && /\s/u.test(folded.text)) local.push(...credentialRanges(folded.text, depth + 1));
    for (const range of local) {
      if (range.end <= range.start) continue;
      ranges.push({ start: word.start + folded.starts[range.start], end: word.start + folded.ends[range.end - 1] });
    }
  }
  return ranges;
}

export function redactReviewText(text: string, kind: "command" | "user" | "context" | "display"): string {
  const ranges = credentialRanges(text).sort((a, b) => a.start - b.start || a.end - b.end);
  const merged: Redaction[] = [];
  for (const range of ranges) {
    const previous = merged.at(-1);
    if (previous && range.start < previous.end) previous.end = Math.max(previous.end, range.end);
    else merged.push({ ...range });
  }
  for (const range of merged.reverse()) text = text.slice(0, range.start) + MASK + text.slice(range.end);
  return text;
}

function plainObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      ![Object.prototype, null].includes(Object.getPrototypeOf(value))) throw 0;
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (Reflect.ownKeys(value).some(key => typeof key !== "string") ||
      Object.values(descriptors).some(d => !("value" in d) || !d.enumerable)) throw 0;
  return Object.fromEntries(Object.entries(descriptors).map(([key, d]) => [key, d.value]));
}
function shape(value: unknown, allowed: string[]): Record<string, unknown> {
  const object = plainObject(value);
  if (Object.keys(object).some(key => !allowed.includes(key))) throw 0;
  return object;
}
function freeze<T>(value: T): T {
  if (value && typeof value === "object") { for (const child of Object.values(value)) freeze(child); Object.freeze(value); }
  return value;
}

export function prepareReviewPacket(input: RawReviewInput): PreparedReviewPacket {
  try {
    const raw = shape(input, ["command", "cwd", "userMessages", "parameters", "executionContext"]);
    if (typeof raw.command !== "string" || !raw.command.trim() || typeof raw.cwd !== "string" || !Array.isArray(raw.userMessages)) throw 0;
    let redacted = false, nodes = 0;
    const seen = new Set<object>();
    const text = (value: string, kind: "command" | "user" | "context") => {
      const sanitized = redactReviewText(value, kind); redacted ||= sanitized !== value; return sanitized;
    };
    const context = (value: unknown, depth = 0, key = ""): ContextValue => {
      if (++nodes > 10000 || depth > 32) throw 0;
      if (typeof value === "string") {
        if (secretField.test(key) || /^(?:authorization)$/iu.test(key)) { redacted ||= value !== MASK; return MASK; }
        return text(value, "context");
      }
      if (secretField.test(key) && (typeof value === "number" || typeof value === "boolean")) { redacted = true; return MASK; }
      if (value === null || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value))) return value;
      if (!value || typeof value !== "object" || seen.has(value)) throw 0;
      seen.add(value);
      let result: ContextValue;
      if (Array.isArray(value)) {
        const desc = Object.getOwnPropertyDescriptors(value);
        if (Reflect.ownKeys(value).length !== value.length + 1 || Object.entries(desc).some(([k, d]) => k !== "length" && !("value" in d))) throw 0;
        result = Array.from({ length: value.length }, (_, i) => context(desc[String(i)].value, depth + 1, key));
      } else {
        const entries = Object.entries(plainObject(value)).map(([k, v]) => [text(k, "context"), context(v, depth + 1, k)] as const);
        if (new Set(entries.map(([k]) => k)).size !== entries.length) throw 0;
        result = Object.fromEntries(entries);
      }
      seen.delete(value); return result;
    };
    const messages = context(raw.userMessages) as string[];
    if (messages.some(message => typeof message !== "string")) throw 0;
    // 用户文本使用同一规则，原始对象绝不进入审查包。
    const sanitizedMessages = messages;
    let parameters: { cwd?: string; timeout?: number } | undefined;
    if (raw.parameters !== undefined) {
      const params = shape(raw.parameters, ["cwd", "timeout"]);
      if (params.cwd !== undefined && typeof params.cwd !== "string" || params.timeout !== undefined &&
        (typeof params.timeout !== "number" || !Number.isFinite(params.timeout))) throw 0;
      parameters = { ...(params.cwd !== undefined ? { cwd: text(params.cwd as string, "context") } : {}),
        ...(params.timeout !== undefined ? { timeout: params.timeout as number } : {}) };
    }
    const executionContext = raw.executionContext === undefined ? undefined : context(plainObject(raw.executionContext)) as Record<string, ContextValue>;
    const command = text(raw.command, "command"), cwd = text(raw.cwd, "context");
    const required = new Set<number>();
    if (sanitizedMessages.length) { required.add(0); required.add(sanitizedMessages.length - 1); }
    sanitizedMessages.forEach((message, index) => {
      if (/\b(?:must|never|only|do not|don't|cannot|forbid|restrict|revoke|authorization|permission|allow|deny)\b|禁止|不得|仅限|不要|授权|撤销|限制/iu.test(message)) required.add(index);
    });
    const selected = new Set(required);
    let historySize = bytes([...selected].sort((a, b) => a - b).map(i => sanitizedMessages[i]));
    const requiredPacket = { command, cwd, ...(parameters ? { parameters } : {}), ...(executionContext ? { executionContext } : {}),
      genuineUserMessages: [...required].sort((a, b) => a - b).map(i => sanitizedMessages[i]),
      privacy: { redacted, detection: "credential-slots-and-known-formats" },
      contextSelection: { omittedMessages: sanitizedMessages.length, authorizationHistoryComplete: false } };
    const requiredBytes = bytes(requiredPacket);
    if (requiredBytes > MAX_BYTES) return { status: "input-too-large", reasonCode: "INPUT_TOO_LARGE" };
    let availableBytes = MAX_BYTES - requiredBytes;
    for (let i = sanitizedMessages.length - 1; i >= 0; i--) {
      if (selected.has(i)) continue;
      const size = bytes(sanitizedMessages[i]) + 1;
      if (historySize + size <= HISTORY_BYTES && size <= availableBytes) { selected.add(i); historySize += size; availableBytes -= size; }
    }
    const omittedMessages = sanitizedMessages.length - selected.size;
    const genuineUserMessages = [...selected].sort((a, b) => a - b).map(i => sanitizedMessages[i]);
    const packet: SanitizedReviewPacket = { command, cwd,
      ...(parameters ? { parameters } : {}), ...(executionContext ? { executionContext } : {}), genuineUserMessages,
      privacy: { redacted, detection: "credential-slots-and-known-formats" },
      contextSelection: { omittedMessages, authorizationHistoryComplete: sanitizedMessages.length > 0 && omittedMessages === 0 } };
    if (bytes(packet) > MAX_BYTES) return { status: "input-too-large", reasonCode: "INPUT_TOO_LARGE" };
    freeze(packet); packets.add(packet);
    return { status: "ready", packet };
  } catch { return { status: "invalid", reasonCode: "INPUT_INVALID" }; }
}
