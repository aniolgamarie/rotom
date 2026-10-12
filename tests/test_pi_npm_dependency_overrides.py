"""自有 npm overrides 默认边界；所有工具命令均 fake，不运行 npm/Node。"""
import json
from copy import deepcopy

import pytest

from agentcfg import pi_vendor as vendor
from agentcfg.pi_dependencies import PiBackend
from agentcfg.schema import ConfigError
from test_pi_dependencies import payload, fixture_repository
from test_pi_lock_families import generator_fixture
from test_pi_npm_seed import synthetic, reject, DRIFT

INVALID = "pi-build-dependency-overrides-invalid"


def helper():
  from agentcfg.pi_npm_seed import validate_dependency_overrides
  return validate_dependency_overrides


def selected():
  return {"parent": {"kind": "npm", "package": "@fixture/parent", "version": "1.0.2"}}


def valid():
  return {"@fixture/parent@1.0.2": {"https-proxy-agent@9.1.0": "9.0.0"}}


def configured(tmp_path, monkeypatch):
  workspace, inputs, path, calls, package, seed, raw, ref = synthetic(tmp_path, monkeypatch)
  source = inputs["sources"]["pi-host"]
  overrides = {source["package"] + "@" + source["version"]: {"transitive-proxy@9.1.0": "9.0.0"}}
  inputs["profiles"]["pi-base"]["npm_dependency_overrides"] = overrides
  path.write_bytes(payload(inputs))
  return workspace, inputs, path, calls, package, seed, raw, overrides


def test_seeded_overrides_reach_original_stage_and_public_candidate_readback(tmp_path, monkeypatch):
  workspace, inputs, path, calls, package, seed, raw, overrides = configured(tmp_path, monkeypatch)
  observed = []
  def checked(argv, *, cwd, env):
    calls.append(argv)
    if argv == ["node", "--version"]: return inputs["toolchains"]["node"]
    if argv == ["npm", "--version"]: return inputs["toolchains"]["npm"]
    assert argv == ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"]
    assert json.loads((cwd / "package.json").read_bytes()) == {**package, "overrides": overrides}
    assert (cwd / "package-lock.json").read_bytes() == raw
    observed.append(True)
    return ""
  monkeypatch.setattr(vendor, "checked", checked)
  lock = PiBackend(profile="pi-base").resolve_lock(workspace.repository)
  assert observed == [True] and len(calls) == 3
  assert lock.validated_bindings["pi-base"].state == "candidate"
  assert "npm_dependency_overrides" not in lock.metadata["profile_slices"]["pi-base"]
  assert json.loads(lock.pairs["pi-base"][0])["overrides"] == overrides


@pytest.mark.parametrize("fault", ["missing-seed", "empty", "empty-child", "parent", "parent-version", "direct", "bare-child", "range", "alias", "url", "file", "git", "dollar", "nested", "dot", "bool"])
def test_invalid_input_preserves_manifest_before_temp_or_checked(tmp_path, monkeypatch, fault):
  workspace, inputs, path, calls, package, seed, raw, overrides = configured(tmp_path, monkeypatch)
  profile = inputs["profiles"]["pi-base"]; parent = next(iter(overrides))
  if fault == "missing-seed": profile.pop("npm_resolution_seed")
  elif fault == "empty": profile["npm_dependency_overrides"] = {}
  elif fault == "empty-child": overrides[parent] = {}
  elif fault == "parent": profile["npm_dependency_overrides"] = {"unselected@1.0.0": overrides[parent]}
  elif fault == "parent-version": profile["npm_dependency_overrides"] = {parent.rsplit("@", 1)[0] + "@2.0.0": overrides[parent]}
  elif fault == "direct": overrides[parent] = {parent: "2.0.0"}
  elif fault == "bare-child": overrides[parent] = {"proxy": "9.0.0"}
  elif fault == "dot": overrides[parent] = {".": "9.0.0"}
  elif fault == "bool": profile["npm_dependency_overrides"] = True
  else: overrides[parent]["transitive-proxy@9.1.0"] = {"range": "^9.0.0", "alias": "npm:proxy@9.0.0", "url": "https://example.invalid/x", "file": "file:../x", "git": "git+https://example.invalid/x", "dollar": "$proxy", "nested": {"proxy": "9.0.0"}}[fault]
  path.write_bytes(payload(inputs)); root = workspace.repository
  before = (root / "locks/pi-modern/manifest.json").read_bytes()
  monkeypatch.setattr(vendor.tempfile, "TemporaryDirectory", lambda *a, **k: pytest.fail("must fail before temp"))
  reject(lambda: PiBackend(profile="pi-base").resolve_lock(root), code=INVALID)
  assert calls == [] and (root / "locks/pi-modern/manifest.json").read_bytes() == before


@pytest.mark.parametrize("version", ["0.0.0", "9.0.0", "1.2.3-0", "1.2.3-alpha.0", "1.2.3-x-01", "1.2.3+000", "1.2.3-rc.1+build.002"])
def test_exact_semver_positive_and_detached(version):
  value = valid(); value["@fixture/parent@1.0.2"] = {"@fixture/proxy@" + version: version}
  output = helper()(value, selected())
  assert output == value and output is not value
  output["@fixture/parent@1.0.2"].clear()
  assert value["@fixture/parent@1.0.2"]


@pytest.mark.parametrize("version", ["01.2.3", "1.02.3", "1.2.03", "1.2.3-00", "1.2.3-alpha.01", "1.2", "v1.2.3", "1.2.3-", "1.2.3+", "1.2.3-a..b", "1.2.3-ü", "1.2.3\x00", "1.2.3\ud800", "1.2.3" + "a" * 124])
@pytest.mark.parametrize("position", ["child", "replacement"])
def test_invalid_semver_numeric_and_text_domains(version, position):
  value = valid()
  value["@fixture/parent@1.0.2"] = {"proxy@" + (version if position == "child" else "9.1.0"): version if position == "replacement" else "9.0.0"}
  reject(helper(), value, selected(), code=INVALID)


@pytest.mark.parametrize("kind", ["npm", "local", "git"])
def test_direct_selected_packages_cannot_be_replaced(kind):
  sources = selected(); sources["direct"] = {"kind": kind, "package": "@fixture/direct", "version": "3.0.0"}
  value = {"@fixture/parent@1.0.2": {"@fixture/direct@3.0.0": "2.0.0"}}
  reject(helper(), value, sources, code=INVALID)


@pytest.mark.parametrize("over", [False, True])
def test_parent_child_package_and_version_exact_limits(over):
  sources = {str(i): {"kind": "npm", "package": "parent" + str(i), "version": "1.0.0"} for i in range(16 + int(over))}
  value = {row["package"] + "@1.0.0": {"proxy@9.1.0": "9.0.0"} for row in sources.values()}
  if over: reject(helper(), value, sources, code=INVALID)
  else: assert helper()(value, sources) == value
  children = {"proxy" + str(i) + "@9.1.0": "9.0.0" for i in range(32 + int(over))}
  value = {"@fixture/parent@1.0.2": children}
  if over: reject(helper(), value, selected(), code=INVALID)
  else: assert helper()(value, selected()) == value
  package = "p" * (214 + int(over)); version = "1.2.3+" + "0" * (122 + int(over))
  for child, replacement in ((package + "@9.1.0", "9.0.0"), ("proxy@9.1.0", version)):
    value = {"@fixture/parent@1.0.2": {child: replacement}}
    if over: reject(helper(), value, selected(), code=INVALID)
    else: assert helper()(value, selected()) == value


def test_child_budget_is_aggregate_across_parents():
  sources = selected(); sources["second"] = {"kind": "npm", "package": "second", "version": "1.0.0"}
  children = {"proxy" + str(i) + "@9.1.0": "9.0.0" for i in range(16)}
  value = {"@fixture/parent@1.0.2": children, "second@1.0.0": deepcopy(children)}
  assert helper()(value, sources) == value
  value["second@1.0.0"]["extra@9.1.0"] = "9.0.0"
  reject(helper(), value, sources, code=INVALID)


@pytest.mark.parametrize("fault", ["map", "key", "children", "child-key", "replacement", "source-key"])
def test_foreign_types_never_receive_callbacks(fault):
  events = []
  class Foreign(str):
    def __hash__(self): events.append("hash"); return str.__hash__(self)
    def __eq__(self, other): events.append("eq"); return str.__eq__(self, other)
    def __str__(self): events.append("str"); return str.__str__(self)
    def __len__(self): events.append("len"); return str.__len__(self)
  class ForeignMap(dict):
    def items(self): events.append("items"); return super().items()
    def __len__(self): events.append("map-len"); return super().__len__()
  value = valid(); sources = selected(); parent = next(iter(value))
  if fault == "map": value = ForeignMap(value)
  elif fault == "key": value = {Foreign(parent): value[parent]}
  elif fault == "children": value[parent] = ForeignMap(value[parent])
  elif fault == "child-key": value[parent] = {Foreign("proxy@9.1.0"): "9.0.0"}
  elif fault == "replacement": value[parent] = {"proxy@9.1.0": Foreign("9.0.0")}
  else: sources = {Foreign("parent"): sources["parent"]}
  events.clear()
  reject(helper(), value, sources, code=INVALID)
  assert events == []


def test_control_exception_propagates_original_object(monkeypatch):
  from agentcfg import pi_npm_seed
  control = KeyboardInterrupt("synthetic control")
  def fail(*args): raise control
  monkeypatch.setattr(pi_npm_seed, "_dependency_overrides", fail)
  with pytest.raises(KeyboardInterrupt) as caught: helper()(valid(), selected())
  assert caught.value is control


@pytest.mark.parametrize("field", ["path", "name", "version", "resolved", "integrity", "optional", "os", "cpu", "libc"])
def test_overrides_preserve_original_nine_identity_drift_gate(tmp_path, monkeypatch, field):
  import base64
  workspace, inputs, path, calls, package, seed, raw, overrides = configured(tmp_path, monkeypatch)
  changed = deepcopy(seed); key = next(key for key in changed["packages"] if key and "synthetic-host" in key)
  if field == "path": changed["packages"]["node_modules/moved-host"] = changed["packages"].pop(key)
  else: changed["packages"][key][field] = {"name":"different", "version":"2.0.0", "resolved":"https://example.invalid/drift.tgz", "integrity":"sha512-" + base64.b64encode(b"x" * 64).decode(), "optional":True, "os":["darwin"], "cpu":["arm64"], "libc":["musl"]}[field]
  root = workspace.repository; before = (root / "locks/pi-modern/manifest.json").read_bytes()
  def checked(argv, *, cwd, env):
    calls.append(argv)
    if argv == ["node", "--version"]: return inputs["toolchains"]["node"]
    if argv == ["npm", "--version"]: return inputs["toolchains"]["npm"]
    assert json.loads((cwd / "package.json").read_bytes())["overrides"] == overrides
    (cwd / "package-lock.json").write_bytes(payload(changed)); return ""
  monkeypatch.setattr(vendor, "checked", checked)
  reject(lambda: PiBackend(profile="pi-base").resolve_lock(root), code=DRIFT)
  assert len(calls) == 3 and (root / "locks/pi-modern/manifest.json").read_bytes() == before


@pytest.mark.parametrize("seeded", [False, True])
def test_modern_without_overrides_does_not_use_new_validator(tmp_path, monkeypatch, seeded):
  if seeded:
    workspace, inputs, path, calls, package, seed, raw, ref = synthetic(tmp_path, monkeypatch)
  else: workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch)
  monkeypatch.setattr("agentcfg.pi_npm_seed.validate_dependency_overrides", lambda *args: pytest.fail("unselected optional validator"))
  lock = PiBackend(profile="pi-base").resolve_lock(workspace.repository)
  assert len(calls) == 3 and "overrides" not in json.loads(lock.pairs["pi-base"][0])


def test_legacy_rejects_overrides_at_original_unknown_field_gate(tmp_path, monkeypatch):
  root, manifest = fixture_repository(tmp_path); build = root / "agents/pi/build"; build.mkdir()
  (build / "recipes.json").write_bytes(payload({"schema_version":1,"sources":{}}))
  source = manifest["sources"]["host"]
  inputs = {"schema_version":1,"toolchains":manifest["toolchains"],"platforms":manifest["platforms"],"sources":{"host":{key:source[key] for key in ("kind","package","version","license_files")}},"profiles":{"pi-fixture":{"engine":"node","source_ids":["host"],"entrypoint":"node_modules/synthetic-host/index.js","npm_dependency_overrides":valid()}},"build_steps":[]}
  inputs["sources"]["host"]["resources"] = {key:[] for key in ("extensions","skills","prompts","themes")}
  (root / "agents/pi/dependencies.json").write_bytes(payload(inputs)); calls = []
  monkeypatch.setattr(vendor, "checked", lambda *a, **k: calls.append(a))
  monkeypatch.setattr("agentcfg.pi_npm_seed.validate_dependency_overrides", lambda *args: pytest.fail("legacy optional import/call"))
  with pytest.raises(ConfigError, match="pi-build-profile-invalid"): vendor.read_inputs(root)
  assert calls == []
