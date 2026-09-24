import { constants, closeSync, fstatSync, openSync, readFileSync } from "node:fs";
import { readseekGitQuery } from "./readseek-git.ts";
import { resolve } from "node:path";
try {
  const fd = openSync(process.env.AGENTCFG_READSEEK_SELECTION, constants.O_RDONLY | constants.O_NOFOLLOW);
  let body;
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.nlink !== 1 || info.size > 8 * 1024 * 1024) throw new Error();
    body = readFileSync(fd);
    if (body.length > 8 * 1024 * 1024) throw new Error();
  } finally { closeSync(fd); }
  const selection = JSON.parse(new TextDecoder("utf8", { fatal: true }).decode(body));
  const argv = process.argv.slice(2);
  if (argv[0] === "-C" && typeof argv[1] === "string") argv[1] = resolve(process.cwd(), argv[1]);
  process.stdout.write(readseekGitQuery(selection, argv));
} catch {
  process.stderr.write("READSEEK_GIT_QUERY_INVALID\n");
  process.exitCode = 2;
}
