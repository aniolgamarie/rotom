"""4.1：纯候选渲染；只使用虚构 adapter、临时资源及真实解析边界。"""

from copy import deepcopy
from dataclasses import replace
import importlib
import json
from pathlib import Path
import traceback

import pytest
import yaml

from agentcfg import config
from agentcfg.adapter import Artifact, ManagedTarget, Ownership
from agentcfg.merge import Provenance
from agentcfg.secrets import SecretStore
from test_config_resolution import ResolutionAdapter, resolution_inputs, resolve


SPECIAL = '中文 {{example}}\n"quotes" $() `backticks`\r\n'
PRIVATE = "https://private-render.example.invalid/private-model"


def rendering():
  assert importlib.util.find_spec("agentcfg.render") is not None, "deterministic rendering core missing"
  return importlib.import_module("agentcfg.render")


def test_concatenate_rules_preserves_order_bytes_and_explicit_separator():
  render = rendering()
  first = SPECIAL.encode("utf-8") + b"\xff"
  assert render.concatenate_rules((first, b"", b"last\r\n")) == first + b"\n\n\n\nlast\r\n"
  assert render.concatenate_rules(()) == b""
  assert render.concatenate_rules((first,)) == first
  assert render.concatenate_rules((b"b", b"a")) == b"b\n\na"


@pytest.mark.parametrize("format", ["json", "yaml"])
def test_serialize_structured_roundtrips_literals_and_is_canonical(format):
  render = rendering()
  data = {"z": [False, None, 2, 1.5, SPECIAL], "a": {"z": "!!js function() {}", "a": "yes"}}
  encoded = render.serialize_structured(data, format=format)
  assert encoded == render.serialize_structured({"a": {"a": "yes", "z": "!!js function() {}"}, "z": data["z"]}, format=format)
  assert encoded.endswith(b"\n") and not encoded.endswith(b"\n\n")
  assert "中文".encode() in encoded
  assert (json.loads(encoded) if format == "json" else yaml.safe_load(encoded)) == data
  assert encoded.index(b"a") < encoded.index(b"z")
  if format == "json":
    assert render.serialize_structured({"b": 2, "a": 1}, format=format) == b'{"a":1,"b":2}\n'
  else:
    assert render.serialize_structured({"b": 2, "a": 1}, format=format) == b"a: 1\nb: 2\n"


@pytest.mark.parametrize("value", [object(), SecretStore({"key": "synthetic-secret"}), {1: "value"},
                                    {"x": float("nan")}, {"x": float("inf")}, {"x": (1, 2)},
                                    {"x": b"secret"}, {"x": {1, 2}}])
def test_serialize_structured_rejects_objects_and_nonstandard_data(value):
  render = rendering()
  for format in ("json", "yaml"):
    with pytest.raises(render.RenderError):
      render.serialize_structured(value, format=format)


def test_serialize_structured_rejects_cycles_subclasses_and_unknown_codec():
  render = rendering()
  cyclic = []
  cyclic.append(cyclic)

  class PrivateString(str):
    def __str__(self):
      raise AssertionError(PRIVATE)

  for value in (cyclic, {"value": PrivateString(PRIVATE)}):
    with pytest.raises(render.RenderError):
      render.serialize_structured(value, format="json")
  with pytest.raises(render.RenderError):
    render.serialize_structured({}, format="cordis-js")
  with pytest.raises(render.RenderError):
    render.concatenate_rules(("not bytes",))


def test_render_text_reads_only_explicit_trusted_asset_and_preserves_values(tmp_path, sentinel_factory):
  render = rendering()
  assets = tmp_path / "trusted"
  assets.mkdir()
  (assets / "text.j2").write_bytes(b"{{ value }}\n\n")
  before = sentinel_factory(tmp_path)
  assert render.render_text(assets, "text.j2", {"value": SPECIAL}) == (SPECIAL + "\n\n").encode()
  before.assert_unchanged()


@pytest.mark.parametrize("template", ["{{ missing_private_id }}", "{{ value.__class__ }}",
                                       "{{ value.upper() }}", "{{ cycler('x') }}",
                                       "{{ values | random }}", "{% include 'outside' %}",
                                       "{% private_invalid %}"])
def test_render_text_redacts_failures_and_exposes_no_objects_or_functions(tmp_path, template):
  render = rendering()
  (tmp_path / "trusted.j2").write_text(template + PRIVATE)
  with pytest.raises(render.RenderError) as caught:
    render.render_text(tmp_path, "trusted.j2", {"value": PRIVATE, "values": [PRIVATE]})
  assert caught.value.__context__ is None and caught.value.__cause__ is None
  output = "".join(traceback.format_exception(caught.value))
  assert PRIVATE not in output and "missing_private_id" not in str(caught.value)


def test_render_text_rejects_nondata_context_and_asset_escape(tmp_path):
  render = rendering()
  assets = tmp_path / "assets"
  assets.mkdir()
  (assets / "text.j2").write_text("{{ value }}")
  outside = tmp_path / "outside.j2"
  outside.write_text(PRIVATE)
  (assets / "link.j2").symlink_to(outside)
  linked_root = tmp_path / "linked"
  linked_root.symlink_to(assets, target_is_directory=True)
  for root, name in ((assets, "../outside.j2"), (assets, str(outside)),
                     (assets, "link.j2"), (linked_root, "text.j2"),
                     (assets, "missing.j2")):
    with pytest.raises(render.RenderError) as caught:
      render.render_text(root, name, {})
    assert caught.value.__context__ is None
  for value in (SecretStore({"key": PRIVATE}), lambda: PRIVATE, Path(PRIVATE)):
    with pytest.raises(render.RenderError):
      render.render_text(assets, "text.j2", {"value": value})


def test_render_rules_uses_resolved_selection_and_only_explicit_templates(selected, tmp_path):
  render = rendering()
  catalog, local, _, _, _ = selected
  assets = tmp_path / "trusted-rules"
  (assets / "shared/rules").mkdir(parents=True)
  (assets / "shared/rules/one.md").write_bytes(SPECIAL.encode() + b"\xff")
  (assets / "explicit.j2").write_text("template: {{ value }}\n")
  catalog.registry["rules"]["two"] = {"path": "explicit.j2", "template": True}
  catalog.profiles["fixture-default"]["rules"] = ["two", "one"]
  resolved = resolve(catalog, local)
  ordered = tuple(resolved.data["rules"][key] for key in resolved.data["profile"]["rules"])
  assert render.render_rules(assets, ordered, {"value": SPECIAL}) == ("template: " + SPECIAL + "\n\n\n" + SPECIAL).encode() + b"\xff"
  assert render.render_rules(assets, (), {}) == b""
  for rule in ({"path": "explicit.j2", "extra": PRIVATE},
               {"path": "explicit.j2", "template": "false"},
               {"path": "../outside"}):
    with pytest.raises(render.RenderError):
      render.render_rules(assets, (rule,), {})


class RenderingAdapter(ResolutionAdapter):
  def __init__(self):
    self.rule_bytes = (SPECIAL.encode(), b"second\r\n")

  def managed_targets(self, data):
    return (ManagedTarget("native.json", Ownership.FILE, "json"),
            ManagedTarget("rules.md", Ownership.FILE, "text"),
            ManagedTarget("preferences.yaml", Ownership.FIELDS, "yaml", "/theme"),
            ManagedTarget("preferences.yaml", Ownership.INITIALIZE, "yaml", "/welcome"),
            ManagedTarget("session.json", Ownership.RUNTIME, "json"))

  def render(self, data):
    render = rendering()
    targets = self.managed_targets(data)
    provider = data["providers"]["public"]
    return (Artifact(targets[0], render.serialize_structured({"endpoint": provider["base_url"],
                      "caption": data["profile"]["agent_options"]["caption"]}, format="json")),
            Artifact(targets[1], render.concatenate_rules(self.rule_bytes)),
            Artifact(targets[2], render.serialize_structured("quiet", format="yaml")),
            Artifact(targets[3], render.serialize_structured(False, format="yaml")))


@pytest.fixture
def selected(tmp_path):
  catalog, local, _, paths = resolution_inputs(tmp_path)
  local.data["overrides"]["providers"] = {"public": {"base_url": PRIVATE}}
  return catalog, local, resolve(catalog, local), RenderingAdapter(), paths


def candidate(render, selected, **kwargs):
  catalog, _, resolved, adapter, _ = selected
  return render.render_candidate(resolved, adapter=adapter, adapter_schemas=catalog.adapter_schemas,
                                 lock_identity=kwargs.pop("lock_identity", "fixture-lock-v1"), **kwargs)


def test_render_candidate_integrates_resolved_config_artifacts_without_io(selected, sentinel_factory, isolated_environment, capsys):
  render = rendering()
  before = sentinel_factory(isolated_environment.root)
  data = deepcopy(selected[2].data)
  first = candidate(render, selected)
  second = candidate(render, selected)
  before.assert_unchanged()
  assert first == second and selected[2].data == data
  assert len(first.generation) == 64
  assert [artifact.target.path for artifact in first.artifacts] == ["native.json", "preferences.yaml", "preferences.yaml", "rules.md"]
  assert all(artifact.mode == 0o600 for artifact in first.artifacts)
  assert json.loads(first.artifacts[0].content)["endpoint"] == PRIVATE
  assert first.artifacts[-1].content == SPECIAL.encode() + b"\n\nsecond\r\n"
  assert PRIVATE not in repr(first) + repr(first.artifacts)
  assert capsys.readouterr() == ("", "")


def test_render_candidate_generation_ignores_provenance_mapping_order_unselected_and_secret_rotation(selected, monkeypatch):
  render = rendering()
  catalog, local, resolved, adapter, paths = selected
  first = candidate(render, selected)
  reordered = replace(resolved, data=dict(reversed(list(resolved.data.items()))),
                      provenance=Provenance({("private-source",): PRIVATE}), validated_profiles=123)
  assert candidate(render, (catalog, local, reordered, adapter, paths)) == first
  catalog.registry["providers"]["unused"]["base_url"] = "https://changed.example.invalid"
  assert candidate(render, (catalog, local, resolve(catalog, local), adapter, paths)) == first

  def forbidden(*args, **kwargs):
    raise AssertionError("secret resolution forbidden")

  monkeypatch.setattr(SecretStore, "resolve", forbidden)
  rotations = []
  for secret in ("", 'synthetic-secret-"\n$() `rotation-one`', "synthetic-secret-rotation-two"):
    # 同一本地文件被实际改写、加载及解析；不是冻结的 resolved 对象比较。
    ordinary = paths["local"].read_text().split("[secrets]")[0]
    paths["local"].write_text(ordinary + "[secrets]\nnot-filled = " + json.dumps(secret) + "\n")
    loaded, store = config.load_local(paths["local"], adapter_schemas=catalog.adapter_schemas)
    loaded.data["overrides"]["providers"] = deepcopy(local.data["overrides"]["providers"])
    current = candidate(render, (catalog, loaded, resolve(catalog, loaded), adapter, paths))
    rotations.append(current)
    assert all(not secret or secret.encode() not in artifact.content for artifact in current.artifacts)
  assert rotations == [first, first, first]


def test_render_candidate_private_preimage_excludes_source_metadata_and_secret_values(selected, monkeypatch):
  render = rendering()
  canonical = render._json
  captured = []

  def observe(data):
    encoded = canonical(data)
    captured.append(encoded)
    return encoded

  monkeypatch.setattr(render, "_json", observe)
  result = candidate(render, selected)
  preimage = json.loads(captured[-1])
  assert set(preimage) == {"render_version", "config", "lock_identity", "adapter", "targets", "artifacts"}
  assert preimage["config"] == selected[2].data
  assert PRIVATE in captured[-1].decode()
  assert all(name not in preimage for name in ("provenance", "secrets", "validated_profiles", "local", "time"))
  assert PRIVATE not in repr(result)


def test_render_candidate_rejects_declaration_string_subclasses(selected):
  render = rendering()

  class PrivateString(str):
    pass

  selected[3].declaration = replace(selected[3].declaration, adapter_version=PrivateString("mapping-v1"))
  with pytest.raises(render.RenderError):
    candidate(render, selected)


def test_render_candidate_generation_tracks_nonsecret_input_lock_version_paths_and_resources(selected):
  render = rendering()
  catalog, local, resolved, adapter, paths = selected
  first = candidate(render, selected)
  assert candidate(render, selected, lock_identity="fixture-lock-v2").generation != first.generation
  changes = [(("providers", "public", "base_url"), "https://changed.example.invalid"),
             (("providers", "public", "credential_ref"), "secret:rotated-reference"),
             (("machine", "paths", "cache_root"), str(paths["local"].parent / "other-cache")),
             (("profile", "rules"), [])]
  for location, value in changes:
    data = deepcopy(resolved.data)
    parent = data
    for key in location[:-1]:
      parent = parent[key]
    parent[location[-1]] = value
    if location == ("profile", "rules"):
      data["rules"] = {}
    changed = candidate(render, (catalog, local, replace(resolved, data=data), adapter, paths))
    assert changed.generation != first.generation
  adapter.rule_bytes = (b"changed trusted rule",)
  assert candidate(render, selected).generation != first.generation
  adapter.rule_bytes = (SPECIAL.encode(), b"second\r\n")
  adapter.declaration = replace(adapter.declaration, adapter_version="mapping-v2")
  bundle = catalog.adapter_schemas.bundles["fixture-json"]
  catalog.adapter_schemas.bundles["fixture-json"] = replace(bundle, declaration=adapter.declaration)
  assert candidate(render, selected).generation != first.generation


def test_render_candidate_revalidates_mutable_input_and_rejects_secret_channels(selected):
  render = rendering()
  catalog, local, resolved, adapter, paths = selected
  mutations = [(("secrets",), {"key": PRIVATE}), (("extra",), PRIVATE),
               (("providers", "public", "api_key"), PRIVATE),
               (("providers", "public", "base_url"), "https://user:password@example.invalid"),
               (("profile", "agent_options", "extra"), PRIVATE),
               (("profile", "agent_options", "caption"), SecretStore({"key": PRIVATE})),
               (("machine", "environment", "values"), {"API_KEY": PRIVATE}),
               (("machine", "paths", "cache_root"), "~/not-yet-resolved"),
               (("models", "secondary", "provider"), "unknown-private-id"),
               (("profile", "rules"), []),
               (("adapter_documents", "bindings", "extra"), PRIVATE),
               (("plugins", "optional", "extra"), PRIVATE)]
  for location, value in mutations:
    data = deepcopy(resolved.data)
    parent = data
    for key in location[:-1]:
      parent = parent[key]
    parent[location[-1]] = value
    with pytest.raises(render.RenderError) as caught:
      candidate(render, (catalog, local, replace(resolved, data=data), adapter, paths))
    assert PRIVATE not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
  for invalid in (resolved.data, SecretStore({"key": PRIVATE}), object()):
    with pytest.raises(render.RenderError):
      candidate(render, (catalog, local, invalid, adapter, paths))
  for identity in ("", object(), SecretStore({"key": PRIVATE})):
    with pytest.raises(render.RenderError):
      candidate(render, selected, lock_identity=identity)


def test_render_candidate_validates_declarations_and_detaches_adapter_aliases(selected, monkeypatch):
  render = rendering()
  adapter = selected[3]
  original = adapter.render(selected[2].data)
  monkeypatch.setattr(adapter, "render", lambda data: tuple(reversed(original)))
  first = candidate(render, selected)
  object.__setattr__(original[0].target, "path", "mutated.json")
  assert first.artifacts[0].target.path == "native.json"
  object.__setattr__(original[0].target, "path", "native.json")
  bad_cases = [(original[0], original[0]),
               (Artifact(ManagedTarget("undeclared.json", Ownership.FILE, "json"), b"{}"),),
               [original[0]]]
  for attribute, value in (("mode", 0o644), ("content", PRIVATE), ("content", bytearray(b"x"))):
    forged = Artifact(original[0].target, b"{}")
    object.__setattr__(forged, attribute, value)
    bad_cases.append((forged,))
  forged_target = ManagedTarget("safe.json", Ownership.FILE, "json")
  object.__setattr__(forged_target, "path", "../private-escape")
  bad_cases.append((Artifact(forged_target, b"{}"),))
  for artifacts in bad_cases:
    monkeypatch.setattr(adapter, "render", lambda data: artifacts)
    with pytest.raises(render.RenderError) as caught:
      candidate(render, selected)
    assert caught.value.__context__ is None


def test_render_candidate_rejects_overlapping_targets_and_redacts_adapter_errors(selected, monkeypatch):
  render = rendering()
  adapter = selected[3]
  cases = [
    (ManagedTarget("a", Ownership.FILE, "text"), ManagedTarget("a/b", Ownership.FILE, "text")),
    (ManagedTarget("a", Ownership.FILE, "text"), ManagedTarget("a", Ownership.FIELDS, "json", "/x")),
    (ManagedTarget("a", Ownership.FIELDS, "json", "/x"), ManagedTarget("a", Ownership.INITIALIZE, "json", "/x")),
    (ManagedTarget("a", Ownership.FIELDS, "json", "/x"), ManagedTarget("a", Ownership.FIELDS, "yaml", "/y")),
  ]
  for targets in cases:
    monkeypatch.setattr(adapter, "managed_targets", lambda data: targets)
    monkeypatch.setattr(adapter, "render", lambda data: ())
    with pytest.raises(render.RenderError):
      candidate(render, selected)

  def fail(data):
    raise ValueError(PRIVATE)

  monkeypatch.setattr(adapter, "validate", fail)
  with pytest.raises(render.RenderError) as caught:
    candidate(render, selected)
  assert PRIVATE not in "".join(traceback.format_exception(caught.value))
  assert caught.value.__cause__ is None and caught.value.__context__ is None
