"""显式双锁解析与固定 pnpm frozen 安装；运行目录按完整锁身份区分。"""

from dataclasses import dataclass, field
import base64
import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import tomllib
import sys
import re
import tarfile

import yaml

from .deployment import json_bytes
from .process import DependencyError, checked, environment
from .storage import Conflict, Tree, ensure_private, instance_lock
from .toolchain import ensure_compatible_toolchain, ensure_exact_toolchain
from . import runtime_packages


AUDITED_HELPER_SHA256 = "ca5509febf1e6ec1356df121835ebe5ed2f9cace4bdc2ba6d83d41c7e45e0f1b"
LOCK_POLICY_KEYS = frozenset({"node", "npm", "pnpm", "adapter_version", "upstream", "npm_integrity", "pnpm_integrity", "supported_platforms", "packages"})


def recipe_digest(repository, adapter_id="dsh"):
  h = hashlib.sha256()
  agent_root = f"agents/{adapter_id}"
  for relative in (f"{agent_root}/dependencies.json", f"{agent_root}/plugins.toml", f"{agent_root}/lock-policy.json"):
    h.update(relative.encode())
    h.update((repository / relative).read_bytes())
  package = (repository / f"{agent_root}/dependencies.json").read_bytes()
  policy = json.loads((repository / f"{agent_root}/lock-policy.json").read_bytes())
  declared = {value[5:] for value in json.loads(package)["dependencies"].values() if value.startswith("file:")}
  declared.add(f"vendor/pnpm-{policy['pnpm']}.tgz")
  for relative in sorted(declared):
    from .paths import relative_path
    path = repository / f"locks/{adapter_id}" / relative_path(relative)
    if path.is_symlink() or not path.is_file():
      raise DependencyError("锁配方缺少声明的原始归档")
    h.update(relative.encode())
    h.update(path.read_bytes())
    if relative == "vendor/rotom-dsh-cursor-terminal-0.1.0.tgz":
      try:
        with tarfile.open(path, "r:gz") as archive:
          for name in ("package.json", "index.mjs"):
            member = archive.getmember("package/" + name)
            if not member.isfile():
              raise ValueError("invalid local package member")
            body = archive.extractfile(member)
            if body is None or body.read() != (repository / f"{agent_root}/packages/cursor-terminal" / name).read_bytes():
              raise ValueError("local source was not packed")
      except (OSError, ValueError, KeyError, tarfile.TarError):
        raise DependencyError("本地 Cursor 终端源码与固定 vendor 归档不一致；先重新打包再生成锁") from None
  for relative in (f"{agent_root}/packages/cursor-terminal/package.json", f"{agent_root}/packages/cursor-terminal/index.mjs",
      f"{agent_root}/templates/check-runtime.mjs"):
    h.update(relative.encode())
    h.update((repository / relative).read_bytes())
  return h.hexdigest()


def copy_vendors(repository, destination, package, adapter_id="dsh"):
  from .paths import relative_path
  for value in json.loads(package)["dependencies"].values():
    if value.startswith("file:"):
      relative = relative_path(value[5:])
      if len(relative.parts) != 2 or relative.parts[0] != "vendor":
        raise DependencyError("本地依赖必须为锁目录中的固定 vendor 归档")
      source = repository / f"locks/{adapter_id}" / relative
      if source.is_symlink() or not source.is_file():
        raise DependencyError("缺少受核验的 vendor 归档")
      target = destination / relative
      target.parent.mkdir(mode=0o700, exist_ok=True)
      shutil.copyfile(source, target)


@dataclass
class Lock:
  identity: str
  metadata: dict = field(repr=False)
  package: bytes = field(repr=False)
  resolution: bytes = field(repr=False)
  installer_resolution: bytes = field(default=b"", repr=False)


def lock_identity(package, resolution, metadata, installer_resolution=b""):
  tools = {key: metadata[key] for key in ("node", "npm", "pnpm", "pnpm_integrity", "adapter_version")}
  return hashlib.sha256(package + resolution + installer_resolution + json_bytes(tools)).hexdigest()


def validate_installer_resolution(package, resolution):
  document = yaml.safe_load(resolution)
  dependencies = json.loads(package)["dependencies"]
  if (not isinstance(document, dict) or document.get("lockfileVersion") != "9.0"
      or set(document.get("importers", {})) != {"."}
      or set(document["importers"]["."].get("dependencies", {})) != set(dependencies)
      or not isinstance(document.get("packages"), dict) or not document["packages"]
      or not isinstance(document.get("snapshots"), dict) or not document["snapshots"]):
    raise ValueError("invalid frozen installer lock")
  for name, version in dependencies.items():
    item = document["importers"]["."]["dependencies"][name]
    if item.get("specifier") != version or not isinstance(item.get("version"), str) or not item["version"]:
      raise ValueError("inconsistent frozen dependency")
  if any("openspec" in name.lower() or "superpowers" in name.lower() for name in document["packages"]):
    raise ValueError("retired dependency in installer lock")
  local = {value[5:] for value in dependencies.values() if value.startswith("file:")}
  for name, package in document["packages"].items():
    if not isinstance(package, dict) or "workspace:" in name or "link:" in name:
      raise ValueError("unknown installer source")
    resolution = package.get("resolution", {})
    if (not isinstance(resolution, dict) or set(resolution) - {"integrity", "tarball"}
        or not isinstance(resolution.get("integrity"), str)
        or re.fullmatch(r"sha(?:512|1)-[A-Za-z0-9+/]+=*", resolution["integrity"]) is None):
      raise ValueError("installer archive has no fixed integrity")
    tarball = resolution.get("tarball")
    if tarball is not None and (not isinstance(tarball, str) or not (
        tarball in local or tarball.removeprefix("file:") in local or tarball.startswith("https://"))):
      raise ValueError("installer archive source is not fixed")


def prepare_pnpm(repository, destination, policy, adapter_id="dsh"):
  """原包验摘要后解压到本次 stage，不执行安装脚本或创建全局入口。"""
  archive = repository / f"locks/{adapter_id}/vendor/pnpm-{policy['pnpm']}.tgz"
  if archive.is_symlink() or not archive.is_file():
    raise DependencyError("缺少锁定 pnpm 原包")
  content = archive.read_bytes()
  actual = "sha512-" + base64.b64encode(hashlib.sha512(content).digest()).decode()
  if actual != policy["pnpm_integrity"]:
    raise DependencyError("锁定 pnpm 原包完整性不符")
  root = destination / ".tooling/pnpm"
  root.mkdir(mode=0o700, parents=True)
  try:
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as bundle:
      for member in bundle.getmembers():
        relative = Path(member.name)
        if (relative.is_absolute() or ".." in relative.parts or not relative.parts
            or relative.parts[0] != "package" or not (member.isfile() or member.isdir())):
          raise ValueError("unsafe installer archive")
      bundle.extractall(root, filter="data")
    entry = root / "package/bin/pnpm.cjs"
    metadata = json.loads((root / "package/package.json").read_bytes())
    if metadata.get("name") != "pnpm" or metadata.get("version") != policy["pnpm"] or not entry.is_file():
      raise ValueError("incorrect installer entry")
  except (OSError, ValueError, tarfile.TarError):
    raise DependencyError("锁定 pnpm 原包结构不安全或入口不完整") from None
  return ["node", str(entry)]


def check_pnpm_version(argv, expected, *, cwd, env):
  # pnpm 固定原包另行核验，不扩展其他后端的 Node/npm 工具链契约。
  if checked([*argv, "--version"], cwd=cwd, env=env) != expected:
    raise DependencyError("锁定 pnpm 版本不匹配；实际输出已隐藏，拒绝安装")


def validate_plugin_versions(repository, tree, adapter_id="dsh"):
  plugins = tomllib.loads((repository / f"agents/{adapter_id}/plugins.toml").read_text())["plugins"]
  for plugin in plugins.values():
    if not plugin["enabled"]:
      continue
    suffix = "node_modules/" + plugin["package"]
    versions = {item.get("version") for path, item in tree["packages"].items() if path.endswith(suffix)}
    if versions != {plugin["version"]}:
      raise DependencyError("插件声明与完整锁不一致；同时更新配方、vendor 和依赖输入")


def read_lock(repository, adapter_id="dsh", expected_adapter_version=None):
  root = repository / f"locks/{adapter_id}"
  try:
    metadata = json.loads((root / "manifest.json").read_bytes())
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/lock.schema.json").read_bytes())
    if not Draft202012Validator(schema).is_valid(metadata):
      raise ValueError()
    policy = lock_policy(repository, adapter_id, expected_adapter_version)
    if (type(metadata.get("version")) is not int or metadata["version"] != 1
        or any(metadata.get(key) != policy[key] for key in ("adapter_version", "node", "npm", "pnpm", "pnpm_integrity", "npm_integrity", "upstream"))
        or not isinstance(metadata.get("platforms"), dict)
        or sys.platform not in policy["supported_platforms"]
        or sys.platform not in metadata["platforms"]):
      raise ValueError()
    package = (root / "package.json").read_bytes()
    resolution = (root / "package-lock.json").read_bytes()
    installer_resolution = (root / "pnpm-lock.yaml").read_bytes()
    validate_installer_resolution(package, installer_resolution)
    digest = lock_identity(package, resolution, metadata, installer_resolution)
    tree = json.loads(resolution)
    validate_plugin_versions(repository, tree, adapter_id)
    if (metadata["identity"] != digest or metadata["recipe"] != recipe_digest(repository, adapter_id)
        or json.loads(package) != json.loads((repository / f"agents/{adapter_id}/dependencies.json").read_bytes())
        or tree["lockfileVersion"] != 3
        or tree["packages"][""]["dependencies"] != json.loads(package)["dependencies"]):
      raise ValueError()
    for name, item in tree["packages"].items():
      if "superpowers" in name.lower() or "openspec" in name.lower():
        raise ValueError()
      if name and not item.get("link") and not item.get("inBundle"):
        if "integrity" not in item or "version" not in item or "resolved" not in item:
          raise ValueError()
    return Lock(digest, metadata, package, resolution, installer_resolution)
  except (OSError, ValueError, KeyError, TypeError, DependencyError, yaml.YAMLError):
    from .schema import ConfigError
    raise ConfigError(f"lock-missing-or-stale: 请执行 lock --agent {adapter_id}") from None


def lock_policy(repository, adapter_id="dsh", expected_adapter_version=None):
  agent_root = repository / f"agents/{adapter_id}"
  policy = json.loads((agent_root / "lock-policy.json").read_bytes())
  agent = tomllib.loads((agent_root / "agent.toml").read_text())
  plugins = tomllib.loads((agent_root / "plugins.toml").read_text())["plugins"]
  packages = json.loads((agent_root / "dependencies.json").read_bytes())["dependencies"]
  if ((expected_adapter_version is not None and policy["adapter_version"] != expected_adapter_version)
      or policy["adapter_version"] != agent["adapter_version"]
      or policy["upstream"]["host"] != agent["upstream_commit"]
      or policy["upstream"]["tui"] != agent["tui_commit"]
      or policy["upstream"]["cursor"] != plugins["cursor-auth"]["commit"]
      or policy["supported_platforms"] != ["linux", "darwin"]
      or set(policy) != LOCK_POLICY_KEYS
      or not policy["packages"]
      or policy["packages"] != packages
      or any("openspec" in name.lower() for name in packages)
      or set(policy["upstream"]) != {"host", "tui", "cursor"}
      or not all(re.fullmatch(r"[a-f0-9]{40}", value) for value in policy["upstream"].values())
      or not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", policy["node"])
      or any(not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", policy[key]) for key in ("npm", "pnpm"))
      or any(not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", policy[key]) for key in ("npm_integrity", "pnpm_integrity"))):
    raise ValueError("incompatible lock policy")
  return policy


def resolve_lock(repository, *, npm="npm", adapter_id="dsh", expected_adapter_version=None):
  try:
    policy = lock_policy(repository, adapter_id, expected_adapter_version)
  except (OSError, ValueError, KeyError, TypeError):
    raise DependencyError("依赖来源策略无效；核实 lock-policy.json 与 adapter/插件声明") from None
  if sys.platform not in policy["supported_platforms"]:
    raise DependencyError(
      f"当前平台 {sys.platform} 不在支持列表 {policy['supported_platforms']} 内"
    )
  package = (repository / f"agents/{adapter_id}/dependencies.json").read_bytes()
  with tempfile.TemporaryDirectory(prefix="agentcfg-lock-") as directory:
    root = Path(directory)
    env = environment(home=root / "home")
    (root / "home").mkdir(mode=0o700)
    env.update(npm_config_cache=str(root / "cache"), npm_config_userconfig=str(root / "user.npmrc"),
               npm_config_globalconfig=str(root / "global.npmrc"))
    (root / "package.json").write_bytes(package)
    copy_vendors(repository, root, package, adapter_id)
    node_version = checked(["node", "--version"], cwd=root, env=env)
    npm_version = checked([npm, "--version"], cwd=root, env=env)
    ensure_exact_toolchain("Node", policy["node"], node_version)
    ensure_exact_toolchain("npm", policy["npm"], npm_version)
    checked([npm, "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=root, env=env)
    resolution = (root / "package-lock.json").read_bytes()
    validate_plugin_versions(repository, json.loads(resolution), adapter_id)
    pnpm = prepare_pnpm(repository, root, policy, adapter_id)
    check_pnpm_version(pnpm, policy["pnpm"], cwd=root, env=env)
    checked([*pnpm, "install", "--lockfile-only", "--ignore-scripts", "--node-linker=hoisted", "--package-import-method=copy",
      "--store-dir", str(root / "store")], cwd=root, env=env)
    installer_resolution = (root / "pnpm-lock.yaml").read_bytes()
    validate_installer_resolution(package, installer_resolution)
    manifest = {"version": 1, "identity": hashlib.sha256(package + resolution).hexdigest(),
      "recipe": recipe_digest(repository, adapter_id), "node": node_version, "npm": npm_version,
      "pnpm": policy["pnpm"], "pnpm_integrity": policy["pnpm_integrity"],
      "adapter_version": policy["adapter_version"],
      "platforms": {name: "not-smoked" for name in policy["supported_platforms"]},
      "upstream": policy["upstream"], "npm_integrity": policy["npm_integrity"]}
    manifest["identity"] = lock_identity(package, resolution, manifest, installer_resolution)
    # 仓库锁是公开产物；先校验所有结果，再单文件原子替换，manifest 最后提交。
    out = repository / f"locks/{adapter_id}"
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("package.json", package), ("package-lock.json", resolution),
        ("pnpm-lock.yaml", installer_resolution), ("manifest.json", json_bytes(manifest))):
      temporary = out / ("." + name + ".tmp")
      temporary.write_bytes(data)
      os.replace(temporary, out / name)
    return read_lock(repository, adapter_id, expected_adapter_version)


def runtime_root(workspace, lock):
  return workspace.instance / "runtimes" / lock.identity


def installed(workspace, lock):
  return runtime_packages.status(runtime_root(workspace, lock), lock.identity) == "installed"


def sync(workspace, lock, adapter_id="dsh", *, progress=None):
  announce = progress or (lambda stage: None)
  announce("检查运行包")
  with Tree(workspace.state_root, create=True) as state, instance_lock(state):
    if state.read("pending.json"):
      raise Conflict("存在待恢复部署；请先 apply/rollback，恢复完成前不能 sync")
    runtime_packages.recover_repair(runtime_root(workspace, lock), lock.identity)
    if installed(workspace, lock):
      return {"installed": True, "changed": False}
    announce("准备安装")
    ensure_private(workspace.instance)
    ensure_private(workspace.cache / "npm")
    ensure_private(workspace.cache / "pnpm")
    roots = workspace.instance / "runtimes"
    ensure_private(roots)
    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=roots))
    home = stage / ".install-home"
    home.mkdir(mode=0o700)
    env = environment(workspace.resolved.data["machine"], home=home)
    env.update(npm_config_cache=str(workspace.cache / "npm"), npm_config_userconfig=str(home / "user.npmrc"),
               npm_config_globalconfig=str(home / "global.npmrc"))
    try:
      announce("检查 Node/npm 工具链")
      ensure_compatible_toolchain("Node", lock.metadata["node"],
                                  checked(["node", "--version"], cwd=stage, env=env))
      ensure_compatible_toolchain("npm", lock.metadata["npm"],
                                  checked(["npm", "--version"], cwd=stage, env=env))
      (stage / "package.json").write_bytes(lock.package)
      (stage / "package-lock.json").write_bytes(lock.resolution)
      (stage / "pnpm-lock.yaml").write_bytes(lock.installer_resolution)
      copy_vendors(workspace.repository, stage, lock.package, adapter_id)
      pnpm = prepare_pnpm(workspace.repository, stage, lock.metadata, adapter_id)
      check_pnpm_version(pnpm, lock.metadata["pnpm"], cwd=stage, env=env)
      announce("安装锁定依赖")
      checked([*pnpm, "install", "--frozen-lockfile", "--ignore-scripts", "--node-linker=hoisted", "--package-import-method=copy",
        "--store-dir", str(workspace.cache / "pnpm")], cwd=stage, env=env)
      if ((stage / "package-lock.json").read_bytes() != lock.resolution
          or (stage / "pnpm-lock.yaml").read_bytes() != lock.installer_resolution):
        raise DependencyError("安装过程修改了锁，拒绝激活")
      announce("校验安装结果")
      validation = workspace.repository / f"agents/{adapter_id}/templates/check-runtime.mjs"
      checked(["node", str(validation), str(stage)], cwd=stage, env=env)
      # 唯一审核过的安装步骤：修复已打包 node-pty spawn-helper 的执行位，不编译/联网。
      helper = stage / "node_modules/@deepseek-ai/dsh-subprocess-local/scripts/ensure-spawn-helper.mjs"
      if not helper.is_file() or hashlib.sha256(helper.read_bytes()).hexdigest() != AUDITED_HELPER_SHA256:
        raise DependencyError("原生安装步骤不匹配已审核版本，拒绝执行")
      checked(["node", str(helper)], cwd=stage, env=env)
      for required in runtime_packages.REQUIRED_FILES:
        if not (stage / required).is_file():
          raise DependencyError("安装结果缺少锁定配方所需文件")
      runtime_packages.seal(stage, lock.identity)
      announce("激活运行包")
      final = runtime_root(workspace, lock)
      runtime_packages.activate(stage, final, lock.identity)
    except BaseException:
      # 安装器自己创建的本次 stage；不清理其他运行包或实例内容。
      if stage.exists():
        shutil.rmtree(stage)
      raise
    return {"installed": True, "changed": True}
