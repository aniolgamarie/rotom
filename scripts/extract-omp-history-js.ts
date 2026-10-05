/** 私有管道组件：只解析日志文本的 AST，不执行文本或解析所得命令。 */
import { createInterface } from "node:readline";
import { isAbsolute } from "node:path";
import { pathToFileURL } from "node:url";

interface AstNode { type: string; [key: string]: unknown }
interface JsExtraction { commands: string[]; unsupported: number; malformed: boolean }
type Parse = (source: string, options: Record<string, unknown>) => unknown;

function node(value: unknown): value is AstNode {
  return !!value && typeof value === "object" && !Array.isArray(value) && typeof (value as AstNode).type === "string";
}

function shellMember(value: unknown, optional = false): boolean {
  if (!node(value) || (value.type !== "MemberExpression" && !(optional && value.type === "OptionalMemberExpression")) || !node(value.object) ||
      value.object.type !== "Identifier" || value.object.name !== "tools" || !node(value.property)) return false;
  return value.computed === true
    ? value.property.type === "StringLiteral" && value.property.value === "exec_command"
    : value.property.type === "Identifier" && value.property.name === "exec_command";
}

function commandReference(value: unknown): boolean {
  if (!node(value)) return false;
  if (value.type === "Identifier") return value.name === "exec_command";
  if (!["MemberExpression", "OptionalMemberExpression"].includes(value.type) || !node(value.property)) return false;
  if (value.computed === true && node(value.object) && value.object.type === "Identifier" &&
      value.object.name === "tools" && value.property.type !== "StringLiteral") return true;
  return value.computed === true
    ? value.property.type === "StringLiteral" && value.property.value === "exec_command"
    : value.property.type === "Identifier" && value.property.name === "exec_command";
}

function toolsAlias(value: AstNode): boolean {
  if (value.type !== "VariableDeclarator" || !node(value.init) || value.init.type !== "Identifier" ||
      value.init.name !== "tools" || !node(value.id)) return false;
  if (value.id.type === "Identifier") return true;
  if (value.id.type !== "ObjectPattern" || !Array.isArray(value.id.properties)) return false;
  return value.id.properties.some(p => node(p) && (p.type === "RestElement" ||
    p.computed === true || (node(p.key) && ((p.key.type === "Identifier" && p.key.name === "exec_command") ||
      (p.key.type === "StringLiteral" && p.key.value === "exec_command")))));
}

function literal(value: unknown): string | undefined {
  if (!node(value)) return undefined;
  if (value.type === "StringLiteral" && typeof value.value === "string") return value.value;
  if (value.type === "TemplateLiteral" && Array.isArray(value.expressions) && !value.expressions.length &&
      Array.isArray(value.quasis) && value.quasis.length === 1 && node(value.quasis[0])) {
    const cooked = (value.quasis[0].value as { cooked?: unknown } | undefined)?.cooked;
    if (typeof cooked === "string") return cooked;
  }
  return undefined;
}

function commandArgument(args: unknown): string | undefined {
  if (!Array.isArray(args) || args.length !== 1 || !node(args[0]) || args[0].type !== "ObjectExpression" ||
      !Array.isArray(args[0].properties)) return undefined;
  const properties = args[0].properties;
  if (properties.some(p => !node(p) || p.type !== "ObjectProperty" || p.computed === true || p.method === true))
    return undefined;
  const commands = properties.filter(p => node(p) && node(p.key) &&
    (p.key.type === "Identifier" ? p.key.name === "cmd" : p.key.type === "StringLiteral" && p.key.value === "cmd"));
  if (commands.length !== 1 || !node(commands[0])) return undefined;
  return literal(commands[0].value);
}

export function extractFromAst(ast: unknown): JsExtraction {
  const result: JsExtraction = { commands: [], unsupported: 0, malformed: false };
  const stack: unknown[] = [ast];
  let visited = 0;
  while (stack.length) {
    if (++visited > 200_000) return { commands: [], unsupported: 1, malformed: true };
    const current = stack.pop();
    if (!node(current)) continue;
    if (current.type === "CallExpression" && shellMember(current.callee)) {
      const command = commandArgument(current.arguments);
      command === undefined ? result.unsupported++ : result.commands.push(command);
      // callee 已计数，避免作为独立 alias 再次计数；参数中仍可能有嵌套调用。
      const args = Array.isArray(current.arguments) ? current.arguments : [];
      for (let i = args.length - 1; i >= 0; i--) stack.push(args[i]);
      continue;
    }
    if ((current.type === "CallExpression" || current.type === "OptionalCallExpression") &&
        commandReference(current.callee)) {
      result.unsupported++;
      const args = Array.isArray(current.arguments) ? current.arguments : [];
      for (let i = args.length - 1; i >= 0; i--) stack.push(args[i]);
      continue;
    }
    if (commandReference(current) && current.type !== "Identifier") result.unsupported++;
    if (toolsAlias(current)) result.unsupported++; // 只记不支持的引用点，不推断别名或解构的运行期绑定。
    for (const [key, value] of Object.entries(current)) {
      if (["loc", "extra", "comments", "leadingComments", "trailingComments", "innerComments"].includes(key)) continue;
      if (Array.isArray(value)) {
        for (let i = value.length - 1; i >= 0; i--) if (node(value[i])) stack.push(value[i]);
      } else if (node(value)) stack.push(value);
    }
  }
  return result;
}

export function extractJavaScript(source: unknown, parse: Parse): JsExtraction {
  if (typeof source !== "string" || source.length > 2_000_000) return { commands: [], unsupported: 1, malformed: true };
  try {
    const ast = parse(source, { sourceType: "module", allowReturnOutsideFunction: true,
      attachComment: false, errorRecovery: false });
    return extractFromAst(ast);
  } catch {
    // Babel 的异常可能带原文，绝不打印异常或源码片段。
    return { commands: [], unsupported: 1, malformed: true };
  }
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.length !== 2 || argv[0] !== "--parser-module" || !isAbsolute(argv[1])) throw new Error("invalid parser module");
  // 显式提供的本机解析库是受信工具依赖；日志文本绝不用于 import/eval/Function。
  const module = await import(pathToFileURL(argv[1]).href);
  const parse = module.parse ?? module.default?.parse;
  if (typeof parse !== "function") throw new Error("parser API unavailable");
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity, terminal: false });
  for await (const line of input) {
    let result: JsExtraction;
    try {
      const value = JSON.parse(line);
      if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).join(",") !== "script")
        throw new Error("invalid request");
      result = extractJavaScript(value.script, parse);
    } catch { result = { commands: [], unsupported: 1, malformed: true }; }
    // stdout 只接到 Python 私有管道，由调用方脱敏；不得将此组件直接用于真实日志终端输出。
    process.stdout.write(`${JSON.stringify(result)}\n`);
  }
}

if (import.meta.main) {
  try { await main(); }
  catch { console.error("JavaScript history extraction unavailable"); process.exitCode = 2; }
}
