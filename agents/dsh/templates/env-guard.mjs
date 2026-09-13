// 在 DSH 加载前隔离其隐式 dotenv 发现，保持真实业务 cwd。
// 仅屏蔽两个明确的 .env 读取位置；不读取或复制文件内容，不修改文件。
import fs from 'node:fs';
import path from 'node:path';
import { syncBuiltinESMExports } from 'node:module';
import { fileURLToPath } from 'node:url';

const blocked = new Set([
  path.resolve(process.cwd(), '.env'),
  path.resolve(process.env.DSH_HOME, '.env'),
]);
function denied(value) {
  if (value instanceof URL) value = fileURLToPath(value);
  if (Buffer.isBuffer(value)) value = value.toString();
  return typeof value === 'string' && blocked.has(path.resolve(value));
}
function missing() {
  const error = new Error('dotenv discovery is disabled in this managed instance');
  error.code = 'ENOENT';
  return error;
}
const readSync = fs.readFileSync;
fs.readFileSync = function (value, ...args) {
  if (denied(value)) throw missing();
  return readSync.call(this, value, ...args);
};
const read = fs.readFile;
fs.readFile = function (value, ...args) {
  if (denied(value)) {
    const callback = args.at(-1);
    if (typeof callback !== 'function') throw missing();
    queueMicrotask(() => callback(missing()));
    return;
  }
  return read.call(this, value, ...args);
};
const readPromise = fs.promises.readFile;
fs.promises.readFile = async function (value, ...args) {
  if (denied(value)) throw missing();
  return readPromise.call(this, value, ...args);
};
syncBuiltinESMExports();
