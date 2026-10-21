import assert from "node:assert/strict";
import test from "node:test";
import { apply as registerContext } from "../../agents/dsh/packages/review-context/index.mjs";
import { apply as restrictReviewer } from "../../agents/dsh/packages/review-context/reviewer.mjs";

test("context tool supplies fixed boundaries without granting user authorization", async () => {
  const registered = [];
  registerContext({ get(name) {
    assert.equal(name, "tools");
    return { register: (tool) => registered.push(tool) };
  } });
  assert.equal(registered.length, 1);
  const tool = registered[0];
  assert.equal(tool.name, "rotom_review_context");
  assert.equal(tool.parameters.additionalProperties, false);
  const value = await tool.execute();
  assert.equal(await tool.execute(), value);
  assert.match(value, /AI 路由不等于批准/);
  assert.match(value, /不提供当前用户任务或授权证据/);
  assert.deepEqual(tool.output.render({}, value), [{ type: "text", text: value }]);
});

test("reviewer requests a scope restriction containing only the inherited constant tool", () => {
  const restrictions = [];
  restrictReviewer({ get(name) {
    assert.equal(name, "tools");
    return { restrict: (filter) => restrictions.push(filter) };
  } });
  assert.deepEqual(restrictions, [{ allow: ["rotom_review_context"] }]);
});

test("invalid reviewer scope or missing inherited tool fails activation without weakening the mask", () => {
  const failure = new Error("synthetic invalid reviewer scope");
  let attempts = 0;
  assert.throws(() => restrictReviewer({ get(name) {
    assert.equal(name, "tools");
    return { restrict() { attempts += 1; throw failure; } };
  } }), (error) => error === failure);
  assert.equal(attempts, 1);
});
