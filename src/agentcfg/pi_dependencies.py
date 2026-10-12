"""Pi独立完整锁：各配方锁文件原样消费，运行身份保存到部署契约。"""

from dataclasses import dataclass, field
from types import MappingProxyType
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
from .pi_lock_layout import dependency_layout
from .pi_lock_resolution import VERSION


ROOT = Path(__file__).resolve().parents[2]


def digest(value):
  return hashlib.sha256(value if isinstance(value, bytes) else json_bytes(value)).hexdigest()


def platform_id():
  architecture = {"aarch64": "arm64", "amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
  return sys.platform + "-" + architecture


def recipe_digest(repository, *, family=None):
  layout = dependency_layout(family=family)
  result = hashlib.sha256()
  with Tree(repository / "agents/pi", private=False) as tree:
    for name in ("agent.toml", "plugins.toml", Path(layout.dependencies_path).name):
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
  validated_bindings: dict = field(default_factory=dict, repr=False)

  def __post_init__(self):
    # 拷贝已验证范围，防止调用方修改原字典或追加未验证 slice。
    if not isinstance(self.pairs, (dict, MappingProxyType)) or any(not isinstance(value, tuple) or len(value) != 2 or any(not isinstance(raw, bytes) for raw in value) for value in self.pairs.values()):
      raise ConfigError("pi-lock-pairs")
    object.__setattr__(self, "pairs", MappingProxyType(dict(self.pairs)))
    object.__setattr__(self, "validated_bindings", MappingProxyType(dict(self.validated_bindings)))


class PiBackend:
  adapter_id = "pi"
  adapter_version = "pi-1"

  def __init__(self, *, profile=None, family=None):
    if profile is not None and (not isinstance(profile, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", profile)):
      raise ConfigError("pi-lock-profile")
    self.profile = profile
    self.layout = dependency_layout(profile=profile, family=family)

  def read_lock(self, repository, *, accepted_binding_digests=None):
    result, failed = None, False
    try:
      root = Path(repository) / self.layout.lock_directory
      with Tree(root, private=False) as tree:
        raw = tree.read("manifest.json")
        if raw is None:
          raise ValueError()
        manifest = json.loads(raw[0])
        from .pi_lock_header import validate_lock_header
        validate_lock_header(manifest, schema_version=self.layout.schema_version)
        if manifest["recipe_digest"] != recipe_digest(Path(repository), family=self.layout.family):
          raise ValueError()
        if manifest["schema_version"] == 2:
          from .pi_capabilities import validate_manifest_bindings
          validate_manifest_bindings(manifest["capability_bindings"], manifest["profile_slices"], sources=manifest["sources"])
        if accepted_binding_digests is not None and (not isinstance(accepted_binding_digests, dict)
            or set(accepted_binding_digests) - manifest["profile_slices"].keys()
            or any(not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value) for value in accepted_binding_digests.values())):
          raise ValueError()
        pairs = {}
        if self.profile is not None and self.profile not in manifest["profile_slices"]:
          raise ValueError()
        selected = set(manifest["profile_slices"]) if self.profile is None else {self.profile}
        selected_sources = set(manifest["sources"]) if self.profile is None else set(manifest["profile_slices"][self.profile]["source_ids"])
        from .pi_lock_metadata import _validate_source_prefix, _validate_source_suffix, _validate_slice, _validate_build_step
        for source_id, source in manifest["sources"].items():
          _validate_source_prefix(source)
          if source["kind"] == "wheel":
            if source_id in selected_sources:
              archive = tree.read(source["vendor_path"], max_bytes=2097152)
              if archive is None or len(archive[0]) != source["size"] or digest(archive[0]) != source["archive_digest"]:
                raise ValueError()
          elif source["kind"] == "asset":
            if "vendor_path" in source and source_id in selected_sources:
              archive = tree.read(source["vendor_path"])
              if archive is None or digest(archive[0]) != source["archive_digest"]:
                raise ValueError()
              if "build_record" in source:
                from .pi_built_assets import load_record, verify_archive
                verify_archive(archive[0], source, load_record(repository, self.layout, source))
          elif source["kind"] != "npm":
            if source_id in selected_sources:
              archive = tree.read(source["vendor_path"])
              if archive is None or digest(archive[0]) != source["archive_digest"]:
                raise ValueError()
          _validate_source_suffix(source)
        for name, piece in manifest["profile_slices"].items():
          _validate_slice(name, piece, manifest)
          if name not in selected:
            continue
          if manifest["schema_version"] == 2:
            from .pi_runtime_files import verify_sources
            verify_sources(repository, piece["runtime_files"])
            if "python_bundle" in piece:
              from .pi_wheel_sources import validate_selected_python_bundle
              with Tree(Path(repository), private=False) as checkout:
                body = checkout.read(piece["python_bundle"]["source"], max_bytes=8388608)
              if body is None: raise ValueError()
              declaration = validate_selected_python_bundle(body[0], piece, manifest["sources"])
              archives = {}
              for source_id in piece["source_ids"]:
                source = manifest["sources"][source_id]
                if source["kind"] == "wheel":
                  archive = tree.read(source["vendor_path"], max_bytes=2097152)
                  if archive is None: raise ValueError()
                  archives[source_id] = archive[0]
              from .pi_python_bundle import plan_python_bundle_install
              plan_python_bundle_install(declaration, archives, occupied_files=[])
          package, lock = tree.read(piece["package_path"]), tree.read(piece["lock_path"])
          if package is None or lock is None or digest(package[0]) != piece["package_json_digest"] or digest(lock[0]) != piece["package_lock_digest"]:
            raise ValueError()
          self._validate_resolution(json.loads(package[0]), json.loads(lock[0]), piece, manifest)
          if manifest["schema_version"] == 2:
            from .pi_license_bundle import validate_source
            validate_source(repository, piece, json.loads(lock[0]), allow_unresolved=manifest["capability_bindings"]["selections"][name]["state"] == "candidate")
          pairs[name] = (package[0], lock[0])
        for step in manifest["build_steps"]:
          _validate_build_step(step, manifest["sources"])
        result = PiLock(manifest["identity"], manifest, pairs)
        if manifest["schema_version"] == 2:
          from .pi_capabilities import validate_selection
          bindings = manifest["capability_bindings"]
          validated = {}
          for profile in pairs:
            piece = manifest["profile_slices"][profile]
            host = manifest["sources"].get("pi-host")
            if host is None or "pi-host" not in piece["source_ids"] or "version" not in host:
              raise ValueError()
            validated[profile] = validate_selection(bindings["catalog"], bindings["providers"], bindings["selections"][profile], result,
              host_version=host["version"], engine=piece["engine"], accepted_binding_digest=(accepted_binding_digests or {}).get(profile))
          result = PiLock(manifest["identity"], manifest, pairs, validated)
    except Exception:
      failed = True
    if failed:
      raise ConfigError("pi-lock-missing-or-stale")
    return result

  def _validate_resolution(self, package, resolution, piece, manifest):
    from .pi_lock_resolution import validate_lock_resolution
    return validate_lock_resolution(package, resolution, piece, manifest)

  def runtime_identity(self, workspace, lock):
    version = lock.metadata.get("schema_version")
    if version != self.layout.schema_version:
      raise ConfigError("pi-lock-family")
    if type(version) is not int or version not in (1, 2) or version != 2 and (lock.validated_bindings or workspace.profile in ("pi-base", "pi-full")):
      raise ConfigError("pi-lock-binding-stale")
    if workspace.profile not in lock.metadata["profile_slices"] or workspace.profile not in lock.pairs or self.profile is not None and workspace.profile != self.profile:
      raise ConfigError("pi-lock-profile")
    if hasattr(workspace, "resolved"):
      selected = workspace.resolved.data["profile"]["agent_options"].get("runtime", {}).get("engine", "node")
      if selected != lock.metadata["profile_slices"][workspace.profile]["engine"]:
        raise ConfigError("pi-lock-engine")
      plugins = workspace.resolved.data["profile"]["plugins"]
      if version == 2:
        try:
          from .pi_profile_config import validate_projection
          data = workspace.resolved.data
          if (type(plugins) is not list or any(type(name) is not str for name in plugins)
              or len(set(plugins)) != len(plugins) or type(data["plugins"]) is not dict
              or any(type(name) is not str or type(row) is not dict for name, row in data["plugins"].items())
              or data["profile"]["id"] != workspace.profile):
            raise ValueError()
          # resolved.data可变：重验原封闭投影与Base范围，不信任早先校验或用户ID回退。
          validate_projection(data)
          selected_plugins = set(plugins)
          for row in data["plugins"].values():
            if (any(type(row[key]) is not str or not row[key] for key in ("package", "version"))
                or type(row["enabled"]) is not bool or not row["enabled"]):
              raise ValueError()
            for key in ("requires", "conflicts", "engines"):
              names = row[key]
              if (type(names) is not list or any(type(name) is not str or not name for name in names)
                  or len(set(names)) != len(names)):
                raise ValueError()
            if (set(row["engines"]) - {"node", "bun"} or selected not in row["engines"]
                or set(row["requires"]) - selected_plugins or set(row["conflicts"]) & selected_plugins):
              raise ValueError()
          plugins = [data["plugins"][name]["capability_id"] for name in plugins]
          for capability in plugins:
            safe_id(capability)
        except Exception:
          raise ConfigError("pi-lock-capabilities") from None
      if set(plugins) - set(lock.metadata["profile_slices"][workspace.profile]["capability_ids"]):
        raise ConfigError("pi-lock-capabilities")
    runtime = digest({"lock_identity": lock.identity, "slice_identity": lock.metadata["profile_slices"][workspace.profile]["identity"],
      "platform": platform_id(), "toolchain_identity": digest(lock.metadata["toolchains"])})
    if lock.metadata["schema_version"] == 2:
      from .pi_capabilities import validate_manifest_bindings, validate_selection, runtime_identity
      try:
        metadata = lock.metadata; piece = metadata["profile_slices"][workspace.profile]
        if metadata["identity"] != lock.identity or digest({k: v for k, v in metadata.items() if k != "identity"}) != lock.identity:
          raise ValueError()
        if digest({k: v for k, v in piece.items() if k != "identity"}) != piece["identity"]:
          raise ValueError()
        package, resolution = lock.pairs[workspace.profile]
        if digest(package) != piece["package_json_digest"] or digest(resolution) != piece["package_lock_digest"]:
          raise ValueError()
        from .pi_license_bundle import validate_source
        validate_source(workspace.repository, piece, json.loads(resolution), allow_unresolved=metadata["capability_bindings"]["selections"][workspace.profile]["state"] == "candidate")
        bindings = metadata["capability_bindings"]
        validate_manifest_bindings(bindings, metadata["profile_slices"], sources=metadata["sources"])
        cached = lock.validated_bindings[workspace.profile]
        host = metadata["sources"]["pi-host"]
        if "pi-host" not in piece["source_ids"]: raise ValueError()
        current = validate_selection(bindings["catalog"], bindings["providers"], bindings["selections"][workspace.profile], lock,
          host_version=host["version"], engine=piece["engine"], accepted_binding_digest=cached.acceptance_context_digest if cached.state == "accepted" else None)
        if current != cached: raise ValueError()
        return runtime_identity(current, runtime_digest=runtime, adapter_version=self.adapter_version, platform=platform_id())
      except Exception:
        raise ConfigError("pi-lock-binding-stale") from None
    return runtime

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

  def resolve_lock(self, repository, *, current_profiles=()):
    from .pi_vendor import resolve_lock
    return resolve_lock(Path(repository), family=self.layout.family, current_profiles=current_profiles)

  def sync(self, workspace, lock, *, progress=None):
    # 在取得可能创建状态目录的写入 guard 前拒绝未核验 profile。
    self.runtime_identity(workspace, lock)
    if lock.metadata["schema_version"] == 2 and lock.validated_bindings[workspace.profile].state == "candidate":
      raise DependencyError("Pi候选能力选择尚未允许激活")
    from .pi_lifecycle import guard
    selected_guard = guard
    if lock.metadata["schema_version"] == 2 and workspace.profile in ("pi-base", "pi-full"):
      from .pi_lifecycle import source_guard
      selected_guard = source_guard
    with selected_guard(workspace):
      result = self._sync(workspace, lock, progress=progress)
      if lock.metadata["schema_version"] == 2 and workspace.profile in ("pi-base", "pi-full"):
        from . import pi_replacement, runtime
        pi_replacement.record_validated(workspace, runtime.record(workspace, lock), pi_replacement.descriptor(lock, workspace.profile))
      return result

  def _sync(self, workspace, lock, *, progress=None):
    announce = progress or (lambda stage: None)
    announce("检查锁与运行包")
    from .pi_runtime_packages import activate, recover_repair, seal
    identity = self.runtime_identity(workspace, lock)
    if lock.metadata["schema_version"] == 2 and lock.validated_bindings[workspace.profile].state == "candidate":
      raise DependencyError("Pi候选能力选择尚未允许激活")
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
        with Tree(stage) as tree, Tree(workspace.repository / self.layout.lock_directory, private=False) as sources:
          for path, content in zip((piece["package_path"], piece["lock_path"]), lock.pairs[workspace.profile]):
            tree.write_state(path, content)
          for source_id in piece["source_ids"]:
            source = lock.metadata["sources"][source_id]
            if source["kind"] != "asset" and "vendor_path" in source:
              archive = (sources.read(source["vendor_path"], max_bytes=2097152) if source["kind"] == "wheel"
                else sources.read(source["vendor_path"]))
              if (archive is None or digest(archive[0]) != source["archive_digest"]
                  or source["kind"] == "wheel" and len(archive[0]) != source["size"]):
                raise DependencyError("Pi归档身份不匹配")
              tree.write_state(source["vendor_path"], archive[0])
        home = stage / "install-home"
        ensure_private(home)
        from .pi_vendor import npm_environment
        env = npm_environment(home)
        tools = ("node", "npm", "bun") if piece["engine"] == "bun" else ("node", "npm")
        announce("检查工具链")
        for name in tools:
          expected = lock.metadata["toolchains"][name]
          actual = checked([name, "--version"], cwd=stage, env=env)
          if actual != expected:
            raise DependencyError("Pi锁要求精确工具链版本；尚未安装运行包")
        package_root = stage / Path(piece["package_path"]).parent
        announce("安装锁定依赖")
        checked(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=package_root, env=env)
        announce("校验构建产物")
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
        install_assets(workspace.repository, stage, piece, lock.metadata, platform_id(), lock_family=self.layout.family)
        from .pi_vendor import install_launcher
        install_launcher(workspace.repository, stage, piece, lock.metadata, runtime_identity=identity)
        from .pi_native_build import install_platform_helpers
        install_platform_helpers(workspace.repository, stage, platform_id())
        shutil.rmtree(home)
        try:
          if "python_bundle" in piece:
            from .pi_python_bundle_runtime import install_locked_python_bundle_stage
            try:
              install_locked_python_bundle_stage(stage, piece, lock.metadata["sources"])
            except ValueError:
              raise DependencyError("Pi Python bundle暂存安装失败") from None
            from .pi_runtime_files import validate_files
            validate_files(stage, piece["runtime_files"], python_bundle=piece["python_bundle"])
          binding_identity = None
          if lock.metadata["schema_version"] == 2:
            from .pi_capabilities import runtime_identity_payload
            base_runtime = digest({"lock_identity": lock.identity, "slice_identity": piece["identity"],
              "platform": platform_id(), "toolchain_identity": digest(lock.metadata["toolchains"])})
            binding_identity = runtime_identity_payload(lock.validated_bindings[workspace.profile], runtime_digest=base_runtime,
              adapter_version=self.adapter_version, platform=platform_id())
          if "durable_owner" in piece:
            if lock.metadata["schema_version"] != 2 or workspace.profile != "pi-full":
              raise DependencyError("Pi owner材料要求显式现代Full声明")
            from .pi_owner_origin import _write_owner_origin
            try:
              _write_owner_origin(stage, lock.metadata, identity=identity, lock_identity=lock.identity, platform=platform_id(),
                toolchains=lock.metadata["toolchains"], binding_identity=binding_identity)
            except ValueError:
              raise DependencyError("Pi owner材料暂存失败") from None
            from .pi_runtime_files import validate_files
            validate_files(stage, piece["runtime_files"], python_bundle=piece["python_bundle"], durable_owner=piece["durable_owner"])
          seal(stage, identity, lock.identity, piece, toolchains=lock.metadata["toolchains"], binding_identity=binding_identity)
        except Conflict:
          raise DependencyError("Pi安装未包含完整必要运行资源，旧运行包保持不变") from None
        announce("激活运行包")
        activate(stage, final, identity)
      return {"installed": True, "identity": identity}
