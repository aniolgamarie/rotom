import assert from "node:assert/strict";
import { test } from "node:test";
import { readseekRgArguments } from "../readseek-rg.ts";

test("rg retains SDK flags and pattern while searching exactly the exported file selection", () => {
  const argv = ["--json", "--line-number", "--color=never", "--hidden", "--ignore-case", "--fixed-strings", "--glob", "*.ts", "--", "--pre=literal-text", "/snapshot/src"];
  assert.deepEqual(readseekRgArguments(argv, "/snapshot"), ["--no-config", "--no-ignore", ...argv]);
});
test("rg shim cannot accept executable preprocessors, extra paths or paths outside its private snapshot", () => {
  const base = ["--json", "--line-number", "--color=never", "--hidden"];
  for (const rest of [["--pre", "program", "--", "text", "/snapshot"], ["--", "text", "/outside"],
    ["--", "text", "/snapshot/../outside"], ["--", "text", "/snapshot", "/second"]]) {
    assert.throws(() => readseekRgArguments([...base, ...rest], "/snapshot"), /INVALID/);
  }
});
