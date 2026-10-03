#!/usr/bin/env python3
"""保留已退休的 OMP 宿主补丁构建实现用于历史取证；CLI 禁止继续发布。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))

from agentcfg.deployment import json_bytes
from agentcfg.omp_permission_build import apply_patch_bytes, deny_network, extract_inputs, stage_permission_core, permission_plugin_digest
from agentcfg.omp_permission_build_inputs import (
  BUILD_SCRIPT_PATHS, BuildInputUnavailable, _ordinary_path, read_build_input_lock, verify_build_inputs, verify_file,
)
from agentcfg.schema import ConfigError


def digest(path):
  with Path(path).open("rb") as stream:
    return hashlib.file_digest(stream, "sha256").hexdigest()


def plugin_digest():
  return permission_plugin_digest(REPOSITORY)


def run_bun(bun, args, work, env, *, timeout=1200):
  # 子进程仅获得本次临时目录，无代理/凭据/用户配置；网络限制继承到子进程。
  try:
    result = subprocess.run([str(bun), *args], cwd=work, env=env, capture_output=True,
      timeout=timeout, check=False, preexec_fn=deny_network)
  except (OSError, subprocess.SubprocessError):
    raise BuildInputUnavailable("omp-build-process-unavailable") from None
  if result.returncode:
    raise BuildInputUnavailable("omp-build-process-failed")
  return result.stdout


def build(args):
  schema = json.loads((REPOSITORY / "schemas/omp-permission-build-inputs.schema.json").read_text())
  inputs = read_build_input_lock(args.build_inputs_lock, schema)
  if args.platform != inputs["platform"] or args.platform != "linux-x64" or sys.platform != "linux" \
      or platform.machine() not in ("x86_64", "amd64") or platform.libc_ver()[0] != "glibc":
    raise BuildInputUnavailable("omp-build-platform-mismatch")
  verify_build_inputs(inputs, source_archive=args.source,
    dependency_lock=REPOSITORY / inputs["dependencyLock"]["path"],
    tool_cache=args.tool_cache, dependency_cache=args.dependency_cache)
  if len(inputs["tools"]) != 1 or inputs["tools"][0]["name"] != "bun":
    raise ConfigError("omp-build-toolchain-not-supported")
  tool = inputs["tools"][0]
  bun = _ordinary_path(args.tool_cache / tool["cacheKey"])
  series_root = REPOSITORY / "agents/omp/patches/permission-control"
  try:
    series = (series_root / "series").read_text().splitlines()
  except OSError:
    raise BuildInputUnavailable("omp-build-series-missing") from None
  if not series or len(set(series)) != len(series) or any(
      not name.endswith(".patch") or Path(name).name != name for name in series):
    raise ConfigError("omp-build-series-invalid")
  patches = []
  for name in series:
    path = _ordinary_path(series_root / name)
    patches.append({"path": path.relative_to(REPOSITORY).as_posix(), "sha256": digest(path)})
  upstream = json.loads((REPOSITORY / "locks/omp/manifest.json").read_text())
  if upstream["commit"] != inputs["upstreamSource"]["commit"] or upstream["source"]["sha256"] != inputs["upstreamSource"]["archiveSha256"]:
    raise BuildInputUnavailable("omp-build-upstream-mismatch")
  plugin = plugin_digest()
  input_digest = digest(args.build_inputs_lock)
  scripts = [{"path": path, "sha256": digest(REPOSITORY / path)} for path in BUILD_SCRIPT_PATHS]
  with tempfile.TemporaryDirectory(prefix="rotom-omp-offline-") as temporary:
    base = Path(temporary)
    work = base / "source"
    work.mkdir()
    folders = {name: base / name for name in ("home", "cache", "tmp", "config", "omp", "bin")}
    for folder in folders.values(): folder.mkdir(mode=0o700)
    env = {"HOME": str(folders["home"]), "XDG_CONFIG_HOME": str(folders["config"]),
      "XDG_CACHE_HOME": str(folders["cache"]), "PI_CODING_AGENT_DIR": str(folders["omp"]),
      "TMPDIR": str(folders["tmp"]), "PATH": str(folders["bin"]), "CI": "1",
      "BUN_INSTALL_CACHE_DIR": str(folders["cache"] / "bun"), "TZ": "UTC"}
    version = run_bun(bun, ["--version"], base, env, timeout=10).decode("ascii").strip()
    if version != tool["version"]:
      raise BuildInputUnavailable("omp-build-tool-version")
    extract_inputs(args.source, work, strip_root="oh-my-pi-" + inputs["upstreamSource"]["commit"])
    verify_file(work / "bun.lock", inputs["dependencyLock"]["sha256"])
    for entry in inputs["dependencyArtifacts"]:
      extract_inputs(args.dependency_cache / entry["cacheKey"], work)
    for patch in patches:
      apply_patch_bytes(work, (REPOSITORY / patch["path"]).read_bytes())
    stage_permission_core(REPOSITORY / "agents/omp/packages/omp-permission-control", work)
    bridge = work / "packages/coding-agent/src/permission-control/bridge.ts"
    if not bridge.is_file() or b"permission-control/v1" not in bridge.read_bytes():
      raise BuildInputUnavailable("omp-build-static-abi-missing")
    output = work / "omp-permission-control"
    entry = work / ".rotom-permission-build.ts"
    entry.write_text('''import { createRequire } from "node:module";
import { embedNativeAddon } from "./packages/natives/scripts/embed-native";
import { compileCodingAgent } from "./packages/coding-agent/scripts/compile-binary";
import { buildArchiveBase64 } from "./packages/stats/scripts/generate-client-bundle";
const require = createRequire(import.meta.url);
const root = import.meta.dir;
const version = require("./packages/natives/package.json").version;
// 上游静态资源生成器只在已验证的临时源码中编译/写文件，不启动宿主。
process.chdir(`${root}/packages/stats`);
try {
  await import("./packages/stats/build");
} finally {
  process.chdir(root);
}
await Bun.write(`${root}/packages/stats/src/embedded-client.generated.txt`,
  await buildArchiveBase64(`${root}/packages/stats/dist/client`));
await import("./packages/collab-web/scripts/build-tool-views");
await embedNativeAddon({targetPlatform: "linux", targetArch: "x64",
  nativeDir: `${root}/packages/natives/native`,
  outputPath: `${root}/packages/natives/native/embedded-addon.js`, version});
await compileCodingAgent({repoRoot: root,
  entrypoint: `${root}/packages/coding-agent/src/cli.ts`,
  outfile: `${root}/omp-permission-control`,
  transformersVersion: require("@huggingface/transformers/package.json").version,
  executablePath: process.execPath, minifyIdentifiers: true});
''')
    run_bun(bun, ["run", str(entry)], work, env)
    _ordinary_path(output)
    if plugin_digest() != plugin or digest(args.build_inputs_lock) != input_digest:
      raise BuildInputUnavailable("omp-build-input-changed")
    for item in [*patches, *scripts]:
      verify_file(REPOSITORY / item["path"], item["sha256"])
    if json.loads((REPOSITORY / "locks/omp/manifest.json").read_text()) != upstream:
      raise BuildInputUnavailable("omp-build-input-changed")
    asset = {"cacheKey": "sha256/" + digest(output), "sha256": digest(output), "size": output.stat().st_size}
    receipt = {"schemaVersion": 1, "variant": "permission-control-v1", "platform": args.platform,
      "bridgeAbi": "permission-control/v1", "upstreamIdentity": upstream["identity"],
      "upstreamSource": inputs["upstreamSource"], "dependencyLock": inputs["dependencyLock"],
      "buildInputsDigest": input_digest, "tools": inputs["tools"],
      "dependencyArtifacts": inputs["dependencyArtifacts"], "patches": patches,
      "buildScripts": scripts,
      "pluginDigest": plugin, "asset": asset, "networkPolicy": "linux-seccomp-no-inet",
      "manager": {"implementation": platform.python_implementation(), "version": platform.python_version(),
        "sha256": digest(Path(sys.executable).resolve())}}
    args.artifact_cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    _ordinary_path(args.artifact_cache, directory=True)
    destination = args.artifact_cache / asset["cacheKey"]
    destination.parent.mkdir(exist_ok=True, mode=0o700)
    _ordinary_path(destination.parent, directory=True)
    if destination.exists() or destination.is_symlink():
      verify_file(destination, asset["sha256"], size=asset["size"])
    else:
      with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".build-", delete=False) as target:
        pending = Path(target.name)
        try:
          with output.open("rb") as source: shutil.copyfileobj(source, target)
          target.flush()
          os.fsync(target.fileno())
          pending.chmod(0o700)
          os.replace(pending, destination)
        finally:
          pending.unlink(missing_ok=True)
    receipt_path = args.artifact_cache / "build-receipt.json"
    if receipt_path.is_symlink(): raise BuildInputUnavailable("omp-build-receipt-path")
    with tempfile.NamedTemporaryFile(dir=args.artifact_cache, prefix=".receipt-", delete=False) as target:
      pending = Path(target.name)
      try:
        target.write(json_bytes(receipt))
        target.flush()
        os.fsync(target.fileno())
        os.replace(pending, receipt_path)
      finally:
        pending.unlink(missing_ok=True)
    return {"assetSha256": asset["sha256"], "assetSize": asset["size"],
      "receiptDigest": digest(receipt_path), "hostExecuted": False}


def main():
  print("omp-host-patching-retired", file=sys.stderr)
  return 2


if __name__ == "__main__":
  raise SystemExit(main())
