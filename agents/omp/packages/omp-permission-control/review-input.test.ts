import { expect, test } from "bun:test";
import { prepareReviewPacket, redactReviewText, isSanitizedReviewPacket, type RawReviewInput } from "./review-input";
import { reviewCommand, type ReviewRuntime } from "./standalone-reviewer";
const base = { command: "echo fixture", cwd: "/fixture", userMessages: ["run fixture"] };

// 固定 golden，不调用生产脱敏器构造期望。
const golden: Array<[string, string]> = [
  ["echo Be'ar'er CanaryToken", "echo Be'ar'er [REDACTED]"],
  ["echo Be'ar'er\" CanaryToken\"", "echo Be'ar'er\" [REDACTED]\""],
  ["echo Ba's'ic CanaryBasic", "echo Ba's'ic [REDACTED]"],
  ["curl --to'ken' CanarySplit https://fixture.invalid", "curl --to'ken' [REDACTED] https://fixture.invalid"],
  ["curl --to'ken'= CanaryEquals https://fixture.invalid", "curl --to'ken'= [REDACTED] https://fixture.invalid"],
  ["API'_'KEY= CanaryEnv curl https://fixture.invalid", "API'_'KEY= [REDACTED] curl https://fixture.invalid"],
  ["curl -'u' CanaryUser https://fixture.invalid", "curl -'u' [REDACTED] https://fixture.invalid"],
  ["curl --api-key=CANARY_FLAG https://fixture.invalid/items", "curl --api-key=[REDACTED] https://fixture.invalid/items"],
  ["curl --token 'CANARY_SPLIT' https://fixture.invalid", "curl --token '[REDACTED]' https://fixture.invalid"],
  ["API_KEY=CANARY_ENV curl https://fixture.invalid", "API_KEY=[REDACTED] curl https://fixture.invalid"],
  ["curl -u alice:CANARY_AUTH -H 'Authorization: Bearer CANARY_HEADER' https://fixture.invalid", "curl -u [REDACTED] -H 'Authorization: Bearer [REDACTED]' https://fixture.invalid"],
  ["curl -H 'Accept: application/json' https://fixture.invalid", "curl -H 'Accept: application/json' https://fixture.invalid"],
  ["obclient -pCANARY_DB -e 'select 1'", "obclient -p[REDACTED] -e 'select 1'"],
  ["echo 'obclient -pCANARY_NEST -e select'", "echo 'obclient -p[REDACTED] -e select'"],
  ["mysql -p'CANARY_QUOTED' -e 'select 1'", "mysql -p'[REDACTED]' -e 'select 1'"],
  ["mysql -pCANARY\\\n_CONTINUED -e 'select 1'", "mysql -p[REDACTED] -e 'select 1'"],
  ["curl --api'-key' CANARY_CONCAT https://fixture.invalid", "curl --api'-key' [REDACTED] https://fixture.invalid"],
  ["curl --to\\ken=CANARY_ESCAPE https://fixture.invalid", "curl --to\\ken=[REDACTED] https://fixture.invalid"],
  ["curl https://alice:CANARY_URL@fixture.invalid/items", "curl https://[REDACTED]@fixture.invalid/items"],
  ["curl -H 'Authorization: CANARY_BARE_HEADER' https://fixture.invalid", "curl -H 'Authorization: [REDACTED]' https://fixture.invalid"],
  ["Authorization: inspect the repository and report findings", "Authorization: inspect the repository and report findings"],
  ["Authorization: read-only query of fixture", "Authorization: read-only query of fixture"],
  ["for x in a b; do echo $x; done", "for x in a b; do echo $x; done"],
  ["curl --token '[REDACTED]' https://fixture.invalid", "curl --token '[REDACTED]' https://fixture.invalid"],
  ["echo sk-abcdefghijklmnop0123456789", "echo [REDACTED]"],
  ["-----BEGIN PRIVATE KEY-----\nCANARY_PEM\n-----END PRIVATE KEY-----", "[REDACTED]"],
  ["echo 'password=CANARY_ONE harmless token=CANARY_TWO tail'", "echo 'password=[REDACTED] harmless token=[REDACTED] tail'"],
];
for (const [raw, expected] of golden) test(`golden ${raw.slice(0, 55)}`, () => {
  expect(redactReviewText(raw, "command")).toBe(expected);
  expect(redactReviewText(expected, "command")).toBe(expected);
});

test("nested packet secrets removed, independent full golden and source unchanged", () => {
  const input: RawReviewInput = { command: "curl --token CANARY_COMMAND https://fixture.invalid", cwd: "/fixture",
    parameters: { cwd: "/fixture", timeout: 12 }, userMessages: ["Authorization: read-only query; token=CANARY_USER"],
    executionContext: { shellFamily: "fish", plan: [{ password: "CANARY_NESTED", label: "token=CANARY_LABEL", target: "https://fixture.invalid" }] } };
  const snapshot = JSON.stringify(input);
  const result = prepareReviewPacket(input);
  expect(result.status).toBe("ready");
  if (result.status !== "ready") throw 0;
  expect(result.packet).toEqual({ command: "curl --token [REDACTED] https://fixture.invalid", cwd: "/fixture",
    parameters: { cwd: "/fixture", timeout: 12 }, genuineUserMessages: ["Authorization: read-only query; token=[REDACTED]"],
    executionContext: { shellFamily: "fish", plan: [{ password: "[REDACTED]", label: "token=[REDACTED]", target: "https://fixture.invalid" }] },
    privacy: { redacted: true, detection: "credential-slots-and-known-formats" },
    contextSelection: { omittedMessages: 0, authorizationHistoryComplete: true } });
  expect(JSON.stringify(input)).toBe(snapshot);
  expect(JSON.stringify(result.packet)).not.toContain("CANARY_");
  expect(isSanitizedReviewPacket(result.packet)).toBe(true);
  expect(isSanitizedReviewPacket({ ...result.packet })).toBe(false);
  expect(Object.isFrozen(result.packet.executionContext?.plan)).toBe(true);
  expect(Object.isFrozen(result.packet.genuineUserMessages)).toBe(true);
});

test("long unrelated history retains first/latest/restrictions and marks omissions", () => {
  const messages = ["first task", "Never publish files", ...Array.from({ length: 40 }, (_, i) => `old ${i}: ${"x".repeat(1000)}`), "latest task"];
  const result = prepareReviewPacket({ ...base, userMessages: messages });
  expect(result.status).toBe("ready");
  if (result.status !== "ready") throw 0;
  expect(result.packet.genuineUserMessages).toEqual(["first task", "Never publish files", ...messages.slice(34)]);
  expect(result.packet.contextSelection).toEqual({ omittedMessages: 32, authorizationHistoryComplete: false });
  expect(result.packet.command).toBe(base.command);
});

test("complete current operation and required restriction cannot be truncated", () => {
  expect(prepareReviewPacket({ ...base, command: "x".repeat(25 * 1024) })).toEqual({ status: "input-too-large", reasonCode: "INPUT_TOO_LARGE" });
  expect(prepareReviewPacket({ ...base, userMessages: ["Never " + "x".repeat(25 * 1024)] })).toEqual({ status: "input-too-large", reasonCode: "INPUT_TOO_LARGE" });
});

test("unknown fields, getters, cycles and invalid shapes fail without leaked exceptions", () => {
  const cycle: any = {}; cycle.self = cycle;
  let accessed = 0;
  for (const value of [{ ...base, extra: "CANARY_UNKNOWN" }, { ...base, parameters: { surprise: "CANARY" } },
    { ...base, executionContext: cycle }, { ...base, get command() { accessed++; throw new Error("CANARY_GETTER"); } },
    { ...base, executionContext: { get token() { accessed++; throw new Error("CANARY_NESTED_GETTER"); } } },
    { ...base, userMessages: [3] }, { ...base, parameters: { timeout: NaN } }]) {
    expect(prepareReviewPacket(value as RawReviewInput)).toEqual({ status: "invalid", reasonCode: "INPUT_INVALID" });
  }
  expect(accessed).toBe(0);
});

test("optional history gives remaining total budget to complete current command", () => {
  const command = "echo " + "x".repeat(19 * 1024);
  const result = prepareReviewPacket({ ...base, command,
    userMessages: ["first task", ...Array.from({ length: 30 }, (_, i) => `old ${i} ${"z".repeat(1000)}`), "latest task"] });
  expect(result.status).toBe("ready");
  if (result.status !== "ready") throw 0;
  expect(result.packet.command).toBe(command);
  expect(result.packet.genuineUserMessages).toEqual(["first task", "old 26 " + "z".repeat(1000), "old 27 " + "z".repeat(1000),
    "old 28 " + "z".repeat(1000), "old 29 " + "z".repeat(1000), "latest task"]);
  expect(result.packet.contextSelection).toEqual({ omittedMessages: 26, authorizationHistoryComplete: false });
});

for (const api of ["openai-completions", "anthropic-messages"]) test(`normalized credential tokens never enter ${api} primary or remote bodies`, async () => {
  const command = `echo Be'ar'er CanaryToken; echo Be'ar'er" CanaryJoined"; echo Ba's'ic CanaryBasic; curl --to'ken'= CanaryFlag https://fixture.invalid`;
  const expected = `echo Be'ar'er [REDACTED]; echo Be'ar'er" [REDACTED]"; echo Ba's'ic [REDACTED]; curl --to'ken'= [REDACTED] https://fixture.invalid`;
  const prepared = prepareReviewPacket({ ...base, command });
  expect(prepared.status).toBe("ready");
  if (prepared.status !== "ready") throw 0;
  expect(prepared.packet.command).toBe(expected);
  const bodies: string[] = [];
  const model = { provider: "fictional", id: "primary", api, baseUrl: "https://unused.invalid/v1" };
  const runtime: ReviewRuntime = { current: () => model, resolve: () => ({ ...model, id: "remote" }),
    getApiKey: async () => "fictional-key", fetch: async (_url, init) => {
      bodies.push(init.body as string);
      if (bodies.length === 1) return new Response("opaque failure", { status: 500 });
      const review = JSON.stringify({ decision: "ask", risk: "unknown", authorization: "unknown", reasonCode: "UNKNOWN_RISK" });
      return new Response(JSON.stringify(api === "anthropic-messages" ? { content: [{ type: "text", text: review }] } :
        { choices: [{ message: { content: review } }] }));
    } };
  const result = await reviewCommand(prepared.packet, { reviewer: "session", remoteFallback: { provider: "fictional", model: "remote" } }, runtime);
  expect(result.source).toBe("remote"); expect(bodies.length).toBe(2);
  for (const body of bodies) {
    for (const canary of ["CanaryToken", "CanaryJoined", "CanaryBasic", "CanaryFlag"]) expect(body).not.toContain(canary);
    expect(JSON.parse(JSON.parse(body).messages.at(-1).content).command).toBe(expected);
  }
});

test("empty genuine user history remains model-ready without claiming complete authorization history", () => {
  const result = prepareReviewPacket({ command: "pwd", cwd: "/fixture", userMessages: [] });
  expect(result.status).toBe("ready");
  if (result.status !== "ready") throw 0;
  expect(result.packet).toEqual({ command: "pwd", cwd: "/fixture", genuineUserMessages: [],
    privacy: { redacted: false, detection: "credential-slots-and-known-formats" },
    contextSelection: { omittedMessages: 0, authorizationHistoryComplete: false } });
  expect(isSanitizedReviewPacket(result.packet)).toBe(true);
  expect(Object.isFrozen(result.packet.genuineUserMessages)).toBe(true);
});

const multilineGolden: Array<[string, string]> = [
  ["curl -u CanaryFirst$(touch /fixture/side-effect)CanarySecond https://fixture.invalid", "curl -u [REDACTED]$(touch /fixture/side-effect)[REDACTED] https://fixture.invalid"],
  ["mysql -pCanaryFirst$(touch /fixture/side-effect)CanarySecond -e 'select 1'", "mysql -p[REDACTED]$(touch /fixture/side-effect)[REDACTED] -e 'select 1'"],
  ["curl -uCanaryFirst$(touch /fixture/side-effect)CanarySecond https://fixture.invalid", "curl -u[REDACTED]$(touch /fixture/side-effect)[REDACTED] https://fixture.invalid"],
  ["TOKEN='CanaryFirst\nCanarySecond' curl https://fixture.invalid", "TOKEN='[REDACTED]' curl https://fixture.invalid"],
  ['TOKEN="CanaryFirst\nCanarySecond" curl https://fixture.invalid', 'TOKEN="[REDACTED]" curl https://fixture.invalid'],
  ['curl --token "CanaryFirst \\"CanaryQuoted\\"\nCanarySecond" https://fixture.invalid', 'curl --token "[REDACTED]" https://fixture.invalid'],
  ["TOKEN='CanaryFirst\nCanarySecond'CanaryTail curl https://fixture.invalid", "TOKEN=[REDACTED] curl https://fixture.invalid"],
  ['TOKEN="CanaryFirst\\\nCanarySecond" curl https://fixture.invalid', 'TOKEN="[REDACTED]" curl https://fixture.invalid'],
  ["curl -u 'CanaryUser:CanaryFirst\nCanarySecond' -H 'Authorization: Bearer CanaryFirst\nCanarySecond' https://fixture.invalid", "curl -u '[REDACTED]' -H 'Authorization: Bearer [REDACTED]' https://fixture.invalid"],
  ["curl -H 'Authorization: CanaryFirst\nCanarySecond' https://fixture.invalid", "curl -H 'Authorization: [REDACTED]' https://fixture.invalid"],
  ["mysql -p'CanaryFirst\nCanarySecond' -e 'select 1'", "mysql -p'[REDACTED]' -e 'select 1'"],
  ['TOKEN="CanaryFirst$(touch /fixture/side-effect)CanarySecond" curl https://fixture.invalid', 'TOKEN="[REDACTED]$(touch /fixture/side-effect)[REDACTED]" curl https://fixture.invalid'],
  ['TOKEN=CanaryFirst$(touch /fixture/side-effect)CanarySecond curl https://fixture.invalid', 'TOKEN=[REDACTED]$(touch /fixture/side-effect)[REDACTED] curl https://fixture.invalid'],
  ['TOKEN="CanaryFirst`touch /fixture/side-effect`CanarySecond" curl https://fixture.invalid', 'TOKEN="[REDACTED]`touch /fixture/side-effect`[REDACTED]" curl https://fixture.invalid'],
  ['TOKEN="$(echo token=CanaryInner; touch /fixture/side-effect)" curl https://fixture.invalid', 'TOKEN="$(echo token=[REDACTED]; touch /fixture/side-effect)" curl https://fixture.invalid'],
];
for (const [index, [raw, expected]] of multilineGolden.entries()) test(`complete literal and dynamic credential span ${index}`, () => {
  for (const kind of ["command", "user", "context", "display"] as const) {
    expect(redactReviewText(raw, kind)).toBe(expected);
    expect(redactReviewText(expected, kind)).toBe(expected);
  }
  const prepared = prepareReviewPacket({ command: raw, cwd: "/fixture", userMessages: [raw], executionContext: { label: raw } });
  expect(prepared.status).toBe("ready");
  if (prepared.status !== "ready") throw 0;
  expect(prepared.packet.command).toBe(expected);
  expect(prepared.packet.genuineUserMessages).toEqual([expected]);
  expect(prepared.packet.executionContext).toEqual({ label: expected });
  expect(JSON.stringify(prepared.packet)).not.toContain("Canary");
});

for (const api of ["openai-completions", "anthropic-messages"]) test(`complete multiline credentials sanitized at both ${api} reviewer exits`, async () => {
  for (const [raw, expected] of multilineGolden) {
    const prepared = prepareReviewPacket({ command: raw, cwd: "/fixture", userMessages: [raw], executionContext: { label: raw } });
    if (prepared.status !== "ready") throw 0;
    const bodies: string[] = [];
    const model = { provider: "fictional", id: "primary", api, baseUrl: "https://unused.invalid/v1" };
    const runtime: ReviewRuntime = { current: () => model, resolve: () => ({ ...model, id: "remote" }),
      getApiKey: async () => "fictional-key", fetch: async (_url, init) => {
        bodies.push(init.body as string);
        if (bodies.length === 1) return new Response(null, { status: 500 });
        const decision = JSON.stringify({ decision: "ask", risk: "unknown", authorization: "unknown", reasonCode: "UNKNOWN_RISK" });
        return new Response(JSON.stringify(api === "anthropic-messages" ? { content: [{ type: "text", text: decision }] } :
          { choices: [{ message: { content: decision } }] }));
      } };
    const result = await reviewCommand(prepared.packet, { reviewer: "session", remoteFallback: { provider: "fictional", model: "remote" } }, runtime);
    expect(result.source).toBe("remote"); expect(bodies.length).toBe(2);
    for (const body of bodies) {
      expect(body).not.toContain("Canary");
      const packet = JSON.parse(JSON.parse(body).messages.at(-1).content);
      expect(packet.command).toBe(expected);
      expect(packet.genuineUserMessages).toEqual([expected]);
      expect(packet.executionContext).toEqual({ label: expected });
    }
  }
});

// 独立canary：允许拒绝复杂动态凭据，绝不能生成删去真实副作用的ready包。
const unsafePrivacyCases = [
  "# TOKEN='\ntouch /fixture/comment-effect\n# '\necho safe",
  "# TOKEN=\ntouch /fixture/comment-prefix-effect",
  "# Bearer\ntouch /fixture/comment-auth-prefix-effect",
  "echo safe; # password=\"\ntouch /fixture/comment-double-effect\n# \"\necho after",
  "# token='fixture\nsecond'\ntouch /fixture/comment-adjacent-effect",
  'TOKEN="$(case x in x) touch /fixture/case-effect ;; esac)" echo safe',
  'TOKEN="$(case x in (x) touch /fixture/case-pattern-effect ;; esac)" echo safe',
  'TOKEN="$(echo safe # )\ntouch /fixture/substitution-comment-effect)" echo safe',
  'TOKEN="$(cat <<EOF\nfixture)\nEOF\ntouch /fixture/heredoc-effect)" echo safe',
  'TOKEN="CanaryLiteral$(case x in x) touch /fixture/concat-case-effect ;; esac)CanaryTail" echo safe',
];
for (const [index, command] of unsafePrivacyCases.entries()) test(`privacy boundary rejects unsafe secret structure ${index}`, () => {
  expect(prepareReviewPacket({ ...base, command })).toEqual({ status: "invalid", reasonCode: "INPUT_INVALID" });
  expect(() => redactReviewText(command, "display")).toThrow("INPUT_INVALID");
  expect(prepareReviewPacket({ ...base, userMessages: [command] })).toEqual({ status: "invalid", reasonCode: "INPUT_INVALID" });
  expect(prepareReviewPacket({ ...base, executionContext: { label: command } })).toEqual({ status: "invalid", reasonCode: "INPUT_INVALID" });
});

const safePrivacyCases: Array<[string, string]> = [
  ["echo fixture # unrelated ' quote\ntouch /fixture/visible-effect", "echo fixture # unrelated ' quote\ntouch /fixture/visible-effect"],
  ["echo $(printf '#'); touch /fixture/visible-effect", "echo $(printf '#'); touch /fixture/visible-effect"],
  ["case x in x) touch /fixture/visible-effect ;; esac", "case x in x) touch /fixture/visible-effect ;; esac"],
  ["# token=CanaryComment\ntouch /fixture/visible-effect", "# token=[REDACTED]\ntouch /fixture/visible-effect"],
  ["# TOKEN='CanaryComment'\ntouch /fixture/visible-effect", "# TOKEN='[REDACTED]'\ntouch /fixture/visible-effect"],
  ["# unrelated ' quote\nTOKEN='CanaryFirst\nCanarySecond' touch /fixture/visible-effect", "# unrelated ' quote\nTOKEN='[REDACTED]' touch /fixture/visible-effect"],
  ["TOKEN='CanaryFirst\n# CanarySecond' touch /fixture/visible-effect", "TOKEN='[REDACTED]' touch /fixture/visible-effect"],
  ["TOKEN=\"CanaryFirst # CanarySecond\nCanaryThird\" touch /fixture/visible-effect", "TOKEN=\"[REDACTED]\" touch /fixture/visible-effect"],
  ["echo '# literal'; TOKEN='CanaryFirst\nCanarySecond' touch /fixture/visible-effect", "echo '# literal'; TOKEN='[REDACTED]' touch /fixture/visible-effect"],
  ['echo "$(case x in x) touch /fixture/visible-effect ;; esac)"', 'echo "$(case x in x) touch /fixture/visible-effect ;; esac)"'],
  ['echo "$(echo safe # )\ntouch /fixture/visible-effect)"', 'echo "$(echo safe # )\ntouch /fixture/visible-effect)"'],
];
for (const [index, [command, expected]] of safePrivacyCases.entries()) test(`privacy boundary preserves safe nearby commands ${index}`, () => {
  const prepared = prepareReviewPacket({ ...base, command });
  expect(prepared.status).toBe("ready");
  if (prepared.status !== "ready") throw 0;
  expect(prepared.packet.command).toBe(expected);
  expect(redactReviewText(command, "display")).toBe(expected);
  expect(expected).toContain("touch /fixture/visible-effect");
});

for (const api of ["openai-completions", "anthropic-messages"]) test(`privacy boundary never sends unsafe packet to ${api}`, async () => {
  let fetches = 0;
  const model = { provider: "fictional", id: "reviewer", api, baseUrl: "https://unused.invalid/v1" };
  const runtime: ReviewRuntime = { current: () => model, resolve: () => model, getApiKey: async () => "fictional-key",
    fetch: async () => { fetches++; throw new Error("UNEXPECTED_FIXTURE_FETCH"); } };
  for (const command of unsafePrivacyCases) {
    const prepared = prepareReviewPacket({ ...base, command });
    expect(prepared.status).toBe("invalid");
    if (prepared.status === "ready") await reviewCommand(prepared.packet, { reviewer: "session" }, runtime);
  }
  expect(fetches).toBe(0);
});
