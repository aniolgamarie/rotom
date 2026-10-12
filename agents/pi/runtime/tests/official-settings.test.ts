import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, writeFileSync, readFileSync, chmodSync, symlinkSync, linkSync, unlinkSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createOfficialSettings } from "../official-settings.ts";

function fixture(value = {}, { deferredWrites = false } = {}) {
  const root = mkdtempSync(join(tmpdir(), "official-settings-")), path = join(root, "settings.json");
  writeFileSync(path, typeof value === "string" ? value : JSON.stringify(value), { mode: 0o600 });
  const observations = { calls: 0, options: null, storage: null }, states = new WeakMap();
  let writes = Promise.resolve();
  class Manager {
    static fromStorage(storage, options) {
      observations.calls++; observations.options = options; observations.storage = storage;
      let loaded;
      storage.withLock("global", current => { loaded = JSON.parse(current); return undefined; });
      storage.withLock("project", current => { assert.equal(current, undefined); return undefined; });
      const manager = new Manager(); states.set(manager, loaded); return Object.freeze(manager);
    }
    getSettings() { return structuredClone(states.get(this)); }
    setTheme(theme) {
      states.get(this).theme = theme;
      const commit = () => observations.storage.withLock("global", current => JSON.stringify({ ...JSON.parse(current), theme }));
      if (deferredWrites) writes = writes.then(commit).catch(() => {});
      else commit();
    }
    async flush() { await writes; }
  }
  Object.freeze(Manager.prototype); Object.freeze(Manager);
  const sdk = Object.freeze({ SettingsManager: Manager, get ModelRuntime() { throw Error("ModelRuntime touched"); } });
  return { path, root, sdk, observations, mutateManager(manager, fn) { fn(states.get(manager)); } };
}

const enforced = { defaultProjectTrust: "never", enableInstallTelemetry: false, enableAnalytics: false, cacheWarming: "off" };

test("public fromStorage has only global settings and a canonical frozen effective snapshot", () => {
  const f = fixture({ theme: "dark", compaction: { keepRecentTokens: 123, enabled: true } });
  const { settingsManager, snapshot } = createOfficialSettings(f);
  assert.deepEqual(f.observations.options, { projectTrusted: false });
  assert.deepEqual(snapshot(), { cacheWarming: "off", compaction: { enabled: true, keepRecentTokens: 123 }, defaultProjectTrust: "never", enableAnalytics: false, enableInstallTelemetry: false, theme: "dark" });
  assert.equal(Object.isFrozen(snapshot()), true); assert.equal(Object.isFrozen(snapshot().compaction), true);
  assert.throws(() => { snapshot().compaction.enabled = false; }, TypeError);
  assert.equal(settingsManager.getSettings().compaction.enabled, true);
  assert.equal(Object.isFrozen(f.sdk.SettingsManager.prototype), true); assert.equal(Object.isFrozen(settingsManager), true);
});

test("original telemetry and warming flags are overridden before SDK creation without writing on read", () => {
  const f = fixture({ enableInstallTelemetry: true, enableAnalytics: true, cacheWarming: "idle", compaction: { enabled: true } });
  const original = readFileSync(f.path), { snapshot } = createOfficialSettings(f);
  for (const [key, value] of Object.entries(enforced)) assert.equal(snapshot()[key], value);
  assert.deepEqual(readFileSync(f.path), original);
});

for (const key of ["packages", "extensions", "skills", "prompts", "themes"]) test("nonempty automatic resource " + key + " is never silently emptied", () => {
  const f = fixture({ [key]: ["synthetic-secret-source"] }), original = readFileSync(f.path);
  assert.throws(() => createOfficialSettings(f), error => !error.message.includes("synthetic-secret-source"));
  assert.equal(f.observations.calls, 0); assert.deepEqual(readFileSync(f.path), original);
});

for (const value of [{ auth: "synthetic-secret" }, { retry: { maxRetries: true } }, { compaction: { unknown: 1 } }, { terminal: { images: "png" } },
  { modelThinkingLevels: { chosen: "unknown" } }, { compaction: { modelOverrides: { chosen: { token: "synthetic-secret" } } } },
  { markdown: { mermaid: "auto" } }, { outputPad: 2 }, { tuiMode: "other" }, { transport: "fetch" }, { defaultThinkingLevel: "auto" },
  { fullscreenScrollbar: "other" }, { images: { blockImages: 1 } }, { warnings: { anthropicExtraUsage: "yes" } }, { codemode: { mode: "off" } },
  { thinkingBudgets: { xhigh: 123 } }, { defaultProjectTrust: "always" }, { httpProxy: "https://synthetic-secret@invalid" },
  { shellCommandPrefix: "TOKEN=synthetic-secret" }, { npmCommand: ["npm", "--token", "synthetic-secret"] },
  { trackingId: "synthetic-secret" }, { deviceId: "synthetic-secret" }]) test("unsafe or unknown setting fails closed: " + Object.keys(value)[0], () => {
  const f = fixture(value), original = readFileSync(f.path);
  assert.throws(() => createOfficialSettings(f), error => error.message.startsWith("pi-settings-") && !error.message.includes("synthetic-secret"));
  assert.equal(f.observations.calls, 0); assert.deepEqual(readFileSync(f.path), original);
});

for (const raw of ["[]", "null", "{\"theme\":\"dark\",\"theme\":\"light\"}", "{\"httpProxy\":\"synthetic-secret\",\"httpProxy\":\"\"}", "{\"editorPaddingX\":1e999}", "{\"editorPaddingX\":NaN}"])
  test("malformed, nonobject, duplicate, or nonfinite JSON is refused", () => {
    const f = fixture(raw); assert.throws(() => createOfficialSettings(f), /pi-settings-/); assert.equal(f.observations.calls, 0);
  });

test("known nested fields and public enums are retained without probing runtime", () => {
  const value = { compaction: { enabled: true, reserveTokens: 10, keepRecentTokens: 20, modelOverrides: { "fictional/model": { reserveTokens: 30, keepRecentTokens: 40 } } },
    retry: { enabled: false, maxRetries: 1, baseDelayMs: 2, maxAgentDelayMs: 3, provider: { timeoutMs: 4, maxRetries: 5, maxRetryDelayMs: 6 } },
    branchSummary: { reserveTokens: 12, skipPrompt: true }, terminal: { hyperlinks: "auto", images: "kitty", trueColor: "auto", showImages: true },
    markdown: { codeBlockIndent: "  ", mermaid: "final" }, modelThinkingLevels: { "fictional/model": "xhigh" }, thinkingBudgets: { minimal: 1, low: 2, medium: 3, high: 4 },
    images: { autoResize: true, blockImages: false }, warnings: { anthropicExtraUsage: false }, codemode: { mode: "only", inlineBudget: 123 },
    defaultThinkingLevel: "max", transport: "websocket-cached", tuiMode: "fullscreen", fullscreenExitOutput: "resume-hint", fullscreenScrollbar: "auto", fullscreenWheelScrollLines: "auto",
    shellPath: "/synthetic/bin/shell", externalEditor: "/synthetic/bin/editor", packages: [], extensions: [], skills: [], prompts: [], themes: [] };
  const f = fixture(value), { snapshot } = createOfficialSettings(f);
  assert.deepEqual(snapshot(), { ...value, ...enforced });
});

test("native UI update saves only validated global settings and snapshot reflects it", () => {
  const f = fixture({ theme: "dark" }), { settingsManager, snapshot } = createOfficialSettings(f);
  settingsManager.setTheme("light");
  assert.equal(snapshot().theme, "light");
  assert.deepEqual(JSON.parse(readFileSync(f.path, "utf8")), { theme: "light", ...enforced });
});
test("native asynchronous settings save refuses identity until public flush completes", async () => {
  const f = fixture({ theme: "dark" }, { deferredWrites: true }), { settingsManager, snapshot } = createOfficialSettings(f);
  settingsManager.setTheme("light");
  assert.throws(() => snapshot(), /pi-settings-stale/);
  assert.equal(JSON.parse(readFileSync(f.path, "utf8")).theme, "dark");
  await settingsManager.flush(); assert.equal(snapshot().theme, "light");
});
test("native write queue swallowing a failed save cannot restore a usable identity", async () => {
  const f = fixture({ theme: "dark" }, { deferredWrites: true }), { settingsManager, snapshot } = createOfficialSettings(f);
  settingsManager.setTheme(123); await settingsManager.flush();
  assert.equal(JSON.parse(readFileSync(f.path, "utf8")).theme, "dark");
  assert.throws(() => snapshot(), /pi-settings-invalid/);
});

for (const value of [{ unknown: true }, { theme: 123 }, { packages: ["bad"] }, { enableAnalytics: true }, { cacheWarming: "streaming" }, { trackingId: "synthetic-secret" }])
  test("invalid storage write cannot change the file", () => {
    const f = fixture(), { snapshot } = createOfficialSettings(f), original = readFileSync(f.path);
    assert.throws(() => f.observations.storage.withLock("global", () => JSON.stringify(value)), /pi-settings-/);
    assert.deepEqual(readFileSync(f.path), original); assert.deepEqual(snapshot(), enforced);
  });

test("project writes and storage reentry are rejected without creating another file", () => {
  const f = fixture(), { snapshot } = createOfficialSettings(f), original = readFileSync(f.path);
  assert.throws(() => f.observations.storage.withLock("project", () => "{}"), /pi-settings-project-write/);
  assert.throws(() => f.observations.storage.withLock("global", () => { f.observations.storage.withLock("global", () => undefined); }), /pi-settings-reentry/);
  assert.deepEqual(readFileSync(f.path), original); assert.deepEqual(snapshot(), enforced);
});

for (const fault of ["disk", "manager", "unknown-manager", "policy-manager"]) test("snapshot refuses inconsistent " + fault + " state", () => {
  const f = fixture({ theme: "dark" }), { settingsManager, snapshot } = createOfficialSettings(f);
  if (fault === "disk") writeFileSync(f.path, JSON.stringify({ theme: "changed" }), { mode: 0o600 });
  if (fault === "manager") f.mutateManager(settingsManager, value => { value.theme = "changed"; });
  if (fault === "unknown-manager") f.mutateManager(settingsManager, value => { value.credentials = "synthetic-secret"; });
  if (fault === "policy-manager") f.mutateManager(settingsManager, value => { value.enableAnalytics = true; });
  assert.throws(snapshot, error => error.message.startsWith("pi-settings-") && !error.message.includes("synthetic-secret"));
});

for (const fault of ["mode", "symlink", "hardlink", "auth", "models"]) test("private settings path rejects " + fault, () => {
  const f = fixture(); let path = f.path;
  if (fault === "mode") chmodSync(path, 0o644);
  if (fault === "symlink") { path = join(f.root, "linked-settings.json"); symlinkSync(f.path, path); }
  if (fault === "hardlink") { path = join(f.root, "hard-settings.json"); linkSync(f.path, path); }
  if (fault === "auth" || fault === "models") { path = join(f.root, fault + ".json"); writeFileSync(path, "synthetic-secret", { mode: 0o600 }); }
  assert.throws(() => createOfficialSettings({ ...f, path }), error => !error.message.includes("synthetic-secret"));
  assert.equal(f.observations.calls, 0);
});


for (const key of ["externalEditor", "shellPath"]) for (const value of ["editor --token=synthetic-secret", "relative-editor", "/absolute/editor --wait", "https://synthetic.invalid/editor"])
  test(key + " refuses commands, relative paths, whitespace and URLs", () => {
    const f = fixture({ [key]: value });
    assert.throws(() => createOfficialSettings(f), error => error.message === "pi-settings-invalid");
    assert.equal(f.observations.calls, 0);
  });

test("failed native setter leaves disk intact and stale manager cannot issue a snapshot", () => {
  const f = fixture({ theme: "dark" }), { settingsManager, snapshot } = createOfficialSettings(f), original = readFileSync(f.path);
  assert.throws(() => settingsManager.setTheme(123), /pi-settings-invalid/);
  assert.deepEqual(readFileSync(f.path), original);
  assert.throws(snapshot, /pi-settings-invalid/);
});

test("async write callback is rejected because the storage transaction is synchronous", () => {
  const f = fixture(), { snapshot } = createOfficialSettings(f), original = readFileSync(f.path);
  assert.throws(() => f.observations.storage.withLock("global", async () => "{}"), /pi-settings-invalid/);
  assert.deepEqual(readFileSync(f.path), original); assert.deepEqual(snapshot(), enforced);
});

for (const [legacy, modern] of [
  [{ queueMode: "one-at-a-time" }, { steeringMode: "one-at-a-time" }],
  [{ websockets: true }, { transport: "websocket" }],
  [{ websockets: false }, { transport: "sse" }],
  [{ skills: { enableSkillCommands: false, customDirectories: [] } }, { skills: [], enableSkillCommands: false }],
  [{ skills: {} }, { skills: [] }],
  [{ retry: { maxDelayMs: 123, enabled: false, provider: { timeoutMs: 45 } } }, { retry: { enabled: false, provider: { timeoutMs: 45, maxRetryDelayMs: 123 } } }],
]) test("legacy settings normalize only on read: " + JSON.stringify(legacy), () => {
  const f = fixture(legacy), original = readFileSync(f.path), { settingsManager, snapshot } = createOfficialSettings(f);
  assert.deepEqual(snapshot(), { ...modern, ...enforced });
  assert.deepEqual(readFileSync(f.path), original);
  settingsManager.setTheme("light");
  assert.deepEqual(JSON.parse(readFileSync(f.path, "utf8")), { ...modern, ...enforced, theme: "light" });
});

for (const legacy of [
  { queueMode: "all", steeringMode: "all" }, { websockets: false, transport: "sse" },
  { skills: { enableSkillCommands: true }, enableSkillCommands: true },
  { retry: { maxDelayMs: 1, provider: { maxRetryDelayMs: 1 } } },
]) test("legacy and modern sources conflict even when equal", () => {
  const f = fixture(legacy), original = readFileSync(f.path);
  assert.throws(() => createOfficialSettings(f), /pi-settings-conflicting-legacy/);
  assert.equal(f.observations.calls, 0); assert.deepEqual(readFileSync(f.path), original);
});

for (const legacy of [
  { queueMode: "unknown" }, { websockets: 1 }, { skills: { enableSkillCommands: 1 } },
  { skills: { customDirectories: ["synthetic-secret"] } }, { skills: { customDirectories: "" } },
  { skills: { unknown: true } }, { retry: { maxDelayMs: true } }, { retry: { maxDelayMs: 1, provider: [] } },
]) test("legacy settings preserve strict types and resource boundaries", () => {
  const f = fixture(legacy), original = readFileSync(f.path);
  assert.throws(() => createOfficialSettings(f), error => error.message.startsWith("pi-settings-") && !error.message.includes("synthetic-secret"));
  assert.equal(f.observations.calls, 0); assert.deepEqual(readFileSync(f.path), original);
});

for (const legacy of [{ queueMode: "all" }, { websockets: true }, { skills: {} }, { retry: { maxDelayMs: 1 } }])
  test("storage writes and effective manager reject legacy shape", () => {
    const f = fixture(), { settingsManager, snapshot } = createOfficialSettings(f), original = readFileSync(f.path);
    assert.throws(() => f.observations.storage.withLock("global", () => JSON.stringify(legacy)), /pi-settings-invalid/);
    assert.deepEqual(readFileSync(f.path), original);
    f.mutateManager(settingsManager, value => Object.assign(value, legacy));
    assert.throws(snapshot, /pi-settings-invalid/);
  });

test("only a missing settings file in a verified private directory receives defaults", () => {
  const f = fixture(); unlinkSync(f.path);
  assert.equal(createOfficialSettings(f).snapshot().defaultProjectTrust, "never");
  rmSync(f.root, { recursive: true });
  assert.throws(() => createOfficialSettings(f), error => error.message === "pi-settings-private");
});
