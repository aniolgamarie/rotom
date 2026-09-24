// grep 在已按原项目忽略规则选择的文件副本中运行，不能再次用副本忽略规则缩小结果。
import { isAbsolute, relative, resolve, sep } from "node:path";

export function readseekRgArguments(argv, snapshotRoot) {
  const fail = () => { throw new Error("READSEEK_RG_QUERY_INVALID"); };
  const prefix = ["--json", "--line-number", "--color=never", "--hidden"];
  if (!Array.isArray(argv) || prefix.some((value, index) => argv[index] !== value)
      || typeof snapshotRoot !== "string" || !isAbsolute(snapshotRoot)) fail();
  let index = prefix.length;
  if (argv[index] === "--ignore-case") index++;
  if (argv[index] === "--fixed-strings") index++;
  if (argv[index] === "--glob") {
    if (typeof argv[index + 1] !== "string" || argv[index + 1].includes("\0")) fail();
    index += 2;
  }
  if (argv.length !== index + 3 || argv[index] !== "--" || typeof argv[index + 1] !== "string"
      || argv[index + 1].includes("\0") || typeof argv[index + 2] !== "string" || !isAbsolute(argv[index + 2])) fail();
  const path = argv[index + 2], tail = relative(snapshotRoot, resolve(path));
  if (path !== resolve(path) || tail === ".." || tail.startsWith(".." + sep) || isAbsolute(tail)) fail();
  return ["--no-config", "--no-ignore", ...argv];
}
