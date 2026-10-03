"""生成纯文本的运行锁测试材料；所有哈希均来自同目录实际字节，不运行构建器。"""

import hashlib
import json
from pathlib import Path


def generate(directory):
  directory = Path(directory)
  def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
  def digest(raw):
    return hashlib.sha256(raw).hexdigest()
  def write(path, raw):
    target = directory / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return digest(raw)
  source_prefix = "source/"
  def source(path, raw):
    return write(source_prefix + path, raw)
  def cached(kind, raw):
    checksum = digest(raw)
    key = "sha256/" + checksum
    write("inputs/" + kind + "/" + key, raw)
    return {"cacheKey": key, "sha256": checksum}
  upstream = write("inputs/upstream-identity.json", encode({"fixture": "synthetic-official-identity"}))
  archive = write("inputs/source.txt", b"SYNTHETIC SOURCE ARCHIVE: NEVER EXTRACT OR EXECUTE\n")
  commit = hashlib.sha1(b"synthetic-commit-identity").hexdigest()
  tool = cached("tools", b"SYNTHETIC BUN TOOL: NEVER EXECUTE\n")
  dependency_bytes = b"SYNTHETIC DEPENDENCY BUNDLE: NEVER EXECUTE\n"
  deps = cached("dependencies", dependency_bytes)
  dependency_path = "locks/omp/upstream/bun.lock"
  inputs = {"schemaVersion": 1, "platform": "linux-x64",
    "upstreamSource": {"commit": commit, "archiveSha256": archive},
    "dependencyLock": {"path": dependency_path, "sha256": source(dependency_path, b"synthetic dependency lock\n")},
    "tools": [{"name": "bun", "version": "1.4.0", **tool}],
    "dependencyArtifacts": [{**deps, "size": len(dependency_bytes)}]}
  input_hash = source("agents/omp/patches/permission-control/build-inputs.lock.json", encode(inputs))
  plugin_path = "agents/omp/packages/omp-permission-control/index.ts"
  plugin = [{"path": plugin_path, "target": "packages/omp-permission-control/index.ts",
    "sha256": source(plugin_path, b"// synthetic plugin fixture: never imported\n"), "executable": False}]
  plugin_hash = digest(encode(plugin))
  patch_path = "agents/omp/patches/permission-control/0001-host-bridge.patch"
  patches = [{"path": patch_path, "sha256": source(patch_path, b"synthetic patch: never applied\n")}]
  source("agents/omp/patches/permission-control/series", b"0001-host-bridge.patch\n")
  build_scripts = []
  for name in ("agents/omp/build-permission-control.py", "src/agentcfg/omp_permission_build.py",
      "src/agentcfg/omp_permission_build_inputs.py", "schemas/omp-permission-build-inputs.schema.json"):
    build_scripts.append({"path": name, "sha256": source(name, b"synthetic build input: never imported\n")})
  binary = b"SYNTHETIC PERMISSION STANDALONE: NEVER EXECUTE\n"
  asset = {"cacheKey": "sha256/" + digest(binary), "sha256": digest(binary), "size": len(binary)}
  write("artifacts/" + asset["cacheKey"], binary)
  manager = write("inputs/manager.txt", b"SYNTHETIC CPYTHON MANAGER: NEVER EXECUTE\n")
  receipt = {"schemaVersion": 1, "variant": "permission-control-v1", "platform": "linux-x64",
    "bridgeAbi": "permission-control/v1", "upstreamIdentity": upstream,
    **{key: inputs[key] for key in ("upstreamSource", "dependencyLock", "tools", "dependencyArtifacts")},
    "buildInputsDigest": input_hash, "patches": patches, "buildScripts": build_scripts,
    "pluginDigest": plugin_hash, "asset": asset, "networkPolicy": "linux-seccomp-no-inet",
    "manager": {"implementation": "CPython", "version": "3.11.0", "sha256": manager}}
  receipt_hash = write("build-receipt.json", encode(receipt))
  manifest = {"schemaVersion": 1, "variant": "permission-control-v1", "upstreamIdentity": upstream,
    "bridgeAbi": "permission-control/v1", "patches": patches, "buildReceiptDigest": receipt_hash,
    "pluginDigest": plugin_hash, "assets": {"linux-x64": asset}}
  manifest["identity"] = digest(encode(manifest))
  write("manifest.json", encode(manifest))


if __name__ == "__main__":
  generate(Path(__file__).resolve().parent / "fixtures/omp/permission-control/runtime")
