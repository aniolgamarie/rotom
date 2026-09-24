// 一个 supervisor 持有实例写锁；其唯一 manager 再串行提交异步协议事务。
// 每次提交核对文件身份，完整 fsync 后才向 dispatch 返回，损坏记录不初始化。
import { constants, closeSync, fstatSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, realpathSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import { randomUUID } from "node:crypto";
import { assertOwner, canonical, clone, closed, digest, reject } from "./managed-types.ts";

const writers = new Set();
const sameFile = (a, b) => a.dev === b.dev && a.ino === b.ino;
function privateInfo(info, directory = false) {
  if ((directory ? !info.isDirectory() : !info.isFile() || info.nlink !== 1)
      || info.uid !== process.getuid() || (info.mode & 0o777) !== (directory ? 0o700 : 0o600)) reject("MANAGED_STORE_IDENTITY", 4);
}
export class ManagedStore {
  constructor({ root, owner, authorize }) {
    assertOwner(owner);
    if (!isAbsolute(root) || typeof authorize !== "function") reject();
    mkdirSync(root, { recursive: true, mode: 0o700 });
    if (realpathSync(root) !== root) reject("MANAGED_STORE_IDENTITY", 4);
    privateInfo(lstatSync(root), true);
    this.directory = root;
    this.directoryIdentity = lstatSync(root);
    this.path = join(root, digest(owner) + ".json");
    this.owner = clone(owner);
    this.authorize = authorize;
    this.tail = Promise.resolve();
    this.closed = false;
    if (writers.has(this.path)) reject("MANAGED_STORE_ALREADY_OPEN", 4);
    try {
      const fd = openSync(this.path, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
      try { writeFileSync(fd, canonical({ schema_version: 1, owner: this.owner, state: {} }) + "\n"); fsyncSync(fd); }
      finally { closeSync(fd); }
      this.syncDirectory();
    } catch (error) { if (error.code !== "EEXIST") throw error; }
    this.identity = lstatSync(this.path);
    this.read();
    writers.add(this.path);
  }
  checkDirectory() {
    const info = lstatSync(this.directory);
    privateInfo(info, true);
    if (!sameFile(info, this.directoryIdentity) || realpathSync(this.directory) !== this.directory) reject("MANAGED_STORE_IDENTITY", 4);
  }
  syncDirectory() {
    this.checkDirectory();
    const fd = openSync(this.directory, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    try { if (!sameFile(fstatSync(fd), this.directoryIdentity)) reject("MANAGED_STORE_IDENTITY", 4); fsyncSync(fd); }
    finally { closeSync(fd); }
  }
  read() {
    this.checkDirectory();
    const fd = openSync(this.path, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const info = fstatSync(fd);
      privateInfo(info);
      if (!sameFile(info, this.identity)) reject("MANAGED_STORE_IDENTITY", 4);
      let value;
      try { value = JSON.parse(readFileSync(fd, "utf8")); } catch { reject("MANAGED_STORE_CORRUPT", 4); }
      closed(value, ["schema_version", "owner", "state"]);
      if (value.schema_version !== 1 || canonical(value.owner) !== canonical(this.owner)
          || !value.state || Object.getPrototypeOf(value.state) !== Object.prototype) reject("MANAGED_STORE_CORRUPT", 4);
      return value.state;
    } finally { closeSync(fd); }
  }
  transaction(operation) {
    const pending = this.tail.then(async () => {
      if (this.closed) reject("MANAGED_STORE_CLOSED", 4);
      await this.authorize();
      const state = this.read();
      const result = await operation(state);
      await this.authorize();
      this.read();
      const temporary = join(this.directory, ".transaction-" + randomUUID());
      let renamed = false;
      try {
        const fd = openSync(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
        try { writeFileSync(fd, canonical({ schema_version: 1, owner: this.owner, state }) + "\n"); fsyncSync(fd); }
        finally { closeSync(fd); }
        this.checkDirectory();
        renameSync(temporary, this.path);
        renamed = true;
        this.identity = lstatSync(this.path);
        this.syncDirectory();
        return result;
      } catch (error) {
        // rename 后 fsync 失败是提交未知，停止后续写入，不能自动重试 dispatch。
        if (renamed) this.closed = true;
        throw error;
      } finally { if (!renamed) { try { unlinkSync(temporary); } catch {} } }
    });
    this.tail = pending.catch(() => {});
    return pending;
  }
  async close() { await this.tail; this.closed = true; writers.delete(this.path); }
}
