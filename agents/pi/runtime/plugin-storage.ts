// 原生插件自己的秘密状态仅保存在选中实例，不借系统 Keychain 或全局 HOME。
import { createHash } from "node:crypto";
import { mkdirSync, lstatSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { pluginAgentDir, pluginSettings } from "./plugin-settings.ts";
import { privateFile, writePrivate } from "./launch.ts";
import { reject } from "./managed-types.ts";

export function privatePluginStore(capability, namespace) {
  if (!/^[a-z][a-z0-9-]{0,63}$/.test(namespace)) reject("PLUGIN_STORE_NAME", 2);
  const path = account => {
    pluginSettings(capability, namespace);
    if (typeof account !== "string" || !account || account.length > 1024) reject("PLUGIN_STORE_ACCOUNT", 2);
    const root = join(pluginAgentDir(), namespace);
    mkdirSync(root, { recursive: true, mode: 0o700 });
    const info = lstatSync(root);
    if (!info.isDirectory() || info.isSymbolicLink() || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o700) reject("PLUGIN_STORE_OWNERSHIP", 4);
    return join(root, createHash("sha256").update(account).digest("hex") + ".json");
  };
  return {
    read(account) {
      const target = path(account);
      try {
        const raw = privateFile(target);
        if (Buffer.byteLength(raw) > 1024 * 1024) reject("PLUGIN_STORE_OVERSIZE", 4);
        return raw;
      } catch (error) { if (error.code === "ENOENT") return undefined; throw new Error("PLUGIN_STORE_READ_FAILED"); }
    },
    write(account, value) {
      if (typeof value !== "string" || Buffer.byteLength(value) > 1024 * 1024) reject("PLUGIN_STORE_OVERSIZE", 2);
      writePrivate(path(account), value);
    },
    remove(account) {
      const target = path(account);
      try { privateFile(target); unlinkSync(target); }
      catch (error) { if (error.code !== "ENOENT") throw new Error("PLUGIN_STORE_REMOVE_FAILED"); }
    },
  };
}
