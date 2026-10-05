import { test, expect } from "bun:test";
import { pathToFileURL } from "node:url";
import { extractFromAst, extractJavaScript } from "../scripts/extract-omp-history-js";

const identifier = (name: string) => ({ type: "Identifier", name });
const string = (value: string) => ({ type: "StringLiteral", value });
const member = () => ({ type: "MemberExpression", object: identifier("tools"), property: identifier("exec_command"), computed: false });
const property = (value: unknown) => ({ type: "ObjectProperty", key: identifier("cmd"), value, computed: false });
const call = (value: unknown) => ({ type: "CallExpression", callee: member(), arguments: [
  { type: "ObjectExpression", properties: [property(value)] },
] });

test("AST traversal reaches object children, awaits, arrays and nested wrappers in source order", () => {
  const ast = { type: "File", program: { type: "Program", body: [
    { type: "ExpressionStatement", expression: { type: "AwaitExpression", argument: call(string("pwd")) } },
    { type: "ExpressionStatement", expression: { type: "CallExpression", callee: identifier("text"), arguments: [
      call(string("ls -la")), call(string("git status --short")),
    ] } },
  ] } };
  expect(extractFromAst(ast)).toEqual({ commands: ["pwd", "ls -la", "git status --short"], unsupported: 0, malformed: false });
});

test("only literal strings or uninterpolated cooked templates are extracted", () => {
  const template = { type: "TemplateLiteral", expressions: [], quasis: [
    { type: "TemplateElement", value: { cooked: "printf '%s' sample" } },
  ] };
  expect(extractFromAst(call(template)).commands).toEqual(["printf '%s' sample"]);
  for (const value of [identifier("command"), { type: "BinaryExpression", operator: "+", left: string("ls "), right: string(".") },
    { ...template, expressions: [identifier("cwd")] }]) {
    expect(extractFromAst(call(value))).toEqual({ commands: [], unsupported: 1, malformed: false });
  }
});

test("duplicates, computed keys, spreads and aliases remain unresolved", () => {
  for (const properties of [[property(string("pwd")), property(string("ls"))],
    [{ ...property(string("pwd")), computed: true }], [property(string("pwd")), { type: "SpreadElement", argument: identifier("other") }]]) {
    expect(extractFromAst({ ...call(string("pwd")), arguments: [{ type: "ObjectExpression", properties }] }).unsupported).toBe(1);
  }
  expect(extractFromAst({ type: "VariableDeclarator", id: identifier("run"), init: member() })).toEqual({ commands: [], unsupported: 1, malformed: false });
  expect(extractFromAst({ type: "CallExpression", callee: identifier("run"), arguments: [] }).commands).toEqual([]);
});

test("optional shell calls are counted once; unrelated tools are excluded", () => {
  const callee = { ...member(), type: "OptionalMemberExpression", optional: true };
  expect(extractFromAst({ ...call(string("pwd")), type: "OptionalCallExpression", callee }).unsupported).toBe(1);
  expect(extractFromAst({ ...callee, property: identifier("read_file") }).unsupported).toBe(0);
  expect(extractFromAst({ type: "StringLiteral", value: 'tools.exec_command({cmd:"pwd"})' }).commands).toEqual([]);
});

test("unresolved tools aliases and bare or dynamic shell references are not classified as non-command", () => {
  const destructured = { type: "VariableDeclarator", init: identifier("tools"), id: {
    type: "ObjectPattern", properties: [{ type: "ObjectProperty", key: identifier("exec_command"), value: identifier("run") }],
  } };
  expect(extractFromAst(destructured).unsupported).toBe(1);
  expect(extractFromAst({ type: "VariableDeclarator", init: identifier("tools"), id: identifier("t") }).unsupported).toBe(1);
  for (const callee of [identifier("exec_command"), { ...member(), object: identifier("t") },
    { ...member(), computed: true, property: identifier("name") }]) {
    expect(extractFromAst({ ...call(string("pwd")), callee })).toEqual({ commands: [], unsupported: 1, malformed: false });
  }
  expect(extractFromAst({ ...destructured, id: { type: "ObjectPattern", properties: [
    { type: "ObjectProperty", key: identifier("read_file"), value: identifier("read_file") },
  ] } }).unsupported).toBe(0);
});

test("parse failures and oversized scripts return no source or exception text", () => {
  const marker = "PRIVATE_SYNTHETIC_SECRET";
  expect(extractJavaScript(marker, () => { throw new Error(marker); })).toEqual({ commands: [], unsupported: 1, malformed: true });
  let invoked = false;
  expect(extractJavaScript("x".repeat(2_000_001), () => { invoked = true; })).toEqual({ commands: [], unsupported: 1, malformed: true });
  expect(invoked).toBe(false);
});

// 默认测试无需外部库；显式指定本机已准备的库才运行真实 AST 集成，输入全是虚构文本。
test.skipIf(!process.env.OMP_HISTORY_JS_PARSER_MODULE)("real Babel parses synthetic orchestration without evaluating source", async () => {
  const module = await import(pathToFileURL(process.env.OMP_HISTORY_JS_PARSER_MODULE!).href);
  const parse = module.parse ?? module.default?.parse;
  const source = 'throw new Error("MUST_NOT_EXECUTE"); await Promise.all([tools.exec_command({cmd:"pwd"}), tools["exec_command"]({cmd:`ls -la`}), tools.exec_command({cmd:dynamic})]);';
  expect(extractJavaScript(source, parse)).toEqual({ commands: ["pwd", "ls -la"], unsupported: 1, malformed: false });
  expect(extractJavaScript('tools.exec_command({cmd:"pwd",cmd:"rm sample"})', parse).unsupported).toBe(1);
  expect(extractJavaScript('/* tools.exec_command({cmd:"ignored"}) */ text("tools.exec_command")', parse).commands).toEqual([]);
  for (const source of ['const {exec_command}=tools; await exec_command({cmd:"pwd"});',
    'const t=tools; await t.exec_command({cmd:"pwd"});', 'const {exec_command:run}=tools; await run({cmd:"pwd"});',
    'await tools[name]({cmd:"pwd"});']) {
    const result = extractJavaScript(source, parse);
    expect(result.commands).toEqual([]);
    expect(result.unsupported).toBeGreaterThan(0);
  }
  expect(extractJavaScript('const {read_file}=tools; await read_file({path:"sample"});', parse).unsupported).toBe(0);
  expect(extractJavaScript("tools.exec_command({cmd:}", parse).malformed).toBe(true);
});
