import assert from "node:assert/strict";
import test from "node:test";
import { readDevelopmentEnvironment, subprocessEnvironment, mcpArguments } from "../../agents/dsh/packages/execution-environment/environment.mjs";

const PAYLOAD = "AGENTCFG_DEVELOPMENT_ENV";
const value = (values = {}, unset = []) => ({ version: 1, values: { HOME: "/synthetic/caller", PATH: "/synthetic/bin", ...values }, unset });
const read = payload => readDevelopmentEnvironment({ [PAYLOAD]: JSON.stringify(payload) });

for (const [name, payload] of [
  ["missing", undefined], ["invalid JSON", "synthetic-private-{"], ["null", "null"],
  ["array", "[]"], ["string", '"synthetic-private"'],
]) {
  test(`rejects ${name} without disclosing input`, () => {
    assert.throws(() => readDevelopmentEnvironment({ [PAYLOAD]: payload }),
      { message: "Invalid development environment payload" });
  });
}

for (const [name, payload] of [
  ["version", { ...value(), version: 2 }],
  ["extra field", { ...value(), extra: "synthetic-private" }],
  ["missing unset", { version: 1, values: { HOME: "/synthetic" } }],
  ["null values", { ...value(), values: null }],
  ["array values", { ...value(), values: [] }],
  ["numeric value", value({ MODE: 42 })],
  ["NUL value", value({ MODE: "synthetic\0private" })],
  ["bad name", value({ "INVALID=NAME": "synthetic-private" })],
  ["missing HOME", { version: 1, values: {}, unset: [] }],
  ["relative HOME", value({ HOME: "relative" })],
  ["empty HOME", value({ HOME: "" })],
  ["unset HOME", value({}, ["HOME"])],
  ["relative XDG", value({ XDG_CONFIG_HOME: "relative" })],
  ["empty XDG", value({ XDG_DATA_HOME: "" })],
  ["unset nonarray", { ...value(), unset: "MODE" }],
  ["unset nonstring", value({}, [3])],
  ["duplicate unset", value({}, ["MODE", "MODE"])],
  ["unset conflict", value({ MODE: "synthetic" }, ["MODE"])],
]) {
  test(`rejects malformed ${name} with a constant error`, () => {
    assert.throws(() => read(payload), { message: "Invalid development environment payload" });
  });
}

for (const name of ["DSH_HOME", "AGENTCFG_PROFILE", "AGENTCFG_MCP_ENV_ARGS",
  "API_KEY", "PROVIDER_TOKEN", "REFRESH_TOKEN", "AUTHORIZATION", "CREDENTIAL_REF", "db_password",
  "BASH_ENV", "ENV", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "NODE_OPTIONS", "NODE_PATH",
  "PYTHONSTARTUP", "PYTHONINSPECT", "npm_config_userconfig"]) {
  test(`rejects reserved ${name} in values and unset`, () => {
    for (const payload of [value({ [name]: "synthetic-private" }), value({}, [name])]) {
      assert.throws(() => read(payload), { message: "Invalid development environment payload" });
    }
  });
}

test("accepts empty ordinary values and freezes an independent snapshot", () => {
  const input = value({ MODE: "", XDG_CONFIG_HOME: "/synthetic/config" });
  const snapshot = read(input);
  input.values.MODE = "changed";
  assert.equal(snapshot.values.MODE, "");
  assert.ok(Object.isFrozen(snapshot));
  assert.ok(Object.isFrozen(snapshot.values));
  assert.ok(Object.isFrozen(snapshot.unset));
});

test("tool explicit env survives except caller identity, final unset and internal payloads", () => {
  const snapshot = read(value({ MODE: "snapshot", XDG_CONFIG_HOME: "/synthetic/config" }, ["UNSET_ME"]));
  const explicit = { MODE: "tool", HOME: "/synthetic/private-host", XDG_CONFIG_HOME: "/synthetic/host-config",
    XDG_CACHE_HOME: "/synthetic/host-cache", UNSET_ME: "tool", TOOL_API_KEY: "explicit-synthetic-credential",
    [PAYLOAD]: "must-not-forward", AGENTCFG_MCP_ENV_ARGS: "must-not-forward" };
  const original = { ...explicit };
  const env = subprocessEnvironment(explicit, snapshot);
  assert.deepEqual(explicit, original);
  assert.equal(env.MODE, "tool");
  assert.equal(env.TOOL_API_KEY, "explicit-synthetic-credential");
  assert.equal(env.HOME, "/synthetic/caller");
  assert.equal(env.XDG_CONFIG_HOME, "/synthetic/config");
  for (const name of ["XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
    "UNSET_ME", PAYLOAD, "AGENTCFG_MCP_ENV_ARGS"]) {
    assert.ok(Object.hasOwn(env, name), `requires tombstone for ${name}`);
    assert.equal(env[name], undefined);
  }
});

test("PATH unset stays absent after explicit tool env; ordinary explicit PATH is preserved", () => {
  const snapshot = read({ version: 1, values: { HOME: "/synthetic/caller" }, unset: ["PATH"] });
  assert.equal(subprocessEnvironment({ PATH: "/synthetic/host-bin" }, snapshot).PATH, undefined);
  assert.equal(subprocessEnvironment({ PATH: "/synthetic/tool-bin" }, read(value())).PATH, "/synthetic/tool-bin");
  assert.equal(subprocessEnvironment({}, read({ version: 1, values: { HOME: "/synthetic/caller" }, unset: [] })).PATH, undefined);
});

test("prototype-shaped ordinary name is an own tombstone", () => {
  const env = subprocessEnvironment({}, read(value({}, ["__proto__"])));
  assert.ok(Object.hasOwn(env, "__proto__"));
  assert.equal(env.__proto__, undefined);
});

test("MCP argv removes payloads and omitted identities without a shell or relay", () => {
  const argv = mcpArguments("/synthetic/server", ["--argument", "space ; $(literal)"],
    read(value({ MODE: "space ; $(literal)", EMPTY: "" }, ["UNSET_ME"])));
  assert.equal(argv[0], "/usr/bin/env");
  const separator = argv.indexOf("--");
  const options = argv.slice(1, separator);
  assert.equal(options.length % 2, 0);
  const removed = new Set();
  for (let index = 0; index < options.length; index += 2) {
    assert.equal(options[index], "-u");
    removed.add(options[index + 1]);
  }
  assert.deepEqual(removed, new Set([PAYLOAD, "AGENTCFG_MCP_ENV_ARGS", "UNSET_ME", "XDG_CONFIG_HOME",
    "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"]));
  assert.deepEqual(argv.slice(separator + 1, -3), ["EMPTY=", "HOME=/synthetic/caller", "MODE=space ; $(literal)", "PATH=/synthetic/bin"]);
  assert.deepEqual(argv.slice(-3), ["/synthetic/server", "--argument", "space ; $(literal)"]);
  // launch.mjs 使用占位 command 截取 prefix；必须恰好保留删除参数和赋值。
  const prefix = mcpArguments("rotom-placeholder", [], read(value())).slice(1, -1);
  assert.deepEqual(["/usr/bin/env", ...prefix, "/synthetic/server"], mcpArguments("/synthetic/server", [], read(value())));
});

test("MCP PATH deletion emits -u rather than forwarding a host search path", () => {
  const argv = mcpArguments("/synthetic/server", [], read({ version: 1,
    values: { HOME: "/synthetic/caller" }, unset: ["PATH", "SHELL"] }));
  assert.ok(argv.includes("PATH"));
  assert.ok(argv.includes("SHELL"));
  assert.ok(!argv.some(arg => arg.startsWith("PATH=")));
});

test("MCP rejects malformed argv without echoing it", () => {
  for (const [command, args] of [["", []], ["MODE=assignment", []], ["private\0command", []], ["server", ["private\0argument"]], ["server", [42]]]) {
    assert.throws(() => mcpArguments(command, args, read(value())),
      { message: "Invalid development environment payload" });
  }
});

test("internal ambient credentials get tombstones and argv deletion without reading values", () => {
  const name = "AGENTCFG_MCP_0123456789ABCDEF";
  const original = process.env[name];
  process.env[name] = "synthetic-secret-never-forwarded";
  try {
    const environment = subprocessEnvironment({ [name]: "synthetic-explicit" }, read(value()));
    assert.equal(environment[name], undefined);
    const argv = mcpArguments("/synthetic/server", [], read(value()));
    assert.ok(argv.includes(name));
    assert.ok(!JSON.stringify(argv).includes("synthetic-secret-never-forwarded"));
    assert.equal(process.env[name], "synthetic-secret-never-forwarded");
  } finally {
    if (original === undefined) delete process.env[name]; else process.env[name] = original;
  }
});

test("MCP never falls back to a system search path when PATH is absent or empty", () => {
  for (const values of [{ HOME: "/synthetic/caller" }, { HOME: "/synthetic/caller", PATH: "" }]) {
    assert.throws(() => mcpArguments("true", [], read({ version: 1, values, unset: [] })));
    assert.equal(mcpArguments("/synthetic/server", [], read({ version: 1, values, unset: [] })).at(-1), "/synthetic/server");
  }
});
