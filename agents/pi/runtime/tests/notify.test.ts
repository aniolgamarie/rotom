import assert from "node:assert/strict";
import { test } from "node:test";
import { notificationSequence } from "../../extensions/notify.ts";

test("terminal notification modes contain fixed content and require no subprocess", () => {
  assert.equal(notificationSequence("off"), "");
  assert.equal(notificationSequence("bell"), "\x07");
  assert.match(notificationSequence("osc99"), /Ready for input/);
  assert.match(notificationSequence("osc777"), /777;notify;Pi/);
  assert.throws(() => notificationSequence("powershell"), /TERMINAL_NOTIFICATION_MODE/);
});
