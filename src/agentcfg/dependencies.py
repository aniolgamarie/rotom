"""显式锁解析与 frozen npm ci；安装目录按完整锁身份区分。"""

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import tomllib

from .deployment import json_bytes
from .process import DependencyError, checked, environment
from .storage import Conflict, Tree, ensure_private, instance_lock


AUDITED_HELPER_SHA256 = "ca5509febf1e6ec1356df121835ebe5ed2f9cace4bdc2ba6d83d41c7e45e0f1b"


def recipe_digest(repository):
  h = hashlib.sha256()
  for relative in ("agents/dsh/dependencies.json", "agents/dsh/plugins.toml"):
    h.update(relative.encode())
    h.update((repository / relative).read_bytes())
  vendor = repository / "locks/dsh/vendor"
  if vendor.is_dir():
    for path in sorted(vendor.glob("*.tgz")):
      h.update(path.name.encode())
      h.update(path.read_bytes())
  return h.hexdigest()


def copy_vendors(repository, destination, package):
  from .paths import relative_path
  for value in json.loads(package)["dependencies"].values():
    if value.startswith("file:"):
      relative = relative_path(value[5:])
      if len(relative.parts) != 2 or relative.parts[0] != "vendor":
        raise DependencyError("本地依赖必须为锁目录中的固定 vendor 归档")
      source = repository / "locks/dsh" / relative
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


def lock_identity(package, resolution, metadata):
  tools = {key: metadata[key] for key in ("node", "npm", "adapter_version")}
  return hashlib.sha256(package + resolution + json_bytes(tools)).hexdigest()


def validate_plugin_versions(repository, tree):
  plugins = tomllib.loads((repository / "agents/dsh/plugins.toml").read_text())["plugins"]
  for plugin in plugins.values():
    if not plugin["enabled"]:
      continue
    suffix = "node_modules/" + plugin["package"]
    versions = {item.get("version") for path, item in tree["packages"].items() if path.endswith(suffix)}
    if versions != {plugin["version"]}:
      raise DependencyError("插件声明与完整锁不一致；同时更新配方、vendor 和依赖输入")


def read_lock(repository):
  root = repository / "locks/dsh"
  try:
    metadata = json.loads((root / "manifest.json").read_bytes())
    package = (root / "package.json").read_bytes()
    resolution = (root / "package-lock.json").read_bytes()
    digest = lock_identity(package, resolution, metadata)
    tree = json.loads(resolution)
    validate_plugin_versions(repository, tree)
    if (metadata["identity"] != digest or metadata["recipe"] != recipe_digest(repository)
        or tree["lockfileVersion"] != 3
        or tree["packages"][""]["dependencies"] != json.loads(package)["dependencies"]):
      raise ValueError()
    for name, item in tree["packages"].items():
      if "superpowers" in name.lower():
        raise ValueError()
      if name and not item.get("link") and not item.get("inBundle"):
        if "integrity" not in item or "version" not in item or "resolved" not in item:
          raise ValueError()
    return Lock(digest, metadata, package, resolution)
  except (OSError, ValueError, KeyError, TypeError):
    from .schema import ConfigError
    raise ConfigError("lock-missing-or-stale: 请执行 lock --agent dsh") from None


def resolve_lock(repository, *, npm="npm"):
  package = (repository / "agents/dsh/dependencies.json").read_bytes()
  with tempfile.TemporaryDirectory(prefix="agentcfg-lock-") as directory:
    root = Path(directory)
    env = environment(home=root / "home")
    (root / "home").mkdir(mode=0o700)
    env.update(npm_config_cache=str(root / "cache"), npm_config_userconfig=str(root / "user.npmrc"),
               npm_config_globalconfig=str(root / "global.npmrc"))
    (root / "package.json").write_bytes(package)
    copy_vendors(repository, root, package)
    node_version = checked(["node", "--version"], cwd=root, env=env)
    npm_version = checked([npm, "--version"], cwd=root, env=env)
    checked([npm, "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=root, env=env)
    resolution = (root / "package-lock.json").read_bytes()
    validate_plugin_versions(repository, json.loads(resolution))
    manifest = {"version": 1, "identity": hashlib.sha256(package + resolution).hexdigest(),
      "recipe": recipe_digest(repository), "node": node_version, "npm": npm_version,
      "adapter_version": "dsh-1", "platforms": {"linux": "not-smoked", "darwin": "not-smoked"},
      "upstream": {"host": "183f08e9c6dde7e36cd2318eaee70b0da08fb35e",
                   "tui": "78081cebde1ee1b47a561ef57c04f128c5623476",
                   "cursor": "793978ee3b72a1c81d8b769b269ac2fa3bc90654",
                   "openspec": "9d4e5974e5c0d9a09b9c6c1e1eb0975e80ec4461"}}
    manifest["identity"] = lock_identity(package, resolution, manifest)
    # 仓库锁是公开产物；先校验所有结果，再单文件原子替换，manifest 最后提交。
    out = repository / "locks/dsh"
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("package.json", package), ("package-lock.json", resolution), ("manifest.json", json_bytes(manifest))):
      temporary = out / ("." + name + ".tmp")
      temporary.write_bytes(data)
      os.replace(temporary, out / name)
    return read_lock(repository)


def runtime_root(workspace, lock):
  return workspace.instance / "runtimes" / lock.identity


def installed(workspace, lock):
  root = runtime_root(workspace, lock)
  try:
    with Tree(root) as tree:
      marker = tree.read(".agentcfg-ready")
      return marker is not None and marker[1] == 0o600 and marker[0].decode().strip() == lock.identity
  except OSError:
    return False


def sync(workspace, lock):
  with Tree(workspace.state_root, create=True) as state, instance_lock(state):
    if installed(workspace, lock):
      return {"installed": True, "changed": False}
    ensure_private(workspace.instance)
    ensure_private(workspace.cache / "npm")
    roots = workspace.instance / "runtimes"
    ensure_private(roots)
    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=roots))
    home = stage / ".install-home"
    home.mkdir(mode=0o700)
    env = environment(workspace.resolved.data["machine"], home=home)
    env.update(npm_config_cache=str(workspace.cache / "npm"), npm_config_userconfig=str(home / "user.npmrc"),
               npm_config_globalconfig=str(home / "global.npmrc"))
    try:
      if checked(["node", "--version"], cwd=stage, env=env) != lock.metadata["node"]:
        raise DependencyError("Node 版本不匹配当前锁")
      if checked(["npm", "--version"], cwd=stage, env=env) != lock.metadata["npm"]:
        raise DependencyError("npm 版本不匹配当前锁")
      (stage / "package.json").write_bytes(lock.package)
      (stage / "package-lock.json").write_bytes(lock.resolution)
      copy_vendors(workspace.repository, stage, lock.package)
      checked(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=stage, env=env)
      if (stage / "package-lock.json").read_bytes() != lock.resolution:
        raise DependencyError("安装过程修改了锁，拒绝激活")
      checked(["npm", "ls", "--omit=dev", "--all", "--json"], cwd=stage, env=env)
      # 唯一审核过的安装步骤：修复已打包 node-pty spawn-helper 的执行位，不编译/联网。
      helper = stage / "node_modules/@deepseek-ai/dsh-subprocess-local/scripts/ensure-spawn-helper.mjs"
      if not helper.is_file() or hashlib.sha256(helper.read_bytes()).hexdigest() != AUDITED_HELPER_SHA256:
        raise DependencyError("原生安装步骤不匹配已审核版本，拒绝执行")
      checked(["node", str(helper)], cwd=stage, env=env)
      for required in ("@deepseek-ai/dsh/lib/bin.js", "@fission-ai/openspec/bin/openspec.js",
                       "@deepseek-harness-tui/dsh-tui/cordis.patch.yml", "dsh-plugin-oauth-subs/lib/index.js"):
        if not (stage / "node_modules" / required).is_file():
          raise DependencyError("安装结果缺少锁定配方所需文件")
      (stage / ".agentcfg-ready").write_text(lock.identity + "\n")
      (stage / ".agentcfg-ready").chmod(0o600)
      final = runtime_root(workspace, lock)
      if final.exists() or final.is_symlink():
        raise Conflict("运行目录已存在但没有有效安装凭证")
      os.rename(stage, final)
    except BaseException:
      # 安装器自己创建的本次 stage；不清理其他运行包或实例内容。
      shutil.rmtree(stage)
      raise
    return {"installed": True, "changed": True}
