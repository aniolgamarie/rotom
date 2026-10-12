"""确定性源码归档和显式锁构建；只消费仓库相对源码，不读取旧机器安装树。"""

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import re
import stat
import tarfile
import tempfile
from copy import deepcopy

from .config import _credential_url
from .deployment import json_bytes
from .paths import relative_path, safe_id
from .process import DependencyError, checked, environment
from .schema import ConfigError
from .storage import Tree, ensure_private
from .pi_lock_layout import dependency_layout


INSTALL_PROXY_NAMES = frozenset(("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY"))


def installation_network():
  """下载阶段显式保留标准代理；不传给模型宿主，不接受URL内凭据。"""
  selected = {name: os.environ[name] for name in INSTALL_PROXY_NAMES if os.environ.get(name)}
  for name, value in selected.items():
    if any(ord(char) < 32 or ord(char) == 127 for char in value): raise ConfigError("pi-install-proxy-invalid")
    if name.lower() == "no_proxy": continue
    try:
      url = urlsplit(value)
      if (url.scheme not in ("http", "https") or not url.hostname or url.username is not None or url.password is not None
          or url.path not in ("", "/") or url.query or url.fragment or url.port is not None and not 1 <= url.port <= 65535): raise ValueError()
    except ValueError: raise ConfigError("pi-install-proxy-invalid") from None
  return selected


def npm_environment(home):
  env = environment(home=home)
  env.update(installation_network())
  # npm 拒绝将同一路径同时作为 user/global 来源；两个未创建的私人路径均表示空配置。
  env.update(NPM_CONFIG_USERCONFIG=str(Path(home) / "npm-user.rc"), NPM_CONFIG_GLOBALCONFIG=str(Path(home) / "npm-global.rc"),
    NPM_CONFIG_CACHE=str(Path(home) / "npm-cache"), NPM_CONFIG_IGNORE_SCRIPTS="true")
  return env


def source_files(repository, source_path, excludes=()):
  source = Path(repository) / relative_path(source_path)
  exclusions = {str(relative_path(name)) for name in excludes}
  entries = []
  with Tree(source, private=False) as tree:
    def walk(directory):
      for path in sorted(directory.iterdir(), key=lambda value: os.fsencode(value.name)):
        name = path.relative_to(source).as_posix()
        if name in exclusions or any(name.startswith(item + "/") for item in exclusions):
          continue
        info = path.lstat()
        if path.name in (".git", "node_modules", ".env") or path.name.startswith(".env."):
          raise ConfigError("pi-vendor-forbidden-input")
        if stat.S_ISDIR(info.st_mode):
          walk(path)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
          raw = tree.read(name)
          if raw is None:
            raise ConfigError("pi-vendor-input-changed")
          entries.append((name, raw[0], 0o755 if raw[1] & 0o111 else 0o644))
        else:
          raise ConfigError("pi-vendor-unsafe-input")
    walk(source)
  if not entries:
    raise ConfigError("pi-vendor-empty-input")
  return entries


def source_digest(entries):
  return hashlib.sha256(json_bytes([[name, mode, hashlib.sha256(raw).hexdigest()] for name, raw, mode in entries])).hexdigest()


def build_archive(repository, recipe):
  allowed = {"kind", "source_path", "package", "version", "license_files", "exclude", "commit"}
  if (set(recipe) - allowed or not {"kind", "source_path", "package", "version", "license_files", "exclude"} <= recipe.keys()
      or recipe["kind"] not in ("local", "git")):
    raise ConfigError("pi-vendor-recipe")
  if recipe["kind"] == "git" and not re.fullmatch(r"[0-9a-f]{40}", recipe.get("commit", "")):
    raise ConfigError("pi-vendor-commit")
  if not (Path(repository) / relative_path(recipe["source_path"])).exists():
    raise ConfigError("pi-build-source-not-ready")
  if recipe["source_path"] == "agents/pi/packages/task-keeper-modern":
    from .pi_task_keeper_sources import verify_generated
    verify_generated(repository, recipe["source_path"])
  entries = source_files(repository, recipe["source_path"], recipe["exclude"])
  files = {name: raw for name, raw, _ in entries}
  if not recipe["license_files"] or set(recipe["license_files"]) - files.keys():
    raise ConfigError("pi-vendor-license-missing")
  try:
    package = json.loads(files["package.json"])
  except (ValueError, KeyError):
    raise ConfigError("pi-vendor-package-missing") from None
  if package.get("name") != recipe["package"] or package.get("version") != recipe["version"]:
    raise ConfigError("pi-vendor-package-identity")
  for group in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
    if any(str(value).startswith(("file:", "link:", "workspace:", "/", "~" + "/")) or _credential_url(str(value)) for value in package.get(group, {}).values()):
      raise ConfigError("pi-vendor-nonportable-dependency")
  output = io.BytesIO()
  with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
    with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
      for name, raw, mode in entries:
        info = tarfile.TarInfo("package/" + name)
        info.mode, info.size = mode, len(raw)
        info.uid = info.gid = info.mtime = 0
        info.uname = info.gname = ""
        archive.addfile(info, io.BytesIO(raw))
  raw = output.getvalue()
  record = {key: recipe[key] for key in ("kind", "source_path", "package", "version", "license_files")}
  if "commit" in recipe:
    record["commit"] = recipe["commit"]
  record.update(source_tree_digest=source_digest(entries), archive_digest=hashlib.sha256(raw).hexdigest())
  return raw, record


def _modern_resource_id(source_id, resources, kind, index):
  paths = resources[kind]
  if len(paths) != 1:
    return source_id + "-" + str(index)
  # 原单路径主ID保留；其它单路径kind不能与它跨kind重名。
  primary = next(group for group in ("extensions", "skills", "prompts", "themes") if len(resources[group]) == 1)
  return source_id if kind == primary else source_id + "-" + kind.removesuffix("s")


def read_inputs(repository, *, family=None, current_profiles=()):
  if (type(current_profiles) is not tuple
      or any(type(name) is not str or name not in ("pi-base", "pi-full") for name in current_profiles)
      or len(set(current_profiles)) != len(current_profiles)):
    raise ConfigError("pi-build-current-profiles-invalid")
  layout = dependency_layout(family=family)
  if current_profiles and layout.family != "modern":
    raise ConfigError("pi-build-current-profiles-invalid")
  with Tree(repository, private=False) as tree:
    recipe = tree.read(layout.recipes_path)
    requirements = tree.read(layout.dependencies_path)
  if not recipe or not requirements:
    raise ConfigError("pi-build-input-missing")
  try:
    recipes, document = json.loads(recipe[0]), json.loads(requirements[0])
  except ValueError:
    raise ConfigError("pi-build-input-invalid") from None
  fields = {"schema_version", "toolchains", "platforms", "sources", "profiles", "build_steps"}
  if layout.family == "modern": fields.add("capability_bindings")
  if (set(recipes) != {"schema_version", "sources"} or type(recipes["schema_version"]) is not int or recipes["schema_version"] != 1
      or set(document) != fields or type(document["schema_version"]) is not int
      or document["schema_version"] != layout.schema_version):
    raise ConfigError("pi-build-input-invalid")
  for identity, source in document["sources"].items():
    safe_id(identity)
    if source.get("kind") == "wheel":
      if layout.family != "modern": raise ConfigError("pi-build-source-invalid")
      from .pi_wheel_sources import validate_wheel_source
      try:
        validate_wheel_source(source, locked=False)
      except Exception:
        raise ConfigError("pi-build-source-invalid") from None
      continue
    if source.get("kind") == "asset":
      from jsonschema import Draft202012Validator
      from .pi_assets import validate_asset
      schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/pi-lock.schema.json").read_text())
      if not Draft202012Validator(schema["properties"]["sources"]["additionalProperties"]).is_valid(source):
        raise ConfigError("pi-build-asset-invalid")
      try:
        validate_asset(source)
        if "build_record" in source:
          from .pi_built_assets import load_record
          load_record(repository, layout, source)
        with Tree(repository, private=False) as checkout:
          if any(checkout.read(name, max_bytes=1024 * 1024) is None for name in source["license_files"]):
            raise ValueError()
      except Exception:
        raise ConfigError("pi-build-asset-invalid") from None
      continue
    fields = {"kind", "package", "version", "license_files", "resources"}
    if (set(source) not in (fields, fields | {"license_sources"})
        or source["kind"] not in ("npm", "local", "git")):
      raise ConfigError("pi-build-source-invalid")
    validate_license_sources(source)
    with Tree(repository, private=False) as checkout:
      if any(not checkout.read(name, max_bytes=1024 * 1024) for name in source.get("license_sources", {}).values()):
        raise ConfigError("pi-build-license-source-missing")
    if source["kind"] != "npm" and identity not in recipes["sources"]:
      raise ConfigError("pi-build-source-not-ready")
    if set(source["resources"]) != {"extensions", "skills", "prompts", "themes"}:
      raise ConfigError("pi-build-resource-invalid")
    for paths in source["resources"].values():
      for name in paths:
        relative_path(name)
  for name, profile in document["profiles"].items():
    safe_id(name)
    dependency_layout(profile=name, family=layout.family)
    fields = {"engine", "source_ids", "entrypoint"}
    if layout.family == "modern": fields.update(("runtime_files", "ai_package"))
    if layout.family == "modern" and "python_bundle" in profile: fields.add("python_bundle")
    if layout.family == "modern" and "durable_owner" in profile: fields.add("durable_owner")
    if layout.family == "modern" and "npm_resolution_seed" in profile: fields.add("npm_resolution_seed")
    if layout.family == "modern" and "npm_dependency_overrides" in profile: fields.add("npm_dependency_overrides")
    if (set(profile) != fields or profile["engine"] not in ("node", "bun")
        or set(profile["source_ids"]) - document["sources"].keys()):
      raise ConfigError("pi-build-profile-invalid")
    relative_path(profile["entrypoint"])
    if layout.family == "modern" and "npm_dependency_overrides" in profile:
      from .pi_npm_seed import validate_dependency_overrides
      if "npm_resolution_seed" not in profile:
        validate_dependency_overrides(None, {})
      selected = {key: document["sources"][key] for key in profile["source_ids"]
        if document["sources"][key]["kind"] in ("npm", "local", "git")}
      profile["npm_dependency_overrides"] = validate_dependency_overrides(profile["npm_dependency_overrides"], selected)
    if layout.family == "modern" and "npm_resolution_seed" in profile:
      from .pi_npm_seed import validate_reference
      validate_reference(name, profile["npm_resolution_seed"])
    if layout.family == "modern":
      from .pi_wheel_sources import validate_python_bundle_reference
      try:
        validate_python_bundle_reference(name, profile, document["sources"], locked=False)
      except Exception:
        raise ConfigError("pi-build-profile-invalid") from None
      if "durable_owner" in profile:
        from .pi_modern_launcher import validate_owner_declaration
        validate_owner_declaration(name, profile, document["sources"], toolchains=document["toolchains"], locked=False)
      from .pi_runtime_files import lock_files
      if not isinstance(profile["ai_package"], str) or not re.fullmatch(r"(?:@[a-zA-Z0-9_.-]+/)?[a-zA-Z0-9_.-]+", profile["ai_package"]):
        raise ConfigError("pi-build-profile-invalid")
      lock_files(repository, profile["runtime_files"])
  if layout.family == "modern":
    if set(current_profiles) - document["profiles"].keys():
      raise ConfigError("pi-build-current-profiles-invalid")
    from .pi_capabilities import validate_manifest_bindings
    try:
      bindings = document["capability_bindings"]
      pieces = {name: {"capability_ids": [row["capability_id"] for row in bindings["selections"][name]["bindings"]]}
        for name in document["profiles"]}
      validate_manifest_bindings(bindings, pieces, sources=document["sources"])
      for name, row in bindings["selections"].items():
        if row["state"] != ("current" if name in current_profiles else "candidate"): raise ValueError()
        if name in current_profiles:
          # 仅许可已有current声明；candidate版本不替代verified，且在任何工具调用前检查。
          host_version = document["sources"]["pi-host"]["version"]
          engine = document["profiles"][name]["engine"]
          for binding in row["bindings"]:
            provider = bindings["providers"][binding["provider_id"]]
            if host_version not in provider["verified_host_versions"] or engine not in provider["engines"]: raise ValueError()
    except Exception:
      raise ConfigError("pi-build-bindings-invalid") from None
  return recipes, document


def validate_license_sources(source):
  overlays = source.get("license_sources", {})
  if ("license_sources" in source and source["kind"] != "npm" or not isinstance(overlays, dict)
      or set(overlays) - set(source["license_files"])):
    raise ConfigError("pi-license-source-invalid")
  for target, name in overlays.items():
    relative_path(target)
    relative_path(name)
    if not name.startswith("agents/pi/build/licenses/"):
      raise ConfigError("pi-license-source-invalid")


def complete_resolution_integrity(resolution, *, cwd, env, metadata):
  """仅 lock 阶段补全上游 shrinkwrap 省略的 SRI；地址／版本不一致时拒绝。"""
  from .pi_dependencies import VERSION
  changed = False
  for path, record in resolution.get("packages", {}).items():
    if not path or record.get("inBundle") or "integrity" in record:
      continue
    version, resolved = record.get("version"), record.get("resolved")
    name = record.get("name", path.rsplit("node_modules/", 1)[-1])
    if (not isinstance(version, str) or not VERSION.fullmatch(version)
        or not re.fullmatch(r"(?:@[a-zA-Z0-9_.-]+/)?[a-zA-Z0-9_.-]+", name)
        or not isinstance(resolved, str) or not resolved.startswith("https://") or _credential_url(resolved)):
      raise ConfigError("pi-resolution-integrity-missing")
    key = (name, version, resolved)
    if key not in metadata:
      try:
        dist = json.loads(checked(["npm", "view", name + "@" + version, "dist", "--json"], cwd=cwd, env=env))
        if (not isinstance(dist, dict) or dist.get("tarball") != resolved
            or not isinstance(dist.get("integrity"), str) or not dist["integrity"].startswith("sha512-")):
          raise ValueError()
        import base64
        if len(base64.b64decode(dist["integrity"][7:], validate=True)) != 64:
          raise ValueError()
      except (ValueError, TypeError):
        raise ConfigError("pi-resolution-integrity-unverified") from None
      metadata[key] = dist["integrity"]
    record["integrity"] = metadata[key]
    changed = True
  return changed


def _validate_asset_inputs(repository, sources, layout):
  """发布前核验本锁家族全部声明资产；不下载，也不借用另一家族正文。"""
  from .pi_assets import MAX_ARCHIVE
  try:
    with Tree(repository, private=False) as checkout:
      for source in sources.values():
        if source["kind"] != "asset" or "vendor_path" not in source:
          continue
        if "build_record" in source:
          from .pi_built_assets import MAX_ARCHIVE as BUILT_MAX_ARCHIVE, load_record, verify_archive
          record = load_record(repository, layout, source)
          raw = checkout.read(layout.lock_directory + "/" + source["vendor_path"], max_bytes=BUILT_MAX_ARCHIVE)
          if raw is None: raise ValueError()
          verify_archive(raw[0], source, record)
          continue
        limit = source["size"] if source.get("format") == "raw" else MAX_ARCHIVE
        checksum, size = hashlib.sha256(), 0
        with checkout.open_read(layout.lock_directory + "/" + source["vendor_path"], max_bytes=limit) as (stream, _):
          while chunk := stream.read(min(1024 * 1024, limit - size + 1)):
            size += len(chunk)
            if size > limit:
              raise ValueError()
            checksum.update(chunk)
        if ("size" in source and size != source["size"] or checksum.hexdigest() != source["archive_digest"]):
          raise ValueError()
  except Exception:
    raise ConfigError("pi-build-asset-input") from None


def resolve_lock(repository, *, family=None, current_profiles=()):
  from .pi_dependencies import PiBackend, PiLock, digest, recipe_digest
  layout = dependency_layout(family=family)
  initial_recipe = recipe_digest(repository, family=layout.family)
  recipes, inputs = read_inputs(repository, family=layout.family, current_profiles=current_profiles)
  runtime_files = {}
  if layout.family == "modern":
    from .pi_runtime_files import lock_files
    runtime_files = {name: lock_files(repository, profile["runtime_files"]) for name, profile in inputs["profiles"].items()}
  _validate_asset_inputs(repository, inputs["sources"], layout)
  sources, archives = {}, {}
  # 固定预构建来源和 Full 档案语义全部通过后，才能进入任何旧构建或子进程。
  try:
    from .pi_wheel_sources import validate_wheel_source, validate_selected_python_bundle
    wheel_raw = {}
    for identity, source in inputs["sources"].items():
      if source["kind"] != "wheel": continue
      record = {**source, "vendor_path": "vendor/wheels/" + source["archive_digest"] + "/" + source["wheel_filename"]}
      validate_wheel_source(record, locked=True)
      with Tree(repository / layout.lock_directory, private=False) as checkout:
        raw = checkout.read(record["vendor_path"], max_bytes=2097152)
      if raw is None or len(raw[0]) != record["size"] or digest(raw[0]) != record["archive_digest"]:
        raise ValueError()
      sources[identity] = record
      wheel_raw[identity] = raw[0]
      archives[record["vendor_path"]] = raw[0]
    for name, profile in inputs["profiles"].items():
      if "python_bundle" not in profile: continue
      piece = {**profile, "runtime_files": runtime_files[name]}
      with Tree(repository, private=False) as checkout:
        body = checkout.read(profile["python_bundle"]["source"], max_bytes=8388608)
      if body is None: raise ValueError()
      declaration = validate_selected_python_bundle(body[0], piece, {**inputs["sources"], **sources})
      from .pi_python_bundle import plan_python_bundle_install
      selected_raw = {key: wheel_raw[key] for key in profile["source_ids"] if key in wheel_raw}
      plan_python_bundle_install(declaration, selected_raw, occupied_files=[])
  except Exception:
    raise ConfigError("pi-build-wheel-input") from None
  # 先完整检查本地输入；缺待迁移源码时，零下载、零锁写入。
  for identity, source in inputs["sources"].items():
    if source["kind"] == "wheel":
      continue
    elif source["kind"] == "asset":
      sources[identity] = dict(source)
    elif source["kind"] != "npm":
      recipe = recipes["sources"][identity]
      if any(recipe.get(key) != source[key] for key in ("kind", "package", "version", "license_files")):
        raise ConfigError("pi-build-source-identity")
      raw, record = build_archive(repository, recipe)
      record["vendor_path"] = "vendor/" + identity + "-" + record["archive_digest"] + ".tgz"
      archives[record["vendor_path"]] = raw
      sources[identity] = record
  seeded = {}
  if layout.family == "modern":
    for name, profile in inputs["profiles"].items():
      if "npm_resolution_seed" not in profile: continue
      from .pi_npm_seed import load_seed
      selected = {key: inputs["sources"][key] for key in profile["source_ids"]
        if inputs["sources"][key]["kind"] in ("npm", "local", "git")}
      dependencies = {source["package"]: source["version"] if source["kind"] == "npm" else "file:../" + sources[key]["vendor_path"] for key, source in selected.items()}
      if len(dependencies) != len(selected):
        raise ConfigError("pi-build-package-collision")
      package = {"name": "agentcfg-" + name, "version": "1.0.0", "private": True, "dependencies": dependencies}
      if "npm_dependency_overrides" in profile:
        from .pi_npm_seed import validate_dependency_overrides
        package["overrides"] = validate_dependency_overrides(profile["npm_dependency_overrides"], selected)
      seed, identity = load_seed(repository, name, profile["npm_resolution_seed"], package, selected, sources, archives)
      seeded[name] = (selected, json_bytes(package), seed, identity)
  slices, metadata = {}, {}
  with tempfile.TemporaryDirectory(prefix="agentcfg-pi-lock-") as temporary:
    root = Path(temporary)
    home = root / "install-home"
    ensure_private(home)
    env = npm_environment(home)
    for tool in ("node", "npm"):
      if checked([tool, "--version"], cwd=root, env=env) != inputs["toolchains"][tool]:
        raise DependencyError("Pi锁构建要求精确Node/npm版本")
    with Tree(root) as stage:
      for path, raw in archives.items():
        stage.write_state(path, raw)
      for name, profile in inputs["profiles"].items():
        if name in seeded:
          selected, package_raw, seed, identity = seeded[name]
        else:
          selected = {key: inputs["sources"][key] for key in profile["source_ids"]
            if inputs["sources"][key]["kind"] in ("npm", "local", "git")}
          dependencies = {source["package"]: source["version"] if source["kind"] == "npm" else "file:../" + sources[key]["vendor_path"] for key, source in selected.items()}
          if len(dependencies) != len(selected):
            raise ConfigError("pi-build-package-collision")
          package = {"name": "agentcfg-" + name, "version": "1.0.0", "private": True, "dependencies": dependencies}
          package_raw = json_bytes(package)
        stage.write_state(name + "/package.json", package_raw)
        if name in seeded: stage.write_state(name + "/package-lock.json", seed)
        checked(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=root / name, env=env)
        raw = stage.read(name + "/package-lock.json")
        if raw is None:
          raise DependencyError("Pi安装器未生成完整锁")
        lock = json.loads(raw[0])
        if complete_resolution_integrity(lock, cwd=root / name, env=env, metadata=metadata):
          stage.write_state(name + "/package-lock.json", json_bytes(lock))
          raw = stage.read(name + "/package-lock.json")
        if name in seeded:
          from .pi_npm_seed import validate_seed_result
          validate_seed_result(identity, lock)
        # 现代锁的旧manifest始终引用旧完整pair；新pair发布中断不能覆盖它的正文。
        # 保持目录深度不变，npm的 ../vendor 相对引用无需改写。
        slice_root = name
        if layout.family == "modern":
          slice_root += "-" + digest(package_raw + b"\0" + raw[0])
          stage.write_state(slice_root + "/package.json", package_raw)
          stage.write_state(slice_root + "/package-lock.json", raw[0])
        resources = {kind: [] for kind in ("extensions", "skills", "prompts", "themes")}
        for key, source in selected.items():
          entry = lock.get("packages", {}).get("node_modules/" + source["package"], {})
          if entry.get("version") != source["version"]:
            raise DependencyError("Pi解析版本不匹配")
          if source["kind"] == "npm":
            record = {"kind": "npm", "package": source["package"], "version": source["version"],
              "resolved": entry.get("resolved"), "integrity": entry.get("integrity"), "license_files": source["license_files"]}
            if "license_sources" in source:
              record["license_sources"] = source["license_sources"]
            if key in sources and sources[key] != record:
              raise DependencyError("Pi切片来源解析不一致")
            sources[key] = record
          for kind, paths in source["resources"].items():
            for index, path in enumerate(paths):
              resource_id = key if len(paths) == 1 else key + "-" + str(index)
              capability_id = key
              if layout.family == "modern":
                resource_id = _modern_resource_id(key, source["resources"], kind, index)
                bindings = inputs["capability_bindings"]
                owners = [row["capability_id"] for row in bindings["selections"][name]["bindings"]
                  if bindings["providers"][row["provider_id"]]["source_id"] == key
                  and resource_id in bindings["providers"][row["provider_id"]]["resource_ids"]]
                if len(owners) != 1: raise ConfigError("pi-build-resource-owner")
                capability_id = owners[0]
              resources[kind].append({"id": resource_id, "capability_id": capability_id,
                "path": slice_root + "/node_modules/" + source["package"] + "/" + path})
        capabilities = profile["source_ids"] if layout.family == "legacy" else sorted({row["capability_id"] for row in inputs["capability_bindings"]["selections"][name]["bindings"]})
        piece = {"engine": profile["engine"], "source_ids": profile["source_ids"], "capability_ids": capabilities,
          "package_path": slice_root + "/package.json", "lock_path": slice_root + "/package-lock.json",
          "package_json_digest": digest(package_raw), "package_lock_digest": digest(raw[0]),
          "entrypoint": slice_root + "/" + profile["entrypoint"], "resource_manifest": resources,
          "resource_manifest_digest": digest(resources)}
        if layout.family == "modern": piece.update(runtime_files=runtime_files[name], ai_package=profile["ai_package"])
        if "python_bundle" in profile: piece["python_bundle"] = deepcopy(profile["python_bundle"])
        if "durable_owner" in profile: piece["durable_owner"] = deepcopy(profile["durable_owner"])
        piece["identity"] = digest(piece)
        slices[name] = piece
      if recipe_digest(repository, family=layout.family) != initial_recipe:
        raise ConfigError("pi-build-input-changed")
      if layout.family == "modern":
        from .pi_runtime_files import verify_sources
        for rows in runtime_files.values(): verify_sources(repository, rows)
      manifest = {"schema_version": layout.schema_version, "adapter_version": "pi-1", "recipe_digest": initial_recipe,
        "toolchains": inputs["toolchains"], "platforms": inputs["platforms"], "sources": sources,
        "profile_slices": slices, "build_steps": inputs["build_steps"], "compatibility": {"bridge_version": 1}}
      if layout.family == "modern": manifest["capability_bindings"] = deepcopy(inputs["capability_bindings"])
      manifest["identity"] = digest(manifest)
      # 通过与实际读取相同的闭合校验之后才写发布目录，manifest 最后原子替换。
      from jsonschema import Draft202012Validator
      schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/pi-lock.schema.json").read_text())
      if not Draft202012Validator(schema).is_valid(manifest):
        raise ConfigError("pi-generated-lock-invalid")
      backend = PiBackend(family=layout.family)
      for name, piece in slices.items():
        from .pi_assets import validate_asset_platforms
        validate_asset_platforms(piece, manifest)
        if layout.family == "modern":
          from .pi_modern_launcher import validate_destinations, validate_locked_ai
          validate_destinations(piece, manifest)
          validate_locked_ai(json.loads(stage.read(piece["lock_path"])[0]), piece)
          from .pi_license_bundle import validate_source
          validate_source(repository, piece, json.loads(stage.read(piece["lock_path"])[0]),
            allow_unresolved=manifest["capability_bindings"]["selections"][name]["state"] == "candidate")
        backend._validate_resolution(json.loads(stage.read(piece["package_path"])[0]), json.loads(stage.read(piece["lock_path"])[0]), piece, manifest)
      if layout.family == "modern":
        from .pi_capabilities import validate_selection
        bindings = manifest["capability_bindings"]
        lock = PiLock(manifest["identity"], manifest, {name: (stage.read(piece["package_path"])[0], stage.read(piece["lock_path"])[0]) for name, piece in slices.items()})
        for name, piece in slices.items():
          if "pi-host" not in piece["source_ids"]: raise ConfigError("pi-build-host-source")
          validate_selection(bindings["catalog"], bindings["providers"], bindings["selections"][name], lock,
            host_version=sources["pi-host"]["version"], engine=piece["engine"])
      _validate_asset_inputs(repository, sources, layout)
      # lock 是明确的可信源修改；不把共享挂载上的仓库误当私人运行状态目录。
      with Tree(repository, private=False) as checkout:
        with checkout.parent(layout.lock_directory + "/.output-probe", create=True):
          pass
      with Tree(repository / layout.lock_directory, private=False) as target:
        for path, raw in archives.items():
          target.write_state(path, raw)
        for piece in slices.values():
          for key in ("package_path", "lock_path"):
            target.write_state(piece[key], stage.read(piece[key])[0])
        target.write_state("manifest.json", json_bytes(manifest))
  return backend.read_lock(repository)


def install_source_licenses(source, target, prefix, record):
  validate_license_sources(record)
  for name, origin in record.get("license_sources", {}).items():
    raw = source.read(origin, max_bytes=1024 * 1024)
    destination = (prefix / "node_modules" / record["package"] / relative_path(name)).as_posix()
    before = target.read(destination)
    if raw is None or not raw[0] or before is not None and before[0] != raw[0]:
      raise DependencyError("Pi许可补充来源缺失或与已安装许可证冲突")
    if before is None:
      target.write_new(destination, raw[0])
  for name in record["license_files"]:
    path = prefix / "node_modules" / record["package"] / relative_path(name)
    if target.read(path.as_posix()) is None:
      raise DependencyError("Pi依赖许可证文件缺失")


def install_launcher(repository, stage, piece, manifest, *, runtime_identity=None):
  if manifest["schema_version"] == 2:
    from .pi_modern_launcher import install_launcher as install_modern
    return install_modern(repository, stage, piece, manifest, runtime_identity=runtime_identity)
  from .pi_dependencies import platform_id, digest
  with Tree(repository, private=False) as source, Tree(stage) as target:
    prefix = Path(piece["package_path"]).parent
    for identity in piece["source_ids"]:
      record = manifest["sources"][identity]
      if record["kind"] == "asset":
        continue
      install_source_licenses(source, target, prefix, record)
    runtime_sources = sorted((repository / "agents/pi/runtime").glob("*.ts"))
    if not {"launch.ts", "resource-loader.ts"} <= {path.name for path in runtime_sources}:
      raise DependencyError("Pi受控启动源码未就绪")
    for path in runtime_sources:
      raw = source.read(path.relative_to(repository).as_posix())
      if raw is None:
        raise DependencyError("Pi受控启动源码未就绪")
      # runtime 源码使用可直接执行的 ECMAScript 子集，无安装时编译器下载。
      content = re.sub(rb'("\./[a-z-]+)\.ts"', rb'\1.mjs"', raw[0])
      target.write_state("runtime/" + path.stem + ".mjs", content)
    sources = []
    for directory, pattern in (("src/agentcfg", "*.py"), ("schemas", "*.json"), ("agents/pi/schemas", "*.json")):
      sources.extend(path for path in sorted((repository / directory).glob(pattern))
        if path.name not in {"pi_delegate_mcp.py", "pi_delegate_commands.py"})
    sources.extend(repository / "scripts" / name for name in ("pi-supervisor.py", "pi-control.py", "pi-exec.py", "pi-namespace-exec.py", "pi-project-check", "pi-delegate-codex.py", "model-delegate.py", "model-delegate-batch.py", "pi-file-operation.py", "pi-checkpoint.py", "pi-native-scenario.py", "pi-native-recovery.py"))
    if "pi-readseek" in piece["source_ids"]: sources.append(repository / "scripts/pi-readseek.py")
    if "pi-web" in piece["source_ids"]: sources.append(repository / "scripts/pi-web-cli.py")
    sources.append(repository / "scripts/pi-supervisor-macos.c")
    sources.append(repository / "agents/pi/runtime/sandbox-macos.sb")
    if "model-delegate" in piece["source_ids"]:
      sources.extend(sorted((repository / "shared/skills/model-delegate/schemas").glob("*-v2.json")))
      presets = list((repository / "shared/skills/model-delegate/presets").glob("*.md"))
      if len(presets) != 7:
        raise DependencyError("委托用途模板不完整")
      sources.extend(sorted(presets))
    if not (repository / "src/agentcfg/pi_host.py").is_file():
      raise DependencyError("Pi监督源码尚未完整迁入")
    for path in sources:
      name = path.relative_to(repository).as_posix()
      raw = source.read(name)
      if raw is None:
        raise DependencyError("Pi监督源码不完整")
      target.write_state("supervisor/" + name, raw[0])
    if piece["engine"] == "bun":
      for name in ("bunfig.locked.toml", "tsconfig.locked.json"):
        raw = source.read("agents/pi/runtime/" + name)
        if raw is None:
          raise DependencyError("Bun封闭启动配置未就绪")
        target.write_state("runtime/" + name, raw[0])
    commands = {"schema_version": 1, "programs": {"file-operation": {"entrypoint": "supervisor/scripts/pi-file-operation.py", "kind": "external", "engine": "python"}}}
    commands["programs"]["checkpoint"] = {"entrypoint": "supervisor/scripts/pi-checkpoint.py", "kind": "external", "engine": "python"}
    commands["programs"]["ordinary-command"] = {"entrypoint": "supervisor/scripts/pi-project-check", "kind": "external", "engine": "python"}
    if "pi-mcp" in piece["source_ids"]:
      script = target.read(str(Path(piece["package_path"]).parent / "node_modules/pi-mcp-adapter/mcp-script-process.mjs"))
      if script is None: raise DependencyError("MCP脚本监督入口缺失")
      target.write_state("runtime/mcp-script-process.mjs", script[0])
      commands["programs"]["mcp-script"] = {"entrypoint": "runtime/mcp-script-process.mjs", "kind": "external", "engine": "node"}
    if "pi-readseek" in piece["source_ids"]:
      from .pi_readseek_native import install_native
      install_native(repository, stage, piece, platform_id())
      from .pi_readseek_vision import install_vision
      install_vision(stage, piece)
      contracts = source.read("agents/pi/runtime/readseek-tool-contracts.json")
      if contracts is None or target.read("runtime/readseek-process.mjs") is None:
        raise DependencyError("ReadSeek计算入口或参数契约缺失")
      target.write_state("runtime/readseek-tool-contracts.json", contracts[0])
      commands["programs"]["readseek"] = {"entrypoint": "runtime/readseek-process.mjs", "kind": "external", "engine": "node"}
      commands["programs"]["readseek-driver"] = {"entrypoint": "supervisor/scripts/pi-readseek.py", "kind": "external", "engine": "python"}
    if "task-keeper" in piece["source_ids"]:
      if piece["engine"] != "node":
        raise DependencyError("受管worker要求锁定Node运行切片")
      for name in ("managed-worker-main", "managed-worker", "guarded-tools", "managed-http-transport", "route-fetch", "workspace-main"):
        if target.read("runtime/" + name + ".mjs") is None:
          raise DependencyError("受管worker执行闭包缺失")
      commands["programs"]["worker"] = {"entrypoint": "runtime/managed-worker-main.mjs", "kind": "worker", "engine": "node"}
      commands["programs"]["workspace"] = {"entrypoint": "runtime/workspace-main.mjs", "kind": "external", "engine": "node"}
      commands["programs"]["check"] = {"entrypoint": "supervisor/scripts/pi-project-check", "kind": "check", "engine": "python"}
    if "model-delegate" in piece["source_ids"]:
      for name in ("delegate-pi", "delegate-pi-main", "external-executor", "external-rpc"):
        if target.read("runtime/" + name + ".mjs") is None:
          raise DependencyError("委托执行闭包缺失")
      if len(list((repository / "shared/skills/model-delegate/schemas").glob("*-v2.json"))) != 5:
        raise DependencyError("委托V2协议源码不完整")
      commands["programs"]["delegate-pi"] = {"entrypoint": "runtime/delegate-pi-main.mjs", "kind": "external", "engine": piece["engine"]}
      assets = [manifest["sources"][name] for name in piece["source_ids"] if manifest["sources"][name]["kind"] == "asset"
        and manifest["sources"][name]["platform"] == platform_id() and "/openai/codex/releases/" in manifest["sources"][name]["url"]]
      if any(row["target"] != "bin/codex-resources/bwrap" for row in assets):
        if sum(row["target"] == "bin/codex" for row in assets) != 1 or target.read("bin/codex") is None:
          raise DependencyError("所选Codex发行物没有唯一已安装入口")
        for companion in ("codex-code-mode-host", "codex-responses-api-proxy"):
          name = "bin/" + companion
          binary = target.read(name)
          if sum(row["target"] == name for row in assets) != 1 or binary is None or not binary[1] & 0o111:
            raise DependencyError("所选Codex发行物缺少完整官方辅助程序")
        if platform_id().startswith("linux-"):
          companions = [row for row in assets if row["target"] == "bin/codex-resources/bwrap"]
          binary = target.read("bin/codex-resources/bwrap")
          if len(companions) != 1 or binary is None or not binary[1] & 0o111:
            raise DependencyError("所选Codex发行物缺少同版本锁定的bubblewrap资源")
        commands["programs"]["codex-login"] = {"entrypoint": "bin/codex", "kind": "codex", "engine": "native"}
        commands["programs"]["delegate-codex"] = {"entrypoint": "supervisor/scripts/pi-delegate-codex.py", "kind": "codex", "engine": "python", "backend_entrypoint": "bin/codex"}
    target.write_state("runtime/commands.json", json_bytes(commands))
    hosts = [manifest["sources"][name] for name in piece["source_ids"]
      if manifest["sources"][name]["kind"] != "asset" and ("/node_modules/" + manifest["sources"][name]["package"] + "/") in piece["entrypoint"]]
    if len(hosts) != 1:
      raise DependencyError("Pi入口没有唯一已锁定宿主来源")
    target.write_state("runtime/profile.json", json_bytes({"schema_version": 1, "engine": piece["engine"],
      "entrypoint": piece["entrypoint"], "resources": piece["resource_manifest"],
      "lock_identity": manifest["identity"], "sdk_version": hosts[0]["version"], "sdk_package": hosts[0]["package"],
      "slice_identity": piece["identity"], "toolchains": manifest["toolchains"], "platform": platform_id(),
      "runtime_identity": digest({"lock_identity": manifest["identity"], "slice_identity": piece["identity"],
        "platform": platform_id(), "toolchain_identity": digest(manifest["toolchains"])})}))
