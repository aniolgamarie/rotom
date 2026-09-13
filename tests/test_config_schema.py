"""框架结构校验；虚构 adapter 不代表生产 DSH 能力。"""

from copy import deepcopy
import importlib
from pathlib import Path
import shutil
import tomllib
import traceback
import urllib.request

import pytest

from agentcfg.adapter import AdapterDeclaration


FIXTURES = Path(__file__).parent / "fixtures/framework"
CANARY = "PRIVATE-CANARY-key"


def api():
  # 在首次实现前给出明确的缺失功能断言，而不是收集失败。
  assert importlib.util.find_spec("agentcfg.schema") is not None, "schema API missing"
  assert importlib.util.find_spec("agentcfg.config") is not None, "config loader missing"
  return importlib.import_module("agentcfg.schema"), importlib.import_module("agentcfg.config")


def closed(properties, required=()):
  return {"type": "object", "properties": properties, "required": list(required),
          "additionalProperties": False}


def adapter_context():
  schema, _ = api()
  document = closed({"schema_version": {"type": "integer", "const": 2},
                     "mapping": {"type": "string", "enum": ["supported"]}},
                    ("schema_version", "mapping"))

  def validate(kind, data):
    if data.get("mapping") != "supported":
      raise ValueError(CANARY)

  bundle = schema.AdapterSchemaBundle(
    declaration=AdapterDeclaration("synthetic", 2, "mapping-v9"),
    documents={kind: deepcopy(document) for kind in ("agent", "bindings", "plugins")},
    agent_options=closed({"terminal_images": {"type": "boolean"}}, ("terminal_images",)),
    validate=validate,
  )
  return schema.AdapterSchemas(bundles={"synthetic": bundle},
                               profile_agents={"synthetic-default": "synthetic"})


def document(name):
  return tomllib.loads((FIXTURES / f"{name}.toml").read_text())


def test_load_sources_and_local_are_callable_and_nonsecret(tmp_path):
  schema, config = api()
  context = adapter_context()
  paths = {}
  for kind in ("agent", "bindings", "plugins"):
    path = tmp_path / f"{kind}.toml"
    path.write_text('schema_version = 2\nmapping = "supported"\n')
    paths[kind] = path
  sources = config.SourceInputs(
    registries=(FIXTURES / "registry.toml",), profiles=(FIXTURES / "profile.toml",),
    adapters={"synthetic": config.AdapterSources(**paths)},
  )
  catalog = config.load_sources(sources, adapter_schemas=context)
  private = tmp_path / "local.toml"
  private.write_bytes((FIXTURES / "local.toml").read_bytes())
  local, store = config.load_local(private, adapter_schemas=catalog.adapter_schemas)
  assert catalog.registry["models"]["synthetic"]["remote_id"] == "fictional-chat"
  assert catalog.profiles["synthetic-default"]["agent"] == "synthetic"
  assert catalog.adapter_documents["synthetic"]["bindings"]["schema_version"] == 2
  assert local.data["overrides"]["profiles"]["synthetic-default"]["agent_options"] == {"terminal_images": False}
  assert "secrets" not in local.data
  for value in (catalog, local, store, sources, context, context.bundles["synthetic"]):
    assert "private_gateway" not in repr(value)
    assert "synthetic" not in repr(value)
    assert str(FIXTURES) not in repr(value)


@pytest.mark.parametrize("kind", ["registry", "profile", "local"])
@pytest.mark.parametrize("version", [True, False, 0, 2, "1", 1.0, None])
def test_framework_version_is_exact_integer_one(kind, version):
  schema, _ = api()
  data = document(kind)
  data["schema_version"] = version
  with pytest.raises(schema.ConfigError) as caught:
    schema.validate_document(kind, data, adapter_schemas=adapter_context())
  assert caught.value.code == "version"


@pytest.mark.parametrize("kind,path", [
  ("registry", []), ("registry", ["providers", "synthetic"]),
  ("registry", ["models", "synthetic"]), ("registry", ["mcp", "synthetic"]),
  ("registry", ["rules", "synthetic"]), ("registry", ["skills", "synthetic"]),
  ("profile", []), ("profile", ["agent_options"]),
  ("local", []), ("local", ["machine"]), ("local", ["machine", "paths"]),
  ("local", ["overrides"]), ("local", ["overrides", "providers", "private_gateway"]),
  ("local", ["overrides", "profiles", "synthetic-default", "agent_options"]),
])
def test_unknown_canary_keys_fail_without_private_error_context(kind, path, capsys):
  schema, _ = api()
  data = document(kind)
  target = data
  for key in path:
    target = target[key]
  target[CANARY] = "https://private.example.invalid/private-model"
  with pytest.raises(schema.ConfigError) as caught:
    schema.validate_document(kind, data, adapter_schemas=adapter_context())
  error = caught.value
  output = repr(error) + str(error) + repr(vars(error)) + "".join(traceback.format_exception(error))
  assert CANARY not in output
  assert "private.example.invalid" not in output
  assert "private_gateway" not in output
  assert error.__context__ is None
  assert capsys.readouterr() == ("", "")


def test_partial_local_entities_are_structural_not_merged_validation():
  schema, _ = api()
  local = {"schema_version": 1, "machine": {"id": "machine"}, "overrides": {
    "providers": {"new-or-existing": {"base_url": "https://example.invalid"}},
    "models": {"new-or-existing": {"input": []}},
    "mcp": {"new-or-existing": {"args": []}},
    "profiles": {"synthetic-default": {"agent_options": {}}},
  }}
  schema.validate_document("local", local, adapter_schemas=adapter_context())
  with pytest.raises(schema.ConfigError):
    schema.validate_document("registry", {"schema_version": 1, "providers": local["overrides"]["providers"]})
  local["overrides"]["profiles"]["synthetic-default"]["agent"] = "other"
  with pytest.raises(schema.ConfigError):
    schema.validate_document("local", local, adapter_schemas=adapter_context())


@pytest.mark.parametrize("reference", ["secret:", "plain-key", "secret:../key", "secret:a/b"])
def test_credential_reference_syntax_is_checked_offline(reference):
  schema, _ = api()
  data = document("registry")
  data["providers"]["synthetic"]["credential_ref"] = reference
  with pytest.raises(schema.ConfigError):
    schema.validate_document("registry", data)


def test_options_require_explicit_adapter_context(tmp_path):
  schema, config = api()
  private = tmp_path / "local.toml"
  private.write_bytes((FIXTURES / "local.toml").read_bytes())
  with pytest.raises(schema.ConfigError):
    config.load_local(private)
  with pytest.raises(schema.ConfigError):
    schema.validate_document("profile", document("profile"))
  context = adapter_context()
  context.profile_agents["synthetic-default"] = "missing"
  with pytest.raises(schema.ConfigError):
    config.load_local(private, adapter_schemas=context)


@pytest.mark.parametrize("kind", ["agent", "bindings", "plugins"])
def test_adapter_document_schema_and_mapping_callback_are_enforced(kind):
  schema, _ = api()
  context = adapter_context()
  schema.validate_document(kind, {"schema_version": 2, "mapping": "supported"},
                           adapter_schemas=context, adapter_id="synthetic")
  for bad in ({"schema_version": True, "mapping": "supported"},
              {"schema_version": 1, "mapping": "supported"},
              {"schema_version": 2, "mapping": CANARY},
              {"schema_version": 2, "mapping": "supported", CANARY: True}):
    with pytest.raises(schema.ConfigError):
      schema.validate_document(kind, bad, adapter_schemas=context, adapter_id="synthetic")
  context.bundles["synthetic"].documents[kind]["properties"]["mapping"] = {"type": "string"}
  with pytest.raises(schema.ConfigError) as caught:
    schema.validate_document(kind, {"schema_version": 2, "mapping": CANARY},
                             adapter_schemas=context, adapter_id="synthetic")
  assert CANARY not in "".join(traceback.format_exception(caught.value))
  assert caught.value.__context__ is None


@pytest.mark.parametrize("bad_schema", [
  {}, True, {"type": "object"},
  closed({"nested": {"type": "object"}}),
  closed({"nested": {"type": "array"}}),
  {"$ref": "https://example.invalid/schema"},
  closed({"nested": {"$ref": "file:///private/schema"}}),
])
def test_injected_schemas_cannot_open_unvalidated_escape_or_fetch(bad_schema):
  schema, _ = api()
  context = adapter_context()
  context.bundles["synthetic"].agent_options.clear()
  if isinstance(bad_schema, dict):
    context.bundles["synthetic"].agent_options.update(bad_schema)
  else:
    object.__setattr__(context.bundles["synthetic"], "agent_options", bad_schema)
  with pytest.raises(schema.ConfigError):
    schema.validate_document("profile", document("profile"), adapter_schemas=context)


@pytest.mark.parametrize("kind", ["registry", "profile"])
def test_same_layer_duplicate_ids_across_files_fail(tmp_path, kind):
  schema, config = api()
  first = tmp_path / "one.toml"
  second = tmp_path / f"{CANARY}.toml"
  first.write_bytes((FIXTURES / f"{kind}.toml").read_bytes())
  second.write_bytes(first.read_bytes())
  sources = config.SourceInputs(**{"registries" if kind == "registry" else "profiles": (first, second)})
  with pytest.raises(schema.ConfigError) as caught:
    config.load_sources(sources, adapter_schemas=adapter_context())
  assert caught.value.code == "duplicate"
  assert CANARY not in repr(caught.value)


@pytest.mark.parametrize("text", [
  'schema_version = 1\n[secrets]\nkey = "PRIVATE-CANARY-key',
  'schema_version = 1\n[secrets]\nkey = "PRIVATE-CANARY-key"\n[secrets]\n',
])
def test_toml_failures_do_not_attach_raw_exception(tmp_path, text):
  schema, config = api()
  path = tmp_path / CANARY
  path.write_text(text)
  with pytest.raises(schema.ConfigError) as caught:
    config.load_local(path)
  assert caught.value.code == "parse"
  assert caught.value.__context__ is None
  assert CANARY not in "".join(traceback.format_exception(caught.value))


def test_missing_source_error_hides_private_path(tmp_path):
  schema, config = api()
  with pytest.raises(schema.ConfigError) as caught:
    config.load_local(tmp_path / CANARY)
  assert caught.value.code == "read"
  assert caught.value.__context__ is None
  assert CANARY not in repr(vars(caught.value))


@pytest.mark.parametrize("name", ["bad/name", "..", "bad\\name", "bad\n", "bad\x00", ""])
def test_entity_ids_reject_escape_and_controls(name):
  schema, _ = api()
  data = document("registry")
  data["providers"][name] = data["providers"].pop("synthetic")
  with pytest.raises(schema.ConfigError):
    schema.validate_document("registry", data)
  data = document("registry")
  data["providers"]["synthetic"]["credential_ref"] = "secret:" + name
  with pytest.raises(schema.ConfigError):
    schema.validate_document("registry", data)


def test_agent_options_must_be_mapping_even_when_injected_schema_is_scalar():
  schema, _ = api()
  context = adapter_context()
  context.bundles["synthetic"].agent_options.clear()
  context.bundles["synthetic"].agent_options.update({"type": "string"})
  data = document("profile")
  data["agent_options"] = CANARY
  with pytest.raises(schema.ConfigError):
    schema.validate_document("profile", data, adapter_schemas=context)


def test_partial_options_keep_fields_named_required_and_nested_validation():
  schema, _ = api()
  context = adapter_context()
  context.bundles["synthetic"].agent_options.clear()
  context.bundles["synthetic"].agent_options.update(closed({
    "required": {"type": "boolean"},
    "nested": closed({"enabled": {"type": "boolean"}, "count": {"type": "integer"}}, ("enabled", "count")),
  }, ("required", "nested")))
  data = document("local")
  options = data["overrides"]["profiles"]["synthetic-default"]["agent_options"]
  options.clear()
  options.update({"required": False, "nested": {"enabled": False}})
  schema.validate_document("local", data, adapter_schemas=context)
  options["nested"]["enabled"] = "wrong"
  with pytest.raises(schema.ConfigError):
    schema.validate_document("local", data, adapter_schemas=context)


def option_documents(context, option_schema, value):
  options = context.bundles["synthetic"].agent_options
  options.clear()
  options.update(option_schema)
  profile = document("profile")
  profile["agent_options"] = deepcopy(value)
  local = document("local")
  local["overrides"]["profiles"]["synthetic-default"]["agent_options"] = deepcopy(value)
  return profile, local


@pytest.mark.parametrize("target", [
  {}, {"$ref": "https://example.invalid/schema"},
  {"type": "integer", "minimum": "invalid"},
  {"type": "object", "additionalProperties": False, "$id": "https://example.invalid/schema"},
])
def test_local_annotation_ref_targets_are_strict_and_never_fetched(target, monkeypatch):
  schema, _ = api()

  calls = []

  def no_fetch(*args, **kwargs):
    calls.append(args)
    raise AssertionError("unexpected retrieval")

  monkeypatch.setattr(urllib.request, "urlopen", no_fetch)
  context = adapter_context()
  options = closed({"native": {"$ref": "#/$defs/holder/default"}})
  options["$defs"] = {"holder": {"type": "string", "default": target}}
  profile, local = option_documents(context, options, {"native": {CANARY: True}})
  for kind, data in (("profile", profile), ("local", local)):
    with pytest.raises(schema.ConfigError) as caught:
      schema.validate_document(kind, data, adapter_schemas=context)
    assert caught.value.code == "adapter-schema"
    assert caught.value.__context__ is None
  assert calls == []


@pytest.mark.parametrize("reference", [
  "https://example.invalid/schema", "file:///private/schema", "//example.invalid/schema",
])
@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
def test_actual_validator_never_calls_network_retrieval(reference, keyword, monkeypatch):
  schema, _ = api()

  calls = []

  def no_fetch(*args, **kwargs):
    calls.append(args)
    raise AssertionError("unexpected retrieval")

  monkeypatch.setattr(urllib.request, "urlopen", no_fetch)
  with pytest.raises(schema.ConfigError) as caught:
    schema._validate({keyword: reference}, {}, ("profile",))
  assert calls == []
  assert caught.value.__context__ is None


@pytest.mark.parametrize("keyword,value", [
  ("customValidation", True), ("$recursiveRef", "#"),
  ("$anchor", "elsewhere"), ("$vocabulary", {}), ("format", "email"),
  ("$schema", "https://example.invalid/schema"),
])
def test_unsupported_injected_schema_keywords_fail_explicitly(keyword, value):
  schema, _ = api()
  context = adapter_context()
  options = closed({"x": {"type": "boolean"}})
  options[keyword] = value
  profile, _ = option_documents(context, options, {"x": True})
  with pytest.raises(schema.ConfigError) as caught:
    schema.validate_document("profile", profile, adapter_schemas=context)
  assert caught.value.code == "adapter-schema"


@pytest.mark.parametrize("predicate", ["not", "if", "oneOf", "anyOf", "allOf", "dependentSchemas",
                                      "dependentRequired", "minProperties", "const", "enum"])
def test_partial_options_defer_predicates_but_full_validation_enforces_them(predicate):
  schema, _ = api()
  context = adapter_context()
  fields = {"x": {"type": "boolean"}, "y": {"type": "boolean"}}
  options = closed(deepcopy(fields))
  partial = {"x": False}
  valid = {"x": True}
  invalid = {"x": False, "y": True}
  if predicate == "not":
    options["not"] = {"type": "object", "required": ["x", "y"],
                      "additionalProperties": {"type": "boolean"}}
  elif predicate == "if":
    options["if"] = closed(deepcopy(fields), ("y",))
    options["then"] = closed({"x": {"type": "boolean", "const": True}, "y": fields["y"]})
  elif predicate == "oneOf":
    options["oneOf"] = [closed(deepcopy(fields), ("x",)), closed(deepcopy(fields), ("y",))]
  elif predicate in ("anyOf", "allOf", "dependentSchemas"):
    branch = closed(deepcopy(fields), ("y",))
    branch["properties"]["y"]["const"] = False
    options[predicate] = {"x": branch} if predicate == "dependentSchemas" else [branch]
    valid["y"] = False
  elif predicate == "dependentRequired":
    options[predicate] = {"x": ["y"]}
    valid["y"] = True
    invalid = {"x": False}
  elif predicate == "minProperties":
    options[predicate] = 2
    valid["y"] = True
    invalid = {"x": False}
  else:
    valid["x"] = False
    valid["y"] = False
    options[predicate] = valid if predicate == "const" else [valid]
  profile, local = option_documents(context, options, partial)
  original = deepcopy(options)
  profile["agent_options"] = valid
  schema.validate_document("profile", profile, adapter_schemas=context)
  schema.validate_document("local", local, adapter_schemas=context)
  profile["agent_options"] = invalid
  with pytest.raises(schema.ConfigError):
    schema.validate_document("profile", profile, adapter_schemas=context)
  for bad in ({"x": "wrong"}, {CANARY: True}):
    local["overrides"]["profiles"]["synthetic-default"]["agent_options"] = bad
    with pytest.raises(schema.ConfigError):
      schema.validate_document("local", local, adapter_schemas=context)
  assert context.bundles["synthetic"].agent_options == original


@pytest.mark.parametrize("location", ["definition", "default", "not"])
def test_recursive_local_ref_targets_remain_strict_in_partial_options(location):
  schema, _ = api()
  context = adapter_context()
  pointer = "#/$defs/node" if location == "definition" else f"#/$defs/holder/{location}"
  node = closed({"required": {"type": "boolean"}, "child": {"$ref": pointer}}, ("required",))
  options = closed({"root": {"$ref": pointer}}, ("root",))
  options["$defs"] = {"node": node} if location == "definition" else {"holder": {"type": "string", location: node}}
  profile, local = option_documents(context, options, {"root": {"child": {"required": False}}})
  original = deepcopy(options)
  schema.validate_document("local", local, adapter_schemas=context)
  with pytest.raises(schema.ConfigError):
    schema.validate_document("profile", profile, adapter_schemas=context)
  profile["agent_options"]["root"]["required"] = True
  schema.validate_document("profile", profile, adapter_schemas=context)
  child = local["overrides"]["profiles"]["synthetic-default"]["agent_options"]["root"]["child"]
  for bad in ({"required": "wrong"}, {CANARY: True}):
    child.clear()
    child.update(bad)
    with pytest.raises(schema.ConfigError):
      schema.validate_document("local", local, adapter_schemas=context)
  assert context.bundles["synthetic"].agent_options == original


def test_partial_options_keep_scalar_constraints_and_ignore_annotation_keys():
  schema, _ = api()
  context = adapter_context()
  options = closed({"required": {"type": "integer", "minimum": 1, "enum": [1, 2],
                                 "default": {"customValidation": True}}})
  _, local = option_documents(context, options, {"required": 1})
  schema.validate_document("local", local, adapter_schemas=context)
  for value in (0, 3, "1"):
    local["overrides"]["profiles"]["synthetic-default"]["agent_options"]["required"] = value
    with pytest.raises(schema.ConfigError):
      schema.validate_document("local", local, adapter_schemas=context)


@pytest.mark.parametrize("reference", [False, True])
def test_partial_options_preserve_scalar_enum_even_with_container_alternatives(reference):
  schema, _ = api()
  context = adapter_context()
  field = {"$ref": "#/$defs/text"} if reference else {"type": "string"}
  field["enum"] = ["allowed", {}]
  options = closed({"value": field})
  options["$defs"] = {"text": {"type": "string"}}
  _, local = option_documents(context, options, {"value": "allowed"})
  schema.validate_document("local", local, adapter_schemas=context)
  local["overrides"]["profiles"]["synthetic-default"]["agent_options"]["value"] = "wrong"
  with pytest.raises(schema.ConfigError):
    schema.validate_document("local", local, adapter_schemas=context)


def test_schema_resources_work_in_installed_layout(tmp_path, monkeypatch):
  schema, _ = api()
  package = tmp_path / "site-packages/agentcfg"
  package.mkdir(parents=True)
  shutil.copytree(FIXTURES.parents[2] / "schemas", package / "schemas")
  monkeypatch.setattr(schema, "__file__", str(package / "schema.py"))
  schema.validate_document("registry", document("registry"))
  (package / "schemas/registry.schema.json").write_text("{}")
  with pytest.raises(schema.ConfigError):
    schema.validate_document("registry", document("registry"))
