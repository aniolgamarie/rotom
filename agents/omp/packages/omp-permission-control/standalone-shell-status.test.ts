import { describe, expect, test } from "bun:test";
import { parseGenericCommands, hasUncertainPatternMatch, matchesNativePattern, visiblePrefixForDenial } from "./standalone-shell-analysis";

describe("numeric status output syntax", () => {
  test("retains numeric expansion positions without evaluating exit status", () => {
    expect(parseGenericCommands('ls missing 2>/dev/null; echo "exit=$?"; printf "%s\\n" $?')).toEqual({
      status: "complete", commands: [
        { connector: "start", argv: ["ls", "missing"], redirections: [{ fd: 2, operator: ">", target: "/dev/null" }] },
        { connector: ";", argv: ["echo", "exit=$?"], statusExpansions: [1] },
        { connector: ";", argv: ["printf", "%s\\n", "$?"], statusExpansions: [2] },
      ],
    });
  });
  test("literal and escaped forms remain literal", () => {
    for (const command of ["echo '$?'", "echo \\$?", 'echo "\\$?"']) {
      const parsed = parseGenericCommands(command);
      expect(parsed).toEqual({ status: "complete", commands: [{ connector: "start", argv: ["echo", "$?"], ...(command === "echo \\$?" ? { globs: [1] } : {}) }] });
    }
  });
  test("numeric output cannot resolve a configured exact native rule", () => {
    const parsed = parseGenericCommands('echo "exit=$?"');
    expect(parsed.status).toBe("complete");
    if (parsed.status !== "complete") throw new Error("expected static syntax");
    expect(hasUncertainPatternMatch(parsed.commands[0], "echo exit=1")).toBe(true);
    expect(hasUncertainPatternMatch(parsed.commands[0], "printf 1")).toBe(false);
    expect(matchesNativePattern(parsed.commands[0], "echo *")).toBe(true);
    expect(visiblePrefixForDenial('rm file; echo $?; eval "$CMD"')[0].argv).toEqual(["rm", "file"]);
  });
  test("command heads, redirects, executable parameters and other expansion remain unsupported", () => {
    for (const command of [
      "$? arg", "foo$? arg", "cat $?", "git show $?", "command -v $?", "sh -c 'echo $?'", "eval $?",
      "echo ok >$?", "echo ok 2>&$?", "echo ${?}", "echo $!", "echo $$", "echo $1", "echo $PATH",
      "echo $?$(id)", 'echo "exit=$? $PATH"', "sleep 1 & echo $!", "echo $?$HOME",
    ]) expect(parseGenericCommands(command).status).toBe("unsupported");
  });
  test("quote concatenation and compounds retain status positions", () => {
    const parsed = parseGenericCommands('echo "exit=""$?" || /usr/bin/printf status=%s $?');
    expect(parsed).toEqual({ status: "complete", commands: [
      { connector: "start", argv: ["echo", "exit=$?"], statusExpansions: [1] },
      { connector: "||", argv: ["/usr/bin/printf", "status=%s", "$?"], statusExpansions: [2] },
    ] });
  });
});
