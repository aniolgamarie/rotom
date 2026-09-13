"""CFG-01/02/04/06：真实离线解析到测试专用 JSON adapter。"""

from copy import deepcopy
from dataclasses import replace
import importlib
import json
import traceback

import pytest

from agentcfg import config, schema
from agentcfg.adapter import Adapter, AdapterDeclaration, Artifact, DependencyPlan, ManagedTarget, Ownership


PRIVATE = "private-canary-id"


def resolver():
  assert hasattr(config, "resolve_config"), "executable resolver missing"
  return config.resolve_config


def merge_api():
  assert importlib.util.find_spec("agentcfg.merge") is not None, "merge API missing"
  return importlib.import_module("agentcfg.merge")


def closed(properties, required=()):
  return {"type": "object", "additionalProperties": False,
          "properties": properties, "required": list(required)}


class ResolutionAdapter(Adapter):
  declaration = AdapterDeclaration("fixture-json", 2, "mapping-v1")

  def validate(self, data):
    profile = data["profile"]
    routes = data["adapter_documents"]["bindings"]["roles"]
    if set(profile["roles"]) - set(routes):
      raise ValueError(PRIVATE)
    for provider in data["providers"].values():
      if provider["protocol"] != "fixture-http" or provider["auth_kind"] != "api-key":
        raise ValueError(PRIVATE)
    if any(model["input"] != ["text"] for model in data["models"].values()):
      raise ValueError(PRIVATE)
    if any(server["transport"] != "stdio" or "command" not in server
           for server in data["mcp"].values()):
      raise ValueError(PRIVATE)
    if any(plugin["package"] != "fixture-package" for plugin in data["plugins"].values()):
      raise ValueError(PRIVATE)

  def render(self, data):
    self.validate(data)
    model = data["models"][data["profile"]["roles"]["main"]]
    provider = data["providers"][model["provider"]]
    native = {"endpoint": provider["base_url"], "model": model["remote_id"],
              "images": data["profile"]["agent_options"]["terminal_images"]}
    return (Artifact(self.managed_targets(data)[0], json.dumps(native, sort_keys=True).encode()),)

  def managed_targets(self, data):
    return (ManagedTarget("native.json", Ownership.FILE, "json"),)

  def dependency_plan(self, data):
    return DependencyPlan(("fixture-runtime@1",))

  def launch_spec(self, data, **kwargs):
    raise AssertionError("offline resolution must not launch")

  def capture(self, projection):
    return {}

  def doctor(self, projection):
    return ()


def resolution_inputs(tmp_path):
  # 框架 TOML 与 adapter 自有文档均经过真正 loader，不使用元数据假 catalog。
  assert hasattr(schema, "AdapterPolicy"), "normalized adapter policy missing"
  adapter = ResolutionAdapter()
  options = closed({"terminal_images": {"type": "boolean"}, "caption": {"type": "string"}},
                   ("terminal_images",))
  selection = {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
  defaults = closed({"providers": selection, "models": selection, "mcp": selection,
                     "agent_options": deepcopy(options)})
  documents = {
    "agent": closed({"schema_version": {"type": "integer", "const": 2}, "defaults": defaults},
                    ("schema_version", "defaults")),
    "bindings": closed({"schema_version": {"type": "integer", "const": 2},
                        "roles": {"type": "object", "additionalProperties": {"type": "string"}},
                        "owner": {"type": "string"}}, ("schema_version", "roles", "owner")),
    "plugins": closed({"schema_version": {"type": "integer", "const": 2},
                       "packages": {"type": "object", "additionalProperties": closed({
                         "package": {"type": "string"}}, ("package",))}},
                      ("schema_version", "packages")),
  }

  def validate(kind, data):
    if kind == "resolved":
      adapter.validate(data)
    elif kind == "bindings" and any(value != "native-model" for value in data["roles"].values()):
      raise ValueError(PRIVATE)

  def policy(documents):
    return schema.AdapterPolicy(defaults=documents["agent"]["defaults"],
                                plugins=documents["plugins"]["packages"],
                                credential_targets=frozenset({"FIXTURE_KEY"}))

  def claims(data):
    return tuple(schema.AuthenticationClaim(provider, data["adapter_documents"]["bindings"]["owner"])
                 for provider in data["providers"])

  bundle = schema.AdapterSchemaBundle(adapter.declaration, documents, options, validate,
                                      policy=policy, authentication_claims=claims)
  context = schema.AdapterSchemas({"fixture-json": bundle})
  contents = {
    "registry": '''schema_version = 1
[providers.public]
protocol = "fixture-http"
base_url = "https://example.invalid/v1"
auth_kind = "api-key"
credential_ref = "secret:not-filled"
[providers.unused]
protocol = "fixture-http"
base_url = "https://example.invalid/unused"
auth_kind = "api-key"
[models.primary]
provider = "public"
remote_id = "fictional-chat"
input = ["text"]
[models.secondary]
provider = "public"
remote_id = "fictional-small"
input = ["text"]
[mcp.first]
transport = "stdio"
command = "fictional-mcp"
[mcp.second]
transport = "stdio"
command = "fictional-mcp-two"
[rules.one]
path = "shared/rules/one.md"
[skills.one]
path = "shared/skills/one"
''',
    "profile": '''schema_version = 1
id = "fixture-default"
agent = "fixture-json"
models = ["primary", "secondary"]
rules = ["one"]
skills = ["one"]
plugins = ["optional"]
[roles]
main = "primary"
small = "secondary"
[agent_options]
terminal_images = true
caption = "profile"
''',
    "agent": '''schema_version = 2
[defaults]
providers = ["public"]
models = ["primary"]
mcp = ["first", "second"]
[defaults.agent_options]
terminal_images = true
caption = "default"
''',
    "bindings": '''schema_version = 2
owner = "fixture-auth"
[roles]
main = "native-model"
small = "native-model"
''',
    "plugins": '''schema_version = 2
[packages.optional]
package = "fixture-package"
''',
    "local": '''schema_version = 1
[machine]
id = "private-machine"
default_profile = "fixture-default"
[overrides.profiles.fixture-default]
mcp = []
[overrides.profiles.fixture-default.roles]
main = "secondary"
[overrides.profiles.fixture-default.agent_options]
terminal_images = false
caption = ""
[secrets]
not-filled = ""
''',
  }
  paths = {}
  for kind, text in contents.items():
    paths[kind] = tmp_path / (kind + ".toml")
    paths[kind].write_text(text)
  source = config.SourceInputs((paths["registry"],), (paths["profile"],), {
    "fixture-json": config.AdapterSources(*(paths[key] for key in ("agent", "bindings", "plugins")))})
  catalog = config.load_sources(source, adapter_schemas=context)
  local, store = config.load_local(paths["local"], adapter_schemas=catalog.adapter_schemas)
  return catalog, local, adapter, paths


def resolve(catalog, local, **kwargs):
  return resolver()(catalog, local, adapter_schemas=catalog.adapter_schemas, **kwargs)


def test_merge_layers_replaces_arrays_preserves_missing_false_empty_and_sources():
  merge = merge_api()
  layers = [("registry", {"roles": {"main": "a", "small": "b"}, "mcp": ["one", "two"]}),
            ("defaults", {"images": True, "caption": "default"}),
            ("profile", {"mcp": ["two", "one"]}),
            ("local", {"roles": {"main": "c"}, "mcp": [], "images": False,
                       "caption": "", "absent": merge.MISSING, "empty": {}})]
  before = deepcopy(layers)
  result = merge.merge_layers(layers)
  assert result.data == {"roles": {"main": "c", "small": "b"}, "mcp": [], "images": False,
                         "caption": "", "empty": {}}
  assert result.provenance[("roles", "main")] == "local"
  assert result.provenance[("roles", "small")] == "registry"
  assert result.provenance[("mcp",)] == "local"
  assert result.provenance[("empty",)] == "local"
  assert deepcopy(merge.MISSING) is merge.MISSING
  result.data["roles"]["main"] = "mutated"
  assert layers == before
  assert "main" not in repr(result) + repr(result.provenance)


def test_merge_replacement_discards_stale_provenance():
  merge = merge_api()
  result = merge.merge_layers([("registry", {"x": {"old": 1}, "y": "old"}),
                               ("local", {"x": [], "y": {"new": 2}})])
  assert dict(result.provenance) == {("x",): "local", ("y", "new"): "local"}
  ordered = merge.merge_layers([("defaults", {"a": [1, 2]}), ("profile", {"a": [2, 1]})])
  assert ordered.data == {"a": [2, 1]}


def test_resolve_selected_only_immutable_inputs_provenance_and_nonsecret_render(tmp_path, sentinel_factory):
  catalog, local, adapter, paths = resolution_inputs(tmp_path)
  before = deepcopy((catalog.registry, catalog.profiles, catalog.adapter_documents, local.data))
  sentinel = sentinel_factory(tmp_path)
  result = resolve(catalog, local)
  assert result.validated_profiles == 1
  assert result.data["profile"]["roles"] == {"main": "secondary", "small": "secondary"}
  assert result.data["profile"]["agent_options"] == {"terminal_images": False, "caption": ""}
  assert list(result.data["providers"]) == ["public"]
  assert list(result.data["models"]) == ["primary", "secondary"]
  assert result.data["mcp"] == {}
  assert list(result.data["plugins"]) == ["optional"]
  assert result.provenance[("profile", "mcp")] == "local"
  assert result.provenance[("profile", "providers")] == "defaults"
  assert result.provenance[("models", "primary", "remote_id")] == "registry"
  assert "provenance" not in result.data and "secrets" not in result.data
  assert json.loads(adapter.render(result.data)[0].content) == {
    "endpoint": "https://example.invalid/v1", "model": "fictional-small", "images": False}
  assert before == (catalog.registry, catalog.profiles, catalog.adapter_documents, local.data)
  sentinel.assert_unchanged()
  diagnostics = repr(config.public_diagnostics(result))
  for private in ("public", "primary", "secondary", "private-machine", "fixture-default", "example.invalid"):
    assert private not in diagnostics + repr(result) + repr(result.provenance)


@pytest.mark.parametrize("profile_id", [None, "fixture-default"])
def test_present_unknown_default_profile_rejected_even_with_explicit_selection(tmp_path, profile_id):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  local.data["machine"]["default_profile"] = PRIVATE
  before = deepcopy((catalog.registry, catalog.profiles, catalog.adapter_documents, local.data))
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local, profile_id=profile_id)
  assert caught.value.code == "reference"
  assert caught.value.path == ("machine", "default_profile")
  assert PRIVATE not in "".join(traceback.format_exception(caught.value))
  assert before == (catalog.registry, catalog.profiles, catalog.adapter_documents, local.data)


def test_missing_default_profile_preserves_explicit_selection_and_missing_only_fallback(tmp_path):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  del local.data["machine"]["default_profile"]
  assert resolve(catalog, local, profile_id="fixture-default").data["profile"]["id"] == "fixture-default"
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local)
  assert caught.value.code == "reference"
  assert caught.value.path == ("profile",)
  catalog.profiles["dsh-default"] = deepcopy(catalog.profiles["fixture-default"])
  catalog.profiles["dsh-default"]["id"] = "dsh-default"
  assert resolve(catalog, local).data["profile"]["id"] == "dsh-default"
  local.data["machine"]["default_profile"] = "fixture-default"
  assert resolve(catalog, local).data["profile"]["id"] == "fixture-default"
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local, profile_id=PRIVATE)
  assert caught.value.code == "reference"
  assert caught.value.path == ("profile",)
  assert PRIVATE not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("empty_catalog", [False, True])
@pytest.mark.parametrize("selection_layer", ["defaults", "profile", "local"])
def test_empty_selected_map_provenance_comes_from_selection_without_mutation(tmp_path, empty_catalog, selection_layer):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  if empty_catalog:
    catalog.registry["mcp"].clear()
  if selection_layer != "local":
    del local.data["overrides"]["profiles"]["fixture-default"]["mcp"]
    if selection_layer == "profile":
      catalog.profiles["fixture-default"]["mcp"] = []
    else:
      catalog.adapter_documents["fixture-json"]["agent"]["defaults"]["mcp"] = []
  before = deepcopy((catalog.registry, catalog.profiles, catalog.adapter_documents, local.data))
  result = resolve(catalog, local)
  assert result.data["mcp"] == {}
  assert result.provenance[("mcp",)] == selection_layer
  assert result.provenance[("profile", "mcp")] == selection_layer
  assert before == (catalog.registry, catalog.profiles, catalog.adapter_documents, local.data)


def test_profile_options_inherit_tool_defaults_through_actual_source_loader(tmp_path):
  catalog, local, _, paths = resolution_inputs(tmp_path)
  paths["profile"].write_text(paths["profile"].read_text().replace("terminal_images = true\n", ""))
  sources = config.SourceInputs((paths["registry"],), (paths["profile"],), {
    "fixture-json": config.AdapterSources(*(paths[key] for key in ("agent", "bindings", "plugins")))})
  loaded = config.load_sources(sources, adapter_schemas=catalog.adapter_schemas)
  local.data["overrides"]["profiles"]["fixture-default"].pop("agent_options")
  result = resolve(loaded, local)
  assert result.data["profile"]["agent_options"] == {"terminal_images": True, "caption": "profile"}
  assert result.provenance[("profile", "agent_options", "terminal_images")] == "defaults"


def test_partial_profile_loading_cannot_skip_final_completeness(tmp_path):
  catalog, local, _, paths = resolution_inputs(tmp_path)
  paths["profile"].write_text(paths["profile"].read_text().replace("terminal_images = true\n", ""))
  sources = config.SourceInputs((paths["registry"],), (paths["profile"],), {
    "fixture-json": config.AdapterSources(*(paths[key] for key in ("agent", "bindings", "plugins")))})
  loaded = config.load_sources(sources, adapter_schemas=catalog.adapter_schemas)
  local.data["overrides"]["profiles"]["fixture-default"].pop("agent_options")
  bundle = loaded.adapter_schemas.bundles["fixture-json"]
  loaded.adapter_schemas.bundles["fixture-json"] = replace(bundle, policy=lambda docs: schema.AdapterPolicy(
    defaults={"providers": ["public"]}, plugins=docs["plugins"]["packages"]))
  with pytest.raises(schema.ConfigError):
    schema.validate_document("profile", loaded.profiles["fixture-default"], adapter_schemas=loaded.adapter_schemas)
  with pytest.raises(schema.ConfigError) as caught:
    resolve(loaded, local)
  assert caught.value.code == "schema"


@pytest.mark.parametrize("change", [{"schema_version": 2}, {PRIVATE: True}, {"agent_options": {PRIVATE: True}}])
def test_partial_profile_options_do_not_weaken_source_envelope_or_unknown_fields(tmp_path, change):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  source = deepcopy(catalog.profiles["fixture-default"])
  source.update(change)
  with pytest.raises(schema.ConfigError):
    schema.validate_document("profile", source, adapter_schemas=catalog.adapter_schemas, partial_options=True)


def test_private_additions_and_inherited_partial_entities(tmp_path):
  catalog, local, adapter, paths = resolution_inputs(tmp_path)
  local.data["overrides"].update({
    "providers": {"public": {"base_url": "https://private.example.invalid"},
                  PRIVATE: {"protocol": "fixture-http", "base_url": "https://new.example.invalid",
                            "auth_kind": "api-key", "credential_ref": "secret:absent"}},
    "models": {PRIVATE: {"provider": PRIVATE, "remote_id": PRIVATE, "input": ["text"]}},
    "mcp": {PRIVATE: {"transport": "stdio", "command": "/not installed/服务", "args": []}},
  })
  profile = local.data["overrides"]["profiles"]["fixture-default"]
  profile.update(providers=[PRIVATE], models=[PRIVATE], mcp=[PRIVATE], roles={"main": PRIVATE, "small": PRIVATE})
  result = resolve(catalog, local)
  assert list(result.data["providers"]) == [PRIVATE]
  assert result.data["mcp"][PRIVATE]["args"] == []
  assert PRIVATE not in repr(result) + repr(result.provenance) + repr(config.public_diagnostics(result))


@pytest.mark.parametrize("kind,partial", [("providers", {"base_url": "https://example.invalid"}),
                                         ("models", {"input": []}), ("mcp", {"args": []})])
def test_new_entities_need_complete_original_schema_even_unselected(tmp_path, kind, partial):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  local.data["overrides"][kind] = {PRIVATE: partial}
  schema.validate_document("local", local.data, adapter_schemas=catalog.adapter_schemas)
  with pytest.raises(schema.ConfigError, match="schema"):
    resolve(catalog, local)


@pytest.mark.parametrize("kind", ["providers", "models", "mcp", "rules", "skills", "plugins"])
def test_all_selection_references_must_exist(tmp_path, kind):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  local.data["overrides"]["profiles"]["fixture-default"][kind] = [PRIVATE]
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local)
  assert caught.value.code == "reference"
  assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("mutation", ["model-provider", "selected-provider", "role-selection", "deleted-rule", "unknown-profile"])
def test_semantic_references_are_not_silently_repaired(tmp_path, mutation):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  if mutation == "model-provider":
    catalog.registry["models"]["secondary"]["provider"] = PRIVATE
  elif mutation == "selected-provider":
    local.data["overrides"]["profiles"]["fixture-default"]["providers"] = []
  elif mutation == "role-selection":
    local.data["overrides"]["profiles"]["fixture-default"]["models"] = ["primary"]
  elif mutation == "deleted-rule":
    del catalog.registry["rules"]["one"]
  else:
    local.data["overrides"]["profiles"][PRIVATE] = {}
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local)
  assert caught.value.code == "reference"


@pytest.mark.parametrize("overrides", [{"mcp": []}, {PRIVATE: "secret:value"}, {"profile": "fixture-default"}, [], ""])
def test_request_overrides_have_no_implicit_allowlist(tmp_path, overrides):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local, request_overrides=overrides)
  assert caught.value.code == "request"
  assert PRIVATE not in repr(caught.value)


def test_deselection_represents_absence_without_deletion(tmp_path, sentinel_factory):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  target = tmp_path / "user-skill"
  target.write_text("unmanaged or modified content")
  sentinel = sentinel_factory(target)
  local.data["overrides"]["profiles"]["fixture-default"].update(skills=[], rules=[], plugins=[])
  result = resolve(catalog, local, request_overrides={})
  assert result.data["skills"] == result.data["rules"] == result.data["plugins"] == {}
  sentinel.assert_unchanged()


def test_secret_rotation_does_not_reach_callback_render_or_provenance(tmp_path, monkeypatch):
  catalog, local, adapter, paths = resolution_inputs(tmp_path)
  from agentcfg.secrets import SecretStore

  def forbidden(*args, **kwargs):
    raise AssertionError("resolver must never resolve a secret")

  monkeypatch.setattr(SecretStore, "resolve", forbidden)
  first = resolve(catalog, local)
  paths["local"].write_text(paths["local"].read_text().replace('not-filled = ""', 'not-filled = "PRIVATE-secret"'))
  changed, store = config.load_local(paths["local"], adapter_schemas=catalog.adapter_schemas)
  second = resolve(catalog, changed)
  assert first.data == second.data
  assert dict(first.provenance) == dict(second.provenance)
  assert adapter.render(first.data) == adapter.render(second.data)
  assert "PRIVATE-secret" not in repr((first, second, store))


def test_successful_adapter_callback_mutations_do_not_change_resolution_or_sources(tmp_path):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  bundle = catalog.adapter_schemas.bundles["fixture-json"]

  def mutating_callback(kind, data):
    if kind == "resolved":
      data["profile"]["roles"].clear()

  catalog.adapter_schemas.bundles["fixture-json"] = replace(bundle, validate=mutating_callback)
  result = resolve(catalog, local)
  assert result.data["profile"]["roles"]["main"] == "secondary"
  assert catalog.profiles["fixture-default"]["roles"]["main"] == "primary"


def test_every_profile_uses_its_own_adapter_even_when_unselected(tmp_path):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  first = catalog.adapter_schemas.bundles["fixture-json"]
  second = replace(first, declaration=AdapterDeclaration("fixture-other", 2, "v1"),
                   agent_options=closed({"quiet": {"type": "boolean"}}, ("quiet",)),
                   policy=lambda docs: schema.AdapterPolicy(defaults={}, plugins={}, credential_targets=frozenset()))
  catalog.adapter_schemas.bundles["fixture-other"] = second
  catalog.adapter_documents["fixture-other"] = deepcopy(catalog.adapter_documents["fixture-json"])
  catalog.profiles["other"] = {"schema_version": 1, "id": "other", "agent": "fixture-other",
                                "agent_options": {"quiet": True}}
  local.data["overrides"]["profiles"]["other"] = {"agent_options": {"quiet": False}}
  assert resolve(catalog, local).validated_profiles == 2
  local.data["overrides"]["profiles"]["other"]["agent_options"] = {"terminal_images": False}
  with pytest.raises(schema.ConfigError):
    resolve(catalog, local)


@pytest.mark.parametrize("constraint", ["not", "if", "allOf", "anyOf", "oneOf", "dependentRequired", "dependentSchemas", "required"])
def test_final_original_options_schema_rejects_invalid_merge_that_partial_accepts(tmp_path, constraint):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  bundle = catalog.adapter_schemas.bundles["fixture-json"]
  yes = closed({"terminal_images": {"type": "boolean", "const": True}, "caption": {"type": "string"}})
  no = closed({"terminal_images": {"type": "boolean", "const": False}, "caption": {"type": "string"}},
              ("terminal_images",))
  if constraint == "not":
    bundle.agent_options["not"] = no
  elif constraint == "if":
    bundle.agent_options.update({"if": no, "then": closed({"caption": {"type": "string", "minLength": 1},
                                                          "terminal_images": {"type": "boolean"}})})
  elif constraint in ("allOf", "anyOf", "oneOf"):
    bundle.agent_options[constraint] = [yes]
  else:
    bundle.agent_options["properties"]["needed"] = {"type": "boolean"}
    if constraint == "required":
      bundle.agent_options["required"].append("needed")
    elif constraint == "dependentRequired":
      bundle.agent_options[constraint] = {"caption": ["needed"]}
    else:
      bundle.agent_options[constraint] = {"caption": closed(deepcopy(bundle.agent_options["properties"]), ("needed",))}
  # 独立证明来源文档和 partial 均通过；失败必须来自最终 profile/options。
  schema.validate_document("agent", catalog.adapter_documents["fixture-json"]["agent"],
                           adapter_schemas=catalog.adapter_schemas, adapter_id="fixture-json")
  schema.validate_document("profile", catalog.profiles["fixture-default"],
                           adapter_schemas=catalog.adapter_schemas, partial_options=True)
  schema.validate_document("local", local.data, adapter_schemas=catalog.adapter_schemas)
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local)
  assert caught.value.code == "schema"
  assert caught.value.path[:2] == ("profile", "agent_options")


@pytest.mark.parametrize("problem", ["transport", "model-input", "binding", "unselected-profile", "callback-leak"])
def test_adapter_capabilities_checked_on_real_resolved_nonsecret_data(tmp_path, problem):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  if problem == "transport":
    local.data["overrides"]["profiles"]["fixture-default"]["mcp"] = ["first"]
    catalog.registry["mcp"]["first"]["transport"] = PRIVATE
  elif problem == "model-input":
    catalog.registry["models"]["primary"]["input"] = [PRIVATE]
  elif problem == "binding":
    catalog.adapter_documents["fixture-json"]["bindings"]["roles"]["main"] = PRIVATE
  elif problem == "unselected-profile":
    catalog.profiles["other"] = deepcopy(catalog.profiles["fixture-default"])
    catalog.profiles["other"].update(id="other", roles={PRIVATE: "primary"})
  else:
    def failure(kind, data):
      if kind == "resolved":
        data["profile"]["roles"].clear()
        raise RuntimeError("https://private.example.invalid/" + PRIVATE)
    catalog.adapter_schemas.bundles["fixture-json"] = replace(
      catalog.adapter_schemas.bundles["fixture-json"], validate=failure)
  with pytest.raises(schema.ConfigError) as caught:
    resolve(catalog, local)
  assert caught.value.code == "adapter"
  assert caught.value.__context__ is None
  assert PRIVATE not in repr(caught.value) + "".join(traceback.format_exception(caught.value))
  assert "main" in catalog.profiles["fixture-default"]["roles"]
