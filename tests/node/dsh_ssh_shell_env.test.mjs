import assert from "node:assert/strict";
import test from "node:test";
import { remoteShellEnvironment } from "../../agents/dsh/packages/ssh-shell-env/filter.mjs";

test("removes host directory facts and preserves session and plugin facts", () => {
  const snapshot = Object.freeze({
    DSH_HOME: "/synthetic/host/dsh",
    DSH_PROFILE_DIR: "/synthetic/host/dsh/profiles/fixture",
    DSH_SHELL: "1",
    DSH_SESSION_ID: "fixture-session",
    DSH_PROFILE: "fixture-profile",
    DSH_PLUGIN_FACT: "fixture-value",
  });
  const expected = {
    DSH_SHELL: "1",
    DSH_SESSION_ID: "fixture-session",
    DSH_PROFILE: "fixture-profile",
    DSH_PLUGIN_FACT: "fixture-value",
  };
  const before = { ...snapshot };
  const result = remoteShellEnvironment(snapshot);
  assert.deepEqual(result, expected);
  assert.deepEqual(snapshot, before);
  assert.notEqual(result, snapshot);
  assert.ok(Object.isFrozen(result));
  assert.throws(() => { result.DSH_HOME = "/synthetic/changed"; }, TypeError);
});

test("works without host paths and returns a fresh immutable snapshot each time", () => {
  const snapshot = { DSH_SHELL: "1", DSH_PROFILE: "" };
  const first = remoteShellEnvironment(snapshot);
  const second = remoteShellEnvironment(snapshot);
  assert.deepEqual(first, snapshot);
  assert.deepEqual(second, snapshot);
  assert.notEqual(first, second);
  snapshot.DSH_PROFILE = "changed";
  assert.equal(first.DSH_PROFILE, "");
  assert.ok(Object.isFrozen(first));
  assert.ok(Object.isFrozen(second));
  assert.deepEqual(remoteShellEnvironment({}), {});
  assert.ok(Object.isFrozen(remoteShellEnvironment({})));
});

test("filters only the two exact host keys", () => {
  const snapshot = {
    DSH_HOME: "/synthetic/host/dsh",
    DSH_PROFILE_DIR: "/synthetic/host/profile",
    DSH_HOME_HINT: "fixture-hint",
    DSH_PROFILE_DIRECTORY: "fixture-directory",
    DSH_PROFILE: "fixture",
  };
  assert.deepEqual(remoteShellEnvironment(snapshot), {
    DSH_HOME_HINT: "fixture-hint",
    DSH_PROFILE_DIRECTORY: "fixture-directory",
    DSH_PROFILE: "fixture",
  });
});
