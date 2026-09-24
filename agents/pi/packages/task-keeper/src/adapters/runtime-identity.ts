import { readFileSync, readdirSync, lstatSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

/** The CLI is only an import stub; the executable chunks are part of the certificate. */
export function runtimeBundleDigest(directory: string): string {
  const files: string[] = [];
  const visit = (relative: string) => {
    for (const name of readdirSync(join(directory, relative)).sort()) {
      const path = relative ? `${relative}/${name}` : name, stat = lstatSync(join(directory, path));
      if (stat.isSymbolicLink()) throw new Error("Runtime bundle symlinks are not certified");
      if (stat.isDirectory()) visit(path);
      else if (stat.isFile()) files.push(path);
      else throw new Error("Runtime bundle entry is not a regular file");
    }
  };
  visit("");
  const hash = createHash("sha256");
  for (const file of files.sort()) hash.update(file).update("\0").update(readFileSync(join(directory, file))).update("\0");
  return hash.digest("hex");
}

/** agentcfg 身份由 launcher 的已验证收据和监督握手共同提供，不扫描 argv/global install。 */
export function runtimeIdentity(_argv = process.argv) {
  const context = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  const installed = context?.installed, owner = context?.owner;
  const platform = process.platform + "-" + (process.arch === "x64" ? "x86_64" : process.arch);
  const validDigest = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
  const supported = !!installed && !!owner && ["manager", "worker"].includes(owner.role)
    && validDigest(installed.runtime_identity) && validDigest(installed.slice_identity)
    && owner.runtime_identity === installed.runtime_identity && owner.slice_identity === installed.slice_identity
    && installed.engine === "node" && installed.sdk_package === "@earendil-works/pi-coding-agent" && installed.sdk_version === "0.84.4"
    && installed.toolchains?.node === "v24.14.0" && process.version === installed.toolchains.node && installed.platform === platform;
  return { supported, version: installed?.sdk_version ?? null, node: process.versions.node, platform: process.platform,
    cliSha256: null, bundleSha256: installed?.runtime_identity ?? null,
    runtimeIdentity: installed?.runtime_identity ?? null, sliceIdentity: installed?.slice_identity ?? null };
}
