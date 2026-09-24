"""Pi独立完整锁：各配方锁文件原样消费，运行身份保存到部署契约。"""

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import base64
import shutil
import tomllib

from jsonschema import Draft202012Validator
from referencing import Registry

from .config import _credential_url
from .deployment import json_bytes
from .paths import relative_path, safe_id
from .process import DependencyError, checked, environment
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private, instance_lock


ROOT = Path(__file__).resolve().parents[2]
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")


def digest(value):
  return hashlib.sha256(value if isinstance(value, bytes) else json_bytes(value)).hexdigest()


def platform_id():
  architecture = {"aarch64": "arm64", "amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
  return sys.platform + "-" + architecture


def recipe_digest(repository):
  result = hashlib.sha256()
  with Tree(repository / "agents/pi", private=False) as tree:
    for name in ("agent.toml", "plugins.toml", "dependencies.json"):
      raw = tree.read(name)
      if raw is None:
        raise ConfigError("pi-recipe-missing")
      result.update(name.encode() + b"\0" + raw[0])
    for name in ("bindings.toml", "content.toml"):
      raw = tree.read(name)
      if raw is not None:
        result.update(name.encode() + b"\0" + raw[0])
  from .pi_vendor import source_files, source_digest
  for name in ("runtime", "templates", "roles", "prompts", "themes", "packages", "build", "schemas", "profiles"):
    directory = repository / "agents/pi" / name
    if directory.exists():
      result.update(name.encode() + b"\0" + source_digest(source_files(repository, "agents/pi/" + name, ("tests",))).encode())
  selected_skills = set()
  with Tree(repository, private=False) as tree:
    inputs = [*sorted((repository / "src/agentcfg").glob("*.py")), *sorted((repository / "scripts").glob("pi-*.py")),
      repository / "scripts/pi-supervisor-macos.c", repository / "scripts/pi-project-check", repository / "pyproject.toml", repository / "uv.lock"]
    for path in inputs:
      name = path.relative_to(repository).as_posix()
      raw = tree.read(name)
      if raw is not None:
        result.update(name.encode() + b"\0" + raw[0])
    for path in sorted((repository / "profiles").glob("pi-*.toml")):
      raw = tree.read(path.relative_to(repository).as_posix())
      result.update(path.name.encode() + b"\0" + raw[0])
      selected_skills.update(tomllib.loads(raw[0].decode()).get("skills", []))
    for path in ("shared/content.toml", "agents/pi/content.toml"):
      raw = tree.read(path)
      if raw is None:
        continue
      for identity, skill in tomllib.loads(raw[0].decode()).get("skills", {}).items():
        if identity in selected_skills and (repository / skill["path"]).exists():
          result.update(identity.encode() + b"\0" + source_digest(source_files(repository, skill["path"], ("tests",))).encode())
  return result.hexdigest()


@dataclass(frozen=True)
class PiLock:
  identity: str
  metadata: dict = field(repr=False)
  pairs: dict = field(repr=False)


class PiBackend:
  adapter_id = "pi"
  adapter_version = "pi-1"

  def read_lock(self, repository):
    result, failed = None, False
    try:
      root = Path(repository) / "locks/pi"
      with Tree(root, private=False) as tree:
        raw = tree.read("manifest.json")
        if raw is None:
          raise ValueError()
        manifest = json.loads(raw[0])
        schema = json.loads((ROOT / "schemas/pi-lock.schema.json").read_text())
        if not Draft202012Validator(schema, registry=Registry()).is_valid(manifest):
          raise ValueError()
        if (digest({k: v for k, v in manifest.items() if k != "identity"}) != manifest["identity"]
            or manifest["recipe_digest"] != recipe_digest(Path(repository))):
          raise ValueError()
        pairs = {}
        for source in manifest["sources"].values():
          from .pi_vendor import validate_license_sources
          validate_license_sources(source)
          if source["kind"] == "npm":
            if not {"package", "version", "resolved", "integrity"} <= source.keys():
              raise ValueError()
            if not VERSION.fullmatch(source["version"]) or not source["resolved"].startswith("https://") or _credential_url(source["resolved"]):
              raise ValueError()
          elif source["kind"] == "asset":
            from .pi_assets import validate_asset
            validate_asset(source)
            if "vendor_path" in source:
              archive = tree.read(source["vendor_path"])
              if archive is None or digest(archive[0]) != source["archive_digest"]:
                raise ValueError()
          else:
            if not {"vendor_path", "archive_digest"} <= source.keys():
              raise ValueError()
            archive = tree.read(source["vendor_path"])
            if archive is None or digest(archive[0]) != source["archive_digest"]:
              raise ValueError()
            if source["kind"] == "git" and not re.fullmatch(r"[0-9a-f]{40}", source.get("commit", "")):
              raise ValueError()
            if source["kind"] == "local" and not {"source_path", "source_tree_digest"} <= source.keys():
              raise ValueError()
        for name, piece in manifest["profile_slices"].items():
          if set(piece["source_ids"]) - manifest["sources"].keys():
            raise ValueError()
          from .pi_assets import validate_asset_platforms
          validate_asset_platforms(piece, manifest)
          if digest({k: v for k, v in piece.items() if k != "identity"}) != piece["identity"]:
            raise ValueError()
          package, lock = tree.read(piece["package_path"]), tree.read(piece["lock_path"])
          if package is None or lock is None or digest(package[0]) != piece["package_json_digest"] or digest(lock[0]) != piece["package_lock_digest"]:
            raise ValueError()
          if digest(piece["resource_manifest"]) != piece["resource_manifest_digest"]:
            raise ValueError()
          self._validate_resolution(json.loads(package[0]), json.loads(lock[0]), piece, manifest)
          for entries in piece["resource_manifest"].values():
            for entry in entries:
              if entry["capability_id"] not in piece["capability_ids"]:
                raise ValueError()
          pairs[name] = (package[0], lock[0])
        for step in manifest["build_steps"]:
          if (set(step["source_ids"]) - manifest["sources"].keys()
              or set(step["expected_outputs"]) != set(step["output_digests"])):
            raise ValueError()
          for path in (*step["input_digests"], *step["output_digests"]):
            relative_path(path)
        result = PiLock(manifest["identity"], manifest, pairs)
    except Exception:
      failed = True
    if failed:
      raise ConfigError("pi-lock-missing-or-stale")
    return result

  def _validate_resolution(self, package, resolution, piece, manifest):
    if (resolution.get("lockfileVersion") != 3 or not isinstance(package.get("dependencies"), dict)
        or resolution.get("packages", {}).get("", {}).get("dependencies") != package["dependencies"]):
      raise ValueError()
    archives = {source["vendor_path"] for source in manifest["sources"].values() if "vendor_path" in source}
    declared = {manifest["sources"][key]["package"] for key in piece["source_ids"] if manifest["sources"][key]["kind"] != "asset"}
    if set(package["dependencies"]) != declared:
      raise ValueError()
    for version in package["dependencies"].values():
      if not isinstance(version, str):
        raise ValueError()
      if version.startswith("file:"):
        path = os.path.normpath(str(Path(piece["package_path"]).parent / version[5:]))
        if path not in archives or Path(version[5:]).is_absolute():
          raise ValueError()
      elif not VERSION.fullmatch(version):
        raise ValueError()
    for name in package["dependencies"]:
      if "node_modules/" + name not in resolution["packages"]:
        raise ValueError()
    for path, value in resolution["packages"].items():
      if not path:
        continue
      relative_path(path)
      if "node_modules" not in Path(path).parts:
        raise ValueError()
      if value.get("link"):
        # 本地源必须为已冻结归档，不允许workspace/link逃逸运行包。
        raise ValueError()
      required = set(value.get("dependencies", {})) - set(value.get("optionalDependencies", {}))
      required |= {name for name in value.get("peerDependencies", {}) if not value.get("peerDependenciesMeta", {}).get(name, {}).get("optional")}
      for name in required:
        # 按 Node 的祖先 node_modules 查找；锁中必须存在每个必需传递依赖。
        base = Path(path)
        candidates = []
        while base.parts:
          candidates.append((base / "node_modules" / name).as_posix())
          base = base.parent
        candidates.append("node_modules/" + name)
        if not any(candidate in resolution["packages"] for candidate in candidates):
          raise ValueError()
      if not value.get("inBundle"):
        if not {"version", "resolved", "integrity"} <= value.keys():
          raise ValueError()
        if not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", value["integrity"]):
          raise ValueError()
        if len(base64.b64decode(value["integrity"][7:], validate=True)) != 64 or not VERSION.fullmatch(value["version"]):
          raise ValueError()
        resolved = value["resolved"]
        if resolved.startswith("file:"):
          target = os.path.normpath(str(Path(piece["package_path"]).parent / resolved[5:]))
          if target not in archives or Path(resolved[5:]).is_absolute():
            raise ValueError()
        elif not resolved.startswith("https://") or _credential_url(resolved):
          raise ValueError()

  def runtime_identity(self, workspace, lock):
    if workspace.profile not in lock.metadata["profile_slices"]:
      raise ConfigError("pi-lock-profile")
    if hasattr(workspace, "resolved"):
      selected = workspace.resolved.data["profile"]["agent_options"].get("runtime", {}).get("engine", "node")
      if selected != lock.metadata["profile_slices"][workspace.profile]["engine"]:
        raise ConfigError("pi-lock-engine")
      if set(workspace.resolved.data["profile"]["plugins"]) - set(lock.metadata["profile_slices"][workspace.profile]["capability_ids"]):
        raise ConfigError("pi-lock-capabilities")
    return digest({"lock_identity": lock.identity, "slice_identity": lock.metadata["profile_slices"][workspace.profile]["identity"],
      "platform": platform_id(), "toolchain_identity": digest(lock.metadata["toolchains"])})

  def root(self, workspace, identity):
    return workspace.instance / "runtimes" / safe_id(identity)

  def status(self, workspace, identity):
    from .pi_runtime_packages import status
    return status(self.root(workspace, identity), identity)

  def openspec_preflight(self, lock):
    return [(["node", "--version"], lock.metadata["toolchains"]["node"])]

  def openspec_argv(self, workspace, lock):
    if "openspec" not in workspace.resolved.data["profile"]["plugins"]:
      raise DependencyError("Pi OpenSpec 能力未选择")
    identity = self.runtime_identity(workspace, lock)
    if self.status(workspace, identity) != "installed":
      raise DependencyError("Pi OpenSpec 锁定运行包尚未就绪")
    root = self.root(workspace, identity)
    prefix = Path(lock.metadata["profile_slices"][workspace.profile]["package_path"]).parent
    package_path = prefix / "node_modules/@fission-ai/openspec"
    with Tree(root) as tree:
      package = tree.read((package_path / "package.json").as_posix())
      entry = tree.read((package_path / "bin/openspec.js").as_posix())
    try:
      valid = package and json.loads(package[0])["version"] == "1.11.0" and entry
    except (ValueError, KeyError, TypeError): valid = False
    if not valid: raise DependencyError("Pi OpenSpec 1.11.0 入口不完整")
    return ["node", str(root / package_path / "bin/openspec.js")]

  def executable_paths(self, root):
    return (root / "bin",)

  def toolchain(self, lock):
    return dict(lock.metadata["toolchains"])

  def resolve_lock(self, repository):
    from .pi_vendor import resolve_lock
    return resolve_lock(Path(repository))

  def sync(self, workspace, lock):
    from .pi_lifecycle import guard
    with guard(workspace):
      return self._sync(workspace, lock)

  def _sync(self, workspace, lock):
    from .pi_runtime_packages import activate, recover_repair, seal
    identity = self.runtime_identity(workspace, lock)
    if platform_id() not in lock.metadata["platforms"]:
      raise DependencyError("Pi所选平台尚未声明支持")
    piece = lock.metadata["profile_slices"][workspace.profile]
    final = self.root(workspace, identity)
    with Tree(workspace.state_root, create=True) as state, instance_lock(state):
      if state.read("pending.json"):
        raise Conflict("存在配置恢复待处理，不能安装依赖")
      ensure_private(final.parent)
      recover_repair(final, identity)
      if self.status(workspace, identity) == "installed":
        return {"installed": False, "identity": identity}
      with tempfile.TemporaryDirectory(prefix=".pi-stage-", dir=final.parent) as directory:
        stage = Path(directory)
        with Tree(stage) as tree, Tree(workspace.repository / "locks/pi", private=False) as sources:
          for path, content in zip((piece["package_path"], piece["lock_path"]), lock.pairs[workspace.profile]):
            tree.write_state(path, content)
          for source_id in piece["source_ids"]:
            source = lock.metadata["sources"][source_id]
            if source["kind"] != "asset" and "vendor_path" in source:
              archive = sources.read(source["vendor_path"])
              if archive is None or digest(archive[0]) != source["archive_digest"]:
                raise DependencyError("Pi归档身份不匹配")
              tree.write_state(source["vendor_path"], archive[0])
        home = stage / "install-home"
        ensure_private(home)
        from .pi_vendor import npm_environment
        env = npm_environment(home)
        tools = ("node", "npm", "bun") if piece["engine"] == "bun" else ("node", "npm")
        for name in tools:
          expected = lock.metadata["toolchains"][name]
          actual = checked([name, "--version"], cwd=stage, env=env)
          if actual != expected:
            raise DependencyError("Pi锁要求精确工具链版本；尚未安装运行包")
        package_root = stage / Path(piece["package_path"]).parent
        checked(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=package_root, env=env)
        for step in lock.metadata["build_steps"]:
          if step["platform"] not in ("all", platform_id()) or not set(step["source_ids"]) <= set(piece["source_ids"]):
            continue
          for path, expected in step["input_digests"].items():
            with Tree(stage) as tree:
              content = tree.read(path)
            if content is None or digest(content[0]) != expected:
              raise DependencyError("Pi构建输入身份不匹配")
          checked(step["argv"], cwd=package_root, env=env)
          with Tree(stage) as tree:
            for path, expected in step["output_digests"].items():
              raw = tree.read(path)
              if raw is None or digest(raw[0]) != expected:
                raise DependencyError("Pi必要构建输出缺失或摘要不匹配")
        from .pi_assets import install_assets
        install_assets(workspace.repository, stage, piece, lock.metadata, platform_id())
        from .pi_vendor import install_launcher
        install_launcher(workspace.repository, stage, piece, lock.metadata)
        from .pi_native_build import install_platform_helpers
        install_platform_helpers(workspace.repository, stage, platform_id())
        shutil.rmtree(home)
        try:
          seal(stage, identity, lock.identity, piece, toolchains=lock.metadata["toolchains"])
        except Conflict:
          raise DependencyError("Pi安装未包含完整必要运行资源，旧运行包保持不变") from None
        activate(stage, final, identity)
      return {"installed": True, "identity": identity}
