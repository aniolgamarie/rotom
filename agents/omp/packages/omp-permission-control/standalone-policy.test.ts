import { expect, test } from "bun:test";
import { checkConfiguredRules } from "./standalone-policy";

test("syntax analysis never becomes a permission gate without an actual restriction", () => {
  for (const command of ["for branch in main topic; do git log -1 \"$branch\"; done", "ls $HOME", "printf x | xargs echo"]) {
    expect(checkConfiguredRules(command, [])).toEqual({ decision: "allow", analysis: "unsupported", matchedRuleIds: [], uncertainRuleIds: [] });
  }
});
test("visible literal execution keeps both configured deny and prompt before model review", () => {
  for (const approval of ["deny", "prompt"] as const) for (const command of [
    "rm file; echo $(id)", "if rm -rf /; then ls; fi", "for name in a b; do rm file; done",
    "sudo rm file", "sudo -u owner rm file", "env KEY=value rm file", "env -i KEY=value sudo -u owner rm file",
    "command -p rm file", "printf x | xargs -n 1 rm", "timeout -s TERM 10 rm file",
    "sh -c 'rm file; echo $(id)'", "find . -exec rm file \\;",
    "awk 'BEGIN{system(\"rm file\")}'", "sed 'e rm file'",
  ]) expect(checkConfiguredRules(command, [{ match: "rm *", approval }]).decision).toBe(approval);
});
test("quoted data, comments, query arguments and unrelated programs do not invent rule matches", () => {
  for (const command of ["echo 'if rm file'", "echo if rm file", "echo 'rm file'", "echo ok # ; rm file",
    "command -v rm", "command -p -v rm", "env KEY=rm echo rm file", "sudo -u rm echo file",
    "python '-cprint(1)'", "for branch in main topic; do git log -1 \"$branch\"; done"]) {
    expect(checkConfiguredRules(command, [{ match: "rm *", approval: "deny" }]).decision).toBe("allow");
  }
});
test("uncertain targets stay separate from definite rule hits", () => {
  expect(checkConfiguredRules("cat *.txt", [{ match: "cat protected.txt", approval: "deny" }])).toMatchObject({
    decision: "allow", matchedRuleIds: [], uncertainRuleIds: [0], analysis: "complete" });
  expect(checkConfiguredRules("cat '*.txt'", [{ match: "cat protected.txt", approval: "deny" }])).toMatchObject({
    decision: "allow", matchedRuleIds: [], uncertainRuleIds: [] });
});
test("a deny after many prompt rules retains its decisive identity for bounded audit", () => {
  const rules = Array.from({ length: 70 }, () => ({ match: "rm *", approval: "prompt" as const }));
  const result = checkConfiguredRules("rm file", [...rules, { match: "rm *", approval: "deny" }]);
  expect(result.decision).toBe("deny"); expect(result.matchedRuleIds[0]).toBe(70);
});
