import test from "node:test";
import assert from "node:assert/strict";
import { parseFdFlags, captureBinding, matchesBinding } from "../scripts/pi-probe-owner-fd-facts.mjs";

const original = { device: "9007199254740993", inode: "1152921504606846977", uid: 0, mode: 0o600, nlink: 1 };
test("actual octal flags select CLOEXEC bit rather than metadata or decimal", () => {
  assert.deepEqual(parseFdFlags("pos:\t0\nflags:\t02000002\nmnt_id:\t19\nino:\t80\n"), { flags: "2000002", cloexec: true });
  assert.equal(parseFdFlags("flags:\t0100000\n").cloexec, false);
});
for (const [name, value] of Object.entries({ missing: "pos:\t0\n", duplicate: "flags:\t02000002\nflags:\t02000002\n", hiddenDuplicate: "flags:\t02000002\n flags:\t02\n", decimalInvalid: "flags:\t29\n", sign: "flags:\t-02\n", extra: "flags:\t02 trailing\n", overflow: "flags:\t7777777777777777777777\n", tooLong: "flags:\t02\n" + "x".repeat(4096) })) {
  test(`reject fdinfo ${name}`, () => assert.throws(() => parseFdFlags(value), { message: "owner fd facts invalid" }));
}
test("bigint identity remains exact above Number safe range", () => {
  const binding = captureBinding(original);
  const info = { dev: 9007199254740993n, ino: 1152921504606846977n, uid: 0n, mode: 0o100600n, nlink: 1n };
  assert.equal(matchesBinding(info, binding), true);
  assert.equal(matchesBinding({ ...info, dev: 9007199254740992n }, binding), false);
  assert.equal(matchesBinding({ ...info, ino: 1152921504606846976n }, binding), false);
  assert.equal(matchesBinding({ ...info, mode: 0o100644n }, binding), false);
  assert.equal(matchesBinding({ ...info, mode: 0o20600n }, binding), false);
  assert.equal(matchesBinding({ ...info, nlink: 2n }, binding), false);
  assert.ok(Object.isFrozen(binding));
  original.uid = 4; assert.equal(binding.uid, 0); original.uid = 0;
});
for (const [name, change] of Object.entries({ missing: v => delete v.uid, extra: v => v.fd = 3, leadingZero: v => v.device = "01", number: v => v.inode = Number(v.inode), overflow: v => v.inode = String(1n << 64n), zeroInode: v => v.inode = "0", boolean: v => v.uid = true, mode: v => v.mode = 0o644, links: v => v.nlink = 2 })) {
  test(`reject binding ${name}`, () => { const value = { ...original }; change(value); assert.throws(() => captureBinding(value), { message: "owner fd facts invalid" }); });
}
test("accessor and Proxy traps never run", () => {
  let calls = 0; const value = { ...original };
  Object.defineProperty(value, "uid", { enumerable: true, get() { calls++; throw new Error("SYNTHETIC_SECRET"); } });
  assert.throws(() => captureBinding(value), { message: "owner fd facts invalid" });
  const proxy = new Proxy(original, { getPrototypeOf() { calls++; throw new Error("SYNTHETIC_SECRET"); } });
  assert.throws(() => captureBinding(proxy), { message: "owner fd facts invalid" });
  const revoked = Proxy.revocable(original, {}); revoked.revoke();
  assert.throws(() => captureBinding(revoked.proxy), { message: "owner fd facts invalid" });
  assert.equal(calls, 0);
});
