"""显式锁解析与 frozen npm ci；安装目录按完整锁身份区分。"""

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import tomllib
import sys
import re

from .deployment import json_bytes
from .process import DependencyError, checked, environment
from .storage import Conflict, Tree, ensure_private, instance_lock
from . import runtime_packages


AUDITED_HELPER_SHA256 = "ca5509febf1e6ec1356df121835ebe5ed2f9cace4bdc2ba6d83d41c7e45e0f1b"


def recipe_digest(repository):
  h = hashlib.sha256()
  for relative in ("agents/dsh/dependencies.json", "agents/dsh/plugins.toml", "agents/dsh/lock-policy.json"):
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
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/lock.schema.json").read_bytes())
    if not Draft202012Validator(schema).is_valid(metadata):
      raise ValueError()
    policy = lock_policy(repository)
    if (type(metadata.get("version")) is not int or metadata["version"] != 1
        or any(metadata.get(key) != policy[key] for key in ("adapter_version", "node", "npm", "upstream"))
        or not isinstance(metadata.get("platforms"), dict)
        or sys.platform not in policy["supported_platforms"]
        or sys.platform not in metadata["platforms"]):
      raise ValueError()
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
  except (OSError, ValueError, KeyError, TypeError, DependencyError):
    from .schema import ConfigError
    raise ConfigError("lock-missing-or-stale: 请执行 lock --agent dsh") from None


def lock_policy(repository):
  from .dsh import DshAdapter
  policy = json.loads((repository / "agents/dsh/lock-policy.json").read_bytes())
  agent = tomllib.loads((repository / "agents/dsh/agent.toml").read_text())
  plugins = tomllib.loads((repository / "agents/dsh/plugins.toml").read_text())["plugins"]
  packages = json.loads((repository / "agents/dsh/dependencies.json").read_bytes())["dependencies"]
  if (policy["adapter_version"] != DshAdapter.declaration.adapter_version
      or policy["adapter_version"] != agent["adapter_version"]
      or policy["upstream"]["host"] != agent["upstream_commit"]
      or policy["upstream"]["tui"] != agent["tui_commit"]
      or policy["upstream"]["cursor"] != plugins["cursor-auth"]["commit"]
      or policy["supported_platforms"] != ["linux", "darwin"]
      or set(policy) != {"node", "npm", "adapter_version", "upstream", "npm_integrity", "node_distributions", "supported_platforms", "packages"}
      or set(policy["packages"]) != {"@deepseek-ai/dsh", "@deepseek-harness-tui/dsh-tui", "dsh-plugin-oauth-subs", "@fission-ai/openspec"}
      or any(packages.get(name) != version for name, version in policy["packages"].items())
      or set(policy["upstream"]) != {"host", "tui", "cursor", "openspec"}
      or not all(re.fullmatch(r"[a-f0-9]{40}", value) for value in policy["upstream"].values())
      or not re.fullmatch(r"v\d+\.\d+\.\d+", policy["node"])
      or not re.fullmatch(r"\d+\.\d+\.\d+", policy["npm"])):
    raise ValueError("incompatible lock policy")
  return policy


def resolve_lock(repository, *, npm="npm"):
  try:
    policy = lock_policy(repository)
    if sys.platform not in policy["supported_platforms"]:
      raise ValueError()
  except (OSError, ValueError, KeyError, TypeError):
    raise DependencyError("依赖来源策略无效；核实 lock-policy.json 与 adapter/插件声明") from None
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
    if node_version != policy["node"] or npm_version != policy["npm"]:
      raise DependencyError("解析工具链与已核实 lock-policy.json 不一致")
    checked([npm, "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=root, env=env)
    resolution = (root / "package-lock.json").read_bytes()
    validate_plugin_versions(repository, json.loads(resolution))
    manifest = {"version": 1, "identity": hashlib.sha256(package + resolution).hexdigest(),
      "recipe": recipe_digest(repository), "node": node_version, "npm": npm_version,
      "adapter_version": policy["adapter_version"],
      "platforms": {name: "not-smoked" for name in policy["supported_platforms"]},
      "upstream": policy["upstream"], "npm_integrity": policy["npm_integrity"],
      "node_distributions": policy["node_distributions"]}
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
  return runtime_packages.status(runtime_root(workspace, lock), lock.identity) == "installed"


def sync(workspace, lock):
  with Tree(workspace.state_root, create=True) as state, instance_lock(state):
    if state.read("pending.json"):
      raise Conflict("存在待恢复部署；请先 apply/rollback，恢复完成前不能 sync")
    runtime_packages.recover_repair(runtime_root(workspace, lock), lock.identity)
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
      runtime_packages.seal(stage, lock.identity)
      final = runtime_root(workspace, lock)
      runtime_packages.activate(stage, final, lock.identity)
    except BaseException:
      # 安装器自己创建的本次 stage；不清理其他运行包或实例内容。
      if stage.exists():
        shutil.rmtree(stage)
      raise
    return {"installed": True, "changed": True}
