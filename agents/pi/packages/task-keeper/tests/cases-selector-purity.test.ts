import { test, assert, evidence } from "./recorded-test.ts";
import { readFileSync } from "node:fs";
import * as crypto from "node:crypto";
import { createContext, runInContext } from "node:vm";
import ts from "typescript";

const policySource = readFileSync(new URL("../src/orchestration/policy.ts", import.meta.url), "utf8");
const primitivesSource = readFileSync(new URL("../src/contracts/primitives.ts", import.meta.url), "utf8");
const input = { enabled: ["direct", "critique"], qualityFailure: false, environmentFailure: false, upgradeEligible: true, criticEligible: true,
  upgradesUsed: 0, critiquesUsed: 0, semanticAttempts: 1, maxSemanticAttempts: 3, stepsUsed: 1, maxSteps: 16, remainingRequests: 4, requiredReserve: 2, finding: null };

// Architecture fixture, not a security boundary for arbitrary hostile JavaScript.
function run(source: string, data = input) {
  const trap = (name: string) => () => { throw new Error(`SELECTOR_SIDE_EFFECT:${name}`); };
  const context = createContext({ setTimeout: trap("timer"), setInterval: trap("timer"), fetch: trap("network"),
    process: new Proxy({}, { get() { throw new Error("SELECTOR_SIDE_EFFECT:process"); } }) });
  let primitives: unknown;
  const requireFixture = (name: string) => {
    if (name === "node:crypto") return crypto;
    if (name === "../contracts/primitives.ts") return primitives;
    throw new Error(`SELECTOR_SIDE_EFFECT:import:${name}`);
  };
  const load = (text: string) => {
    const code = ts.transpileModule(text, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
    const module = { exports: {} };
    runInContext(`(function(exports,require,module){${code}\n})`, context, { timeout: 1000 })(module.exports, requireFixture, module);
    return module.exports;
  };
  primitives = load(primitivesSource); context.policy = load(source); context.inputJson = JSON.stringify(data);
  return JSON.parse(JSON.stringify(runInContext("policy.recipePolicy(JSON.parse(inputJson))", context, { timeout: 1000 })));
}

test("[U RTB-017 T88] the actual selector needs no effectful capabilities and timer, process and write mutations are rejected", () => {
  for (const id of ["RTB-017", "T88"]) evidence(id, () => {
    assert.equal(run(policySource).action, "critic");
    assert.equal(run(policySource, { ...input, qualityFailure: true }).action, "critic");
    assert.equal(run(policySource, { ...input, critiquesUsed: 1 }).action, "direct");
    for (const effect of ["setTimeout(()=>{},1);", "require('node:child_process').spawn('untrusted');", "require('node:fs').writeFileSync('untrusted','bad');"]) {
      const point = "export function recipePolicy(input: RecipeInput) {";
      assert.equal(policySource.split(point).length, 2);
      assert.throws(() => run(policySource.replace(point, `${point}\n${effect}`)), /SELECTOR_SIDE_EFFECT/);
    }
  });
});

test("[S RTB-017 T88] a selector remains effect-free across critique and repair state transitions", () => {
  const states = [
    { ...input },
    { ...input, critiquesUsed: 1, stepsUsed: 2 },
    { ...input, critiquesUsed: 1, stepsUsed: 3, qualityFailure: true },
    { ...input, critiquesUsed: 1, upgradesUsed: 1, stepsUsed: 4, semanticAttempts: 2, qualityFailure: true },
    { ...input, critiquesUsed: 1, upgradesUsed: 1, stepsUsed: 16, semanticAttempts: 2, qualityFailure: true },
  ];
  const expected = ["critic", "direct", "direct", "direct", "block"], before = structuredClone(states);
  for (const id of ["RTB-017", "T88"]) evidence(id, () => {
    const trace = states.map((state, index) => ({ index, action: run(policySource, state).action }));
    assert.deepEqual(trace.map(row => row.action), expected); assert.deepEqual(states, before);
    for (const effect of ["setTimeout(()=>{},1);", "require('node:child_process').spawn('untrusted');", "require('node:fs').writeFileSync('untrusted','bad');"]) {
      const point = "export function recipePolicy(input: RecipeInput) {";
      const changed = policySource.replace(point, `${point}\nif(input.critiquesUsed > 0){${effect}}`);
      assert.equal(run(changed, states[0]).action, "critic");
      for (const state of states.slice(1)) assert.throws(() => run(changed, state), /SELECTOR_SIDE_EFFECT/);
    }
    assert.deepEqual(states.map(state => run(policySource, state).action), expected);
  });
});
