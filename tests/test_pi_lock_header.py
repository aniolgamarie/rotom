"""固定schema头部、独立旧read_lock基线与默认隔离fixture；无宿主执行。"""

import builtins
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import traceback
from types import SimpleNamespace

import pytest

import agentcfg.pi_dependencies as dependencies
import agentcfg.pi_lock_header as header
from agentcfg.schema import ConfigError
from test_pi_dependencies import fixture_repository, payload
from test_pi_capability_manifest import binding_repository, _write_manifest, proof


# 本轮前像c46b23194f8a278e7a5055e73309bdc3b5cad74b9e824610c9434044f6dfa02f。
# 原read_lock正文独立冻结；保留旧schema/identity流程，不经过新header。
LEGACY_READ_LOCK = r"""
def read_lock(self, repository, *, accepted_binding_digests=None):
  result, failed = None, False
  try:
    root = Path(repository) / self.layout.lock_directory
    with Tree(root, private=False) as tree:
      raw = tree.read("manifest.json")
      if raw is None:
        raise ValueError()
      manifest = json.loads(raw[0])
      schema = json.loads((ROOT / "schemas/pi-lock.schema.json").read_text())
      if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != self.layout.schema_version
          or not Draft202012Validator(schema, registry=Registry()).is_valid(manifest)):
        raise ValueError()
      if (digest({k: v for k, v in manifest.items() if k != "identity"}) != manifest["identity"]
          or manifest["recipe_digest"] != recipe_digest(Path(repository), family=self.layout.family)):
        raise ValueError()
      if manifest["schema_version"] == 2:
        from .pi_capabilities import validate_manifest_bindings
        validate_manifest_bindings(manifest["capability_bindings"], manifest["profile_slices"])
      if accepted_binding_digests is not None and (not isinstance(accepted_binding_digests, dict)
          or set(accepted_binding_digests) - manifest["profile_slices"].keys()
          or any(not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value) for value in accepted_binding_digests.values())):
        raise ValueError()
      pairs = {}
      if self.profile is not None and self.profile not in manifest["profile_slices"]:
        raise ValueError()
      selected = set(manifest["profile_slices"]) if self.profile is None else {self.profile}
      selected_sources = set(manifest["sources"]) if self.profile is None else set(manifest["profile_slices"][self.profile]["source_ids"])
      for source_id, source in manifest["sources"].items():
        from .pi_vendor import validate_license_sources
        validate_license_sources(source)
        if source["kind"] == "npm":
          if not {"package", "version", "resolved", "integrity"} <= source.keys():
            raise ValueError()
          if not VERSION.fullmatch(source["version"]) or not source["resolved"].startswith("https://") or _credential_url(source["resolved"]):
            raise ValueError()
          if not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", source["integrity"]) or len(base64.b64decode(source["integrity"][7:], validate=True)) != 64:
            raise ValueError()
        elif source["kind"] == "asset":
          from .pi_assets import validate_asset
          validate_asset(source)
          if "vendor_path" in source and source_id in selected_sources:
            archive = tree.read(source["vendor_path"])
            if archive is None or digest(archive[0]) != source["archive_digest"]:
              raise ValueError()
            if "build_record" in source:
              from .pi_built_assets import load_record, verify_archive
              verify_archive(archive[0], source, load_record(repository, self.layout, source))
        else:
          if not {"package", "version", "vendor_path", "archive_digest"} <= source.keys() or not VERSION.fullmatch(source["version"]):
            raise ValueError()
          if source_id in selected_sources:
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
        if manifest["schema_version"] == 2:
          from .pi_modern_launcher import validate_destinations
          validate_destinations(piece, manifest)
        if digest({k: v for k, v in piece.items() if k != "identity"}) != piece["identity"]:
          raise ValueError()
        if digest(piece["resource_manifest"]) != piece["resource_manifest_digest"]:
          raise ValueError()
        for entries in piece["resource_manifest"].values():
          for entry in entries:
            if entry["capability_id"] not in piece["capability_ids"]:
              raise ValueError()
        if name not in selected:
          continue
        if manifest["schema_version"] == 2:
          from .pi_runtime_files import verify_sources
          verify_sources(repository, piece["runtime_files"])
        package, lock = tree.read(piece["package_path"]), tree.read(piece["lock_path"])
        if package is None or lock is None or digest(package[0]) != piece["package_json_digest"] or digest(lock[0]) != piece["package_lock_digest"]:
          raise ValueError()
        self._validate_resolution(json.loads(package[0]), json.loads(lock[0]), piece, manifest)
        if manifest["schema_version"] == 2:
          from .pi_license_bundle import validate_source
          validate_source(repository, piece, json.loads(lock[0]), allow_unresolved=manifest["capability_bindings"]["selections"][name]["state"] == "candidate")
        pairs[name] = (package[0], lock[0])
      for step in manifest["build_steps"]:
        if (set(step["source_ids"]) - manifest["sources"].keys()
            or set(step["expected_outputs"]) != set(step["output_digests"])):
          raise ValueError()
        for path in (*step["input_digests"], *step["output_digests"]):
          relative_path(path)
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

"""


@pytest.fixture
def old_read_lock():
  namespace = vars(dependencies).copy()
  exec(compile(LEGACY_READ_LOCK, "<fixed-before-header-read-lock>", "exec"), namespace)
  return namespace["read_lock"]


def reseal(manifest):
  manifest["identity"] = dependencies.digest({key: value for key, value in manifest.items() if key != "identity"})


@pytest.fixture
def legacy_manifest(tmp_path):
  _, manifest = fixture_repository(tmp_path)
  return manifest


def load_own_header(tmp_path):
  # 复制真实自有源到固定supervisor布局；不是installed资格或capability工厂。
  root = tmp_path / "runtime" / "supervisor"
  source = root / "src/agentcfg/pi_lock_header.py"
  source.parent.mkdir(parents=True)
  source.write_bytes(Path(header.__file__).read_bytes())
  schema = root / "schemas/pi-lock.schema.json"
  schema.parent.mkdir()
  schema.write_bytes((Path(header.__file__).resolve().parents[2] / "schemas/pi-lock.schema.json").read_bytes())
  spec = importlib.util.spec_from_file_location("agentcfg._synthetic_lock_header", source)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module, schema


PROFILES_STATES = [("legacy", "current")] + [
  (profile, state) for profile in ("pi-base", "pi-full", "all") for state in ("current", "candidate", "accepted")]


@pytest.mark.parametrize("profile,state", PROFILES_STATES)
def test_real_fixture_read_lock_and_runtime_identity_equal_independent_old_baseline(tmp_path, monkeypatch, old_read_lock, profile, state):
  if profile == "legacy":
    root, manifest = fixture_repository(tmp_path)
    backend = dependencies.PiBackend()
    accepted = None
  else:
    workspace, manifest = binding_repository(tmp_path)
    root = workspace.repository
    if state != "current":
      for selection in manifest["capability_bindings"]["selections"].values(): selection["state"] = state
      _write_manifest(root, manifest)
    accepted = {name: proof(manifest, name) for name in manifest["profile_slices"]} if state == "accepted" else None
    backend = dependencies.PiBackend(family="modern") if profile == "all" else dependencies.PiBackend(profile=profile)
  def capture(lock):
    identities = {name: backend.runtime_identity(SimpleNamespace(profile=name, repository=root), lock) for name in lock.pairs}
    return lock.identity, deepcopy(lock.metadata), dict(lock.pairs), dict(lock.validated_bindings), identities
  with monkeypatch.context() as old:
    old.setattr(dependencies.PiBackend, "read_lock", old_read_lock)
    # 旧基线若意外调用新header则直接失败，不允许伪造双新实现相等。
    old.setattr(header, "validate_lock_header", lambda *args, **kwargs: pytest.fail("old baseline called new header"))
    before = capture(backend.read_lock(root, accepted_binding_digests=accepted))
  after = capture(backend.read_lock(root, accepted_binding_digests=accepted))
  assert after == before
  assert after[0] == manifest["identity"] and after[1] == manifest
  assert all(isinstance(raw, bytes) for pair in after[2].values() for raw in pair)


@pytest.mark.parametrize("fault", [None, "unknown", "reserved", "bool", "float", "mismatch", "identity"])
def test_v1_schema_version_identity_pair_controls(legacy_manifest, fault):
  manifest = deepcopy(legacy_manifest)
  if fault == "unknown": manifest["untrusted"] = "synthetic"
  if fault == "reserved": manifest["profile_slices"]["pi-base"] = manifest["profile_slices"].pop("pi-fixture")
  if fault == "bool": manifest["schema_version"] = True
  if fault == "float": manifest["schema_version"] = 1.0
  if fault == "mismatch": manifest["schema_version"] = 2
  reseal(manifest)
  if fault == "identity": manifest["identity"] = "0" * 64
  before = deepcopy(manifest)
  if fault is None: assert header.validate_lock_header(manifest, schema_version=1) is None
  else:
    with pytest.raises(ValueError) as error: header.validate_lock_header(manifest, schema_version=1)
    assert error.value.args == ("pi-lock-header",)
  assert manifest == before


@pytest.mark.parametrize("schema_version", [True, 1.0, "1", 0, 3, None])
def test_expected_version_requires_native_supported_integer(legacy_manifest, schema_version):
  with pytest.raises(ValueError) as error:
    header.validate_lock_header(legacy_manifest, schema_version=schema_version)
  assert error.value.args == ("pi-lock-header",)


@pytest.mark.parametrize("fault", [None, "missing-binding", "unknown-binding", "selection-keys"])
def test_v2_full_binding_schema_controls(tmp_path, fault):
  _, manifest = binding_repository(tmp_path)
  if fault == "missing-binding": manifest.pop("capability_bindings")
  if fault == "unknown-binding": manifest["capability_bindings"]["authority"] = True
  if fault == "selection-keys": manifest["capability_bindings"]["selections"].pop("pi-full")
  reseal(manifest)
  before = deepcopy(manifest)
  if fault is None: assert header.validate_lock_header(manifest, schema_version=2) is None
  else:
    with pytest.raises(ValueError) as error: header.validate_lock_header(manifest, schema_version=2)
    assert error.value.args == ("pi-lock-header",)
  assert manifest == before


def test_canonical_non_ascii_and_input_unchanged(legacy_manifest):
  manifest = deepcopy(legacy_manifest)
  manifest["toolchains"]["node"] = "虚构工具链版本"
  reseal(manifest)
  before = deepcopy(manifest)
  assert header.validate_lock_header(manifest, schema_version=1) is None
  assert manifest == before


@pytest.mark.parametrize("fault", [None, "schema", "version", "identity", "recipe", "binding"])
def test_read_lock_actual_short_circuit_order(tmp_path, monkeypatch, fault):
  import agentcfg.pi_capabilities as capabilities
  workspace, manifest = binding_repository(tmp_path)
  if fault == "schema": manifest["unknown"] = "synthetic"
  if fault == "version": manifest["schema_version"] = 2.0
  if fault == "recipe": manifest["recipe_digest"] = "0" * 64
  if fault == "binding": manifest["capability_bindings"]["selections"]["pi-base"]["source_revision"] = 2
  reseal(manifest)
  if fault == "identity": manifest["identity"] = "0" * 64
  (workspace.repository / "locks/pi-modern/manifest.json").write_bytes(payload(manifest))
  events = []
  read_text, validator, canonical = Path.read_text, header.Draft202012Validator, header.json_bytes
  recipe, bindings = dependencies.recipe_digest, capabilities.validate_manifest_bindings
  def read(path, *args, **kwargs):
    if path.name == "pi-lock.schema.json": events.append("resource")
    return read_text(path, *args, **kwargs)
  def make_validator(schema, *, registry):
    events.append("validator")
    assert type(registry) is dependencies.Registry
    actual = validator(schema, registry=registry)
    class Recorded:
      def is_valid(self, value): events.append("schema"); return actual.is_valid(value)
    return Recorded()
  def identity(value): events.append("identity"); return canonical(value)
  def recipe_check(*args, **kwargs): events.append("recipe"); return recipe(*args, **kwargs)
  def binding_check(*args, **kwargs): events.append("binding"); return bindings(*args, **kwargs)
  monkeypatch.setattr(Path, "read_text", read)
  monkeypatch.setattr(header, "Draft202012Validator", make_validator)
  monkeypatch.setattr(header, "json_bytes", identity)
  monkeypatch.setattr(dependencies, "recipe_digest", recipe_check)
  monkeypatch.setattr(capabilities, "validate_manifest_bindings", binding_check)
  backend = dependencies.PiBackend(profile="pi-base")
  if fault is None: backend.read_lock(workspace.repository)
  else:
    with pytest.raises(ConfigError) as error: backend.read_lock(workspace.repository)
    assert error.value.args == ConfigError("pi-lock-missing-or-stale").args
  expected = {None: ["resource", "validator", "schema", "identity", "recipe", "binding"],
    "version": ["resource"], "schema": ["resource", "validator", "schema"],
    "identity": ["resource", "validator", "schema", "identity"],
    "recipe": ["resource", "validator", "schema", "identity", "recipe"],
    "binding": ["resource", "validator", "schema", "identity", "recipe", "binding"]}
  assert events == expected[fault]


@pytest.mark.parametrize("fault", ["missing", "parse", "read", "validator", "identity"])
def test_fixed_resource_and_internal_errors_remove_secret_chains(tmp_path, legacy_manifest, monkeypatch, fault):
  module, schema = load_own_header(tmp_path)
  if fault == "missing": schema.unlink()
  if fault == "parse": schema.write_text("invalid JSON")
  def broken(*args, **kwargs): raise RuntimeError("synthetic-input-secret")
  if fault == "read": monkeypatch.setattr(Path, "read_text", broken)
  if fault == "validator": monkeypatch.setattr(module, "Draft202012Validator", broken)
  if fault == "identity": monkeypatch.setattr(module, "json_bytes", broken)
  try:
    raise RuntimeError("synthetic-caller-secret")
  except RuntimeError as caller:
    with pytest.raises(ValueError) as error: module.validate_lock_header(legacy_manifest, schema_version=1)
    assert error.value.args == ("pi-lock-header",)
    assert error.value.__cause__ is None and error.value.__context__ is None
    formatted = "".join(traceback.format_exception(error.value))
    assert "synthetic-input-secret" not in formatted and "synthetic-caller-secret" not in formatted
    assert caller.args == ("synthetic-caller-secret",)
    assert caller.__cause__ is None and caller.__context__ is None


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit])
def test_base_exception_propagates(legacy_manifest, monkeypatch, exception):
  def interrupt(*args, **kwargs): raise exception("synthetic interrupt")
  monkeypatch.setattr(Path, "read_text", interrupt)
  with pytest.raises(exception): header.validate_lock_header(legacy_manifest, schema_version=1)


def test_fixed_supervisor_layout_reads_every_call_without_cache(tmp_path, legacy_manifest, monkeypatch):
  module, schema = load_own_header(tmp_path)
  reads = []
  actual = Path.read_text
  def read(path, *args, **kwargs):
    reads.append(path)
    assert path == schema
    return actual(path, *args, **kwargs)
  monkeypatch.setattr(Path, "read_text", read)
  assert module.validate_lock_header(legacy_manifest, schema_version=1) is None
  schema.write_text('{"type":"array"}')
  # 新schema正文拒绝dict；真实再次读取，不能使用前次validator缓存。
  with pytest.raises(ValueError): module.validate_lock_header(legacy_manifest, schema_version=1)
  schema.unlink()
  with pytest.raises(ValueError): module.validate_lock_header(legacy_manifest, schema_version=1)
  assert reads == [schema, schema, schema]
  for forbidden in ("schema", "path", "validator", "accepted"):
    with pytest.raises(TypeError): module.validate_lock_header(legacy_manifest, schema_version=1, **{forbidden: True})


def test_import_and_base_constructor_do_not_read_schema_or_full_optional(tmp_path, monkeypatch):
  root = tmp_path / "supervisor"
  source = root / "src/agentcfg/pi_lock_header.py"
  source.parent.mkdir(parents=True)
  source.write_bytes(Path(header.__file__).read_bytes())
  spec = importlib.util.spec_from_file_location("agentcfg._cold_synthetic_lock_header", source)
  module = importlib.util.module_from_spec(spec)
  calls = []
  def forbidden(*args, **kwargs):
    calls.append("unexpected resource")
    raise AssertionError("import or constructor accessed resource")
  original = builtins.__import__
  def imports(name, *args, **kwargs):
    if any(part in name for part in ("durable", "origin", "wheel")): forbidden()
    if name == "pi_lock_header": forbidden()
    return original(name, *args, **kwargs)
  with monkeypatch.context() as cold:
    cold.setattr(Path, "read_text", forbidden)
    cold.setattr(builtins, "__import__", imports)
    spec.loader.exec_module(module)
    assert dependencies.PiBackend(profile="pi-base").profile == "pi-base"
  assert calls == []


def test_resource_domain_preserves_duplicate_schema_parser(tmp_path, legacy_manifest):
  module, schema = load_own_header(tmp_path)
  # 兼容现有json.loads last-key规则；不冒充新的strictorigin parser。
  schema.write_text('{"type":"array","type":"object"}')
  assert module.validate_lock_header(legacy_manifest, schema_version=1) is None
