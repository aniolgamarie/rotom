// 自有inode与只读FD隔离文件名替换；不是kernel seal，也不抵抗同进程/同uid恶意写入。
// contents由调用方先校验为非秘密生成JSON；此原语只核字符串/大小和字节身份。
import { constants, closeSync, fstatSync, lstatSync, openSync, readSync, realpathSync, statSync, unlinkSync, writeSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { isAbsolute, join, resolve } from "node:path";

const fail = (code = "pi-model-config-source-invalid", exitCode = 4) => { const error = new Error(code); error.exitCode = exitCode; throw error; };
const same = (actual, original) => actual.dev === original.dev && actual.ino === original.ino;
const privateFile = (actual, original, links) => actual.isFile() && same(actual, original) && actual.uid === original.uid
  && (actual.mode & 0o777) === 0o600 && actual.nlink === links;

export function createModelConfigSource({ directory, contents }) {
  if (process.platform !== "linux") fail("pi-model-config-source-unavailable", 5);
  try { if (!statSync("/proc/self/fd").isDirectory()) fail(); }
  catch { fail("pi-model-config-source-unavailable", 5); }
  if (typeof contents !== "string" || !contents.length || Buffer.byteLength(contents, "utf8") > 1024 * 1024) fail();
  let directoryIdentity;
  try {
    if (typeof directory !== "string" || !isAbsolute(directory) || resolve(directory) !== directory || realpathSync(directory) !== directory) fail();
    directoryIdentity = lstatSync(directory);
    if (!directoryIdentity.isDirectory() || directoryIdentity.isSymbolicLink() || directoryIdentity.uid !== process.getuid()
        || (directoryIdentity.mode & 0o777) !== 0o700) fail();
  } catch { fail(); }
  const initial = Buffer.from(contents, "utf8"), filename = join(directory, ".agentcfg-model-config-" + randomUUID());
  let writer, reader, writerIdentity, readerIdentity, closed = false;
  const sameDirectory = () => {
    const actual = lstatSync(directory);
    return actual.isDirectory() && !actual.isSymbolicLink() && same(actual, directoryIdentity)
      && actual.uid === directoryIdentity.uid && (actual.mode & 0o777) === 0o700 && realpathSync(directory) === directory;
  };
  const closeOwned = (fd, identity) => {
    if (fd === undefined || !identity) return;
    try { if (same(fstatSync(fd), identity)) closeSync(fd); } catch { /* 不关闭被复用的外来fd。 */ }
  };
  const removeOwned = () => {
    if (!writerIdentity) return;
    try {
      if (!sameDirectory()) return;
      const actual = lstatSync(filename);
      if (actual.isFile() && !actual.isSymbolicLink() && same(actual, writerIdentity) && actual.uid === writerIdentity.uid) unlinkSync(filename);
    } catch { /* 不删除替换文件或接管失联目录。 */ }
  };
  try {
    if (!sameDirectory()) fail();
    writer = openSync(filename, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    writerIdentity = fstatSync(writer);
    if (!writerIdentity.isFile() || writerIdentity.uid !== process.getuid() || (writerIdentity.mode & 0o777) !== 0o600 || writerIdentity.nlink !== 1) fail();
    let offset = 0;
    while (offset < initial.length) {
      const count = writeSync(writer, initial, offset, initial.length - offset, offset);
      if (count <= 0) fail(); offset += count;
    }
    if (!sameDirectory()) fail();
    reader = openSync(filename, constants.O_RDONLY | constants.O_NOFOLLOW);
    readerIdentity = fstatSync(reader);
    if (!privateFile(readerIdentity, writerIdentity, 1) || !privateFile(lstatSync(filename), writerIdentity, 1)) fail();
    unlinkSync(filename);
    if (!same(fstatSync(writer), writerIdentity)) fail();
    closeSync(writer); writer = undefined;
    const path = "/proc/self/fd/" + reader;
    const check = () => {
      if (closed) fail("pi-model-config-source-closed");
      try {
        const before = fstatSync(reader);
        if (!privateFile(before, readerIdentity, 0) || before.size !== initial.length) fail();
        const bytes = Buffer.alloc(initial.length + 1);
        let offset = 0;
        while (offset < bytes.length) {
          const count = readSync(reader, bytes, offset, bytes.length - offset, offset);
          if (!count) break; offset += count;
        }
        const after = fstatSync(reader);
        if (!privateFile(after, readerIdentity, 0) || after.size !== initial.length || offset !== initial.length
            || !bytes.subarray(0, offset).equals(initial)) fail();
      } catch { fail(); }
    };
    const close = () => {
      if (closed) return;
      closed = true;
      closeOwned(reader, readerIdentity);
    };
    check();
    try { if (!same(statSync(path), readerIdentity)) fail(); }
    catch { fail("pi-model-config-source-unavailable", 5); }
    return Object.freeze({ path, check, close });
  } catch (error) {
    closeOwned(reader, readerIdentity); closeOwned(writer, writerIdentity); removeOwned();
    fail(error?.exitCode === 5 ? "pi-model-config-source-unavailable" : "pi-model-config-source-invalid", error?.exitCode === 5 ? 5 : 4);
  }
}
