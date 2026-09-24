// ReadSeek 只需要固定的 ls-files 查询；返回父侧已经筛选并导出的类别，不读取 .git。
import { isAbsolute, relative, resolve, sep } from "node:path";

export function readseekGitQuery(selection, argv) {
  function fail() { throw new Error("READSEEK_GIT_QUERY_INVALID"); }
  if (!selection || selection.schema_version !== 1 || typeof selection.snapshot_root !== "string"
      || !isAbsolute(selection.snapshot_root) || selection.snapshot_root !== resolve(selection.snapshot_root)
      || !/^[a-f0-9]{64}$/.test(selection.snapshot_digest)
      || !selection.categories || typeof selection.categories !== "object"
      || Object.keys(selection.categories).some(key => !["cached", "others", "ignored"].includes(key))) fail();
  if (!Array.isArray(argv) || argv[0] !== "-C" || typeof argv[1] !== "string" || argv[2] !== "ls-files" || argv[3] !== "-z") fail();
  const cwd = resolve(selection.snapshot_root, argv[1]), tail = relative(selection.snapshot_root, cwd);
  if (tail === ".." || tail.startsWith(".." + sep) || isAbsolute(tail)) fail();
  const flags = argv.slice(4).join(" ");
  const category = flags === "--cached" ? "cached" : flags === "--others --exclude-standard" ? "others"
    : flags === "--others --ignored --exclude-standard" ? "ignored" : null;
  if (category === null || !Object.hasOwn(selection.categories, category)) fail();
  const names = selection.categories[category];
  if (!Array.isArray(names) || names.length > 10000 || new Set(names).size !== names.length) fail();
  const result = [];
  for (const path of names) {
    if (typeof path !== "string" || !path || /[\x00-\x1f\x7f\\]/.test(path) || isAbsolute(path)
        || path.split("/").some(part => ["", ".", "..", ".git"].includes(part))) fail();
    const scoped = relative(cwd, resolve(selection.snapshot_root, path));
    if (scoped && scoped !== ".." && !scoped.startsWith(".." + sep) && !isAbsolute(scoped)) result.push(scoped);
  }
  result.sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
  return Buffer.from(result.length ? result.join("\0") + "\0" : "");
}
