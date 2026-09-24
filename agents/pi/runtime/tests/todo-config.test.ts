import assert from "node:assert/strict";
import { test } from "node:test";
import { loadConfig, validateGuidanceFields, getMaxWidgetLines, resolveCollapseKey } from "../../packages/todo-vendor/config.ts";
import { t } from "../../packages/todo-vendor/state/i18n-bridge.ts";
const key = Symbol.for("agentcfg.pi.runtime.v1");

test("Todo settings and locale use only the selected instance, preserving empty guidance", () => {
  try {
    globalThis[key] = { owner: { role: "manager" }, manifest: { plugins: ["pi-todo"], options: { todo: {
      locale: "zh", maxWidgetLines: 4, collapseKey: "off", guidance: { promptSnippet: "", promptGuidelines: [] } } } } };
    assert.equal(getMaxWidgetLines(), 4); assert.equal(resolveCollapseKey(), "off");
    assert.deepEqual(validateGuidanceFields(loadConfig().guidance), { promptSnippet: "", promptGuidelines: [] });
    assert.notEqual(t("status.completed", "completed"), "completed");
    assert.equal(t("absent", "fallback"), "fallback");
    globalThis[key].manifest.options.todo.locale = "../../outside";
    assert.throws(() => t("status.completed", "completed"), /PI_TODO_LOCALE_INVALID/);
    globalThis[key].manifest.plugins = [];
    assert.throws(loadConfig, /CAPABILITY_NOT_SELECTED/);
  } finally { delete globalThis[key]; }
});

test("Todo guidance rejects unknown fields and invalid values", () => {
  for (const value of [{ credentials: "synthetic" }, { promptSnippet: false }, { promptGuidelines: [42] }]) {
    assert.throws(() => validateGuidanceFields(value), /PI_TODO_CONFIG_INVALID/);
  }
});
