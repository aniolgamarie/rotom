from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from agentcfg.adapter import RenderContext
from agentcfg.omp import OmpAdapter
from agentcfg.schema import ConfigError
from agentcfg.skills import collect_skills
from agentcfg.config import AdapterSources, SourceInputs, load_local, load_sources, resolve_config
from agentcfg.render import render_candidate


REPO = Path(__file__).resolve().parents[1]


def omp_data():
  return {
    "machine": {"id": "test", "paths": {"instances_root": "/tmp/instances", "state_root": "/tmp/state",
      "cache_root": "/tmp/cache"}, "environment": {"inherit": [], "values": {}}},
    "profile": {"id": "omp-validation", "agent": "omp", "providers": ["gateway"],
      "models": ["large", "small"], "rules": ["one", "two"], "skills": ["full-package"],
      "plugins": [], "mcp": [], "roles": {"main": "large", "smol": "small"},
      "agent_options": {"discovery": {"project_resources": False, "project_roots": []},
        "resources": {"prompts": [], "themes": []}}},
    "providers": {"gateway": {"protocol": "openai-compatible", "auth_kind": "api-key",
      "base_url": "https://omp-validation.invalid/v1", "credential_ref": "secret:placeholder"}},
    "models": {
      "large": {"provider": "gateway", "remote_id": "large-v1", "input": ["text", "image"],
        "context_window": 100000, "max_output_tokens": 8000},
      "small": {"provider": "gateway", "remote_id": "small-v1", "input": ["text"],
        "context_window": 32000, "max_output_tokens": 4000}},
    "rules": {"one": {"path": "tests/fixtures/omp/rules/one.md"},
      "two": {"path": "tests/fixtures/omp/rules/two.md"}},
    "skills": {"full-package": {"path": "tests/fixtures/omp/skills/full-package"}},
    "plugins": {}, "mcp": {}, "adapter_documents": {},
  }


def artifact_map(adapter, data):
  return {(item.target.path, item.target.selector): item for item in adapter.render(data)}


def full_data():
  data = omp_data()
  data["profile"].update(plugins=["rotom-health"], mcp=["echo-stdio", "echo-http"])
  data["profile"]["agent_options"].update(
    resources={"prompts": ["rotom-review"], "themes": ["rotom-dark"]},
    ui={"theme_dark": "rotom-dark", "theme_light": "rotom-dark", "keybindings": {
      "app.model.cycleForward": "Ctrl+P", "app.history.search": []}})
  data["plugins"] = {"rotom-health": {"id": "rotom-health", "source": "agents/omp/packages/rotom-health",
    "entrypoints": ["index.ts"], "tree_digest": "a382040f693dc402fdca39134a02e4c6ca158b8f23f6a8d495de486b840067ca", "license": "MIT",
    "compatibility": {"omp": "v18.3.0"}}}
  data["mcp"] = {"echo-stdio": {"transport": "stdio", "command": "omp-package:echo-mcp", "args": []},
    "echo-http": {"transport": "streamable-http", "url": "https://omp-validation.invalid/mcp"}}
  data["adapter_documents"] = {"agent": {"resources": {
    "rotom-review": {"kind": "prompt", "path": "agents/omp/resources/prompts/rotom-review.md", "scope": "global"},
    "rotom-dark": {"kind": "theme", "path": "agents/omp/resources/themes/rotom-dark.json", "scope": "global"}}},
    "plugins": {"plugins": {"rotom-health": data["plugins"]["rotom-health"], "echo-mcp": {
      "id": "echo-mcp", "source": "agents/omp/packages/echo-mcp", "entrypoints": ["server.py"],
      "tree_digest": "c10617b101717ec6ce399da846e165d7a6f1cfb5c2aad02d2f6c405cd187faf4",
      "license": "MIT", "compatibility": {"omp": "v18.3.0"}}}}}
  return data


def test_provider_models_roles_and_rules_render_as_deterministic_leaf_intents():
  adapter = OmpAdapter(REPO)
  data = omp_data()
  first = artifact_map(adapter, data)
  second = artifact_map(adapter, deepcopy(data))
  assert [(key, item.content, item.mode) for key, item in first.items()] == [
    (key, item.content, item.mode) for key, item in second.items()]
  agent = next(path.rsplit("/", 1)[0] for path, selector in first if selector == "/providers/gateway/api")
  models = json.loads(first[(agent + "/models.yml", "/providers/gateway/models")].content)
  assert models == [{"contextWindow": 100000, "id": "large-v1", "input": ["text", "image"],
    "maxTokens": 8000, "name": "large"}, {"contextWindow": 32000, "id": "small-v1",
    "input": ["text"], "maxTokens": 4000, "name": "small"}]
  assert json.loads(first[(agent + "/models.yml", "/providers/gateway/api")].content) == "openai-completions"
  assert json.loads(first[(agent + "/config.yml", "/modelRoles/default")].content) == "gateway/large-v1"
  assert json.loads(first[(agent + "/config.yml", "/modelRoles/smol")].content) == "gateway/small-v1"
  assert first[(agent + "/RULES.md", None)].content == b"rule-one\n\n\nrule-two\n"
  assert "cost" not in repr(models)


@pytest.mark.parametrize("mutate", [
  lambda data: data["providers"]["gateway"].update(protocol="unknown"),
  lambda data: data["providers"]["gateway"].update(base_url="https://user:password@example.invalid/v1"),
  lambda data: data["models"]["large"].pop("context_window"),
  lambda data: data["models"]["large"].update(input=["audio"]),
  lambda data: data["profile"]["roles"].update(unknown="large"),
  lambda data: data["profile"]["roles"].update(vision="small"),
  lambda data: data["profile"]["roles"].update(main="not-selected"),
  lambda data: data.update(mcp={"bad": {"transport": "stdio", "command": "omp-package:echo-mcp", "args": ["${TOKEN}"]}}),
  lambda data: data.update(mcp={"bad": {"transport": "streamable-http", "url": "https://example.invalid/${TOKEN}"}}),
])
def test_provider_model_and_role_invalid_inputs_fail_closed(mutate):
  data = omp_data()
  mutate(data)
  with pytest.raises(ConfigError):
    OmpAdapter(REPO).validate(data)


def test_omp_document_schemas_are_closed_and_plugin_package_requires_identity():
  schemas = OmpAdapter(REPO).schemas().bundles["omp"].documents
  for kind, schema in schemas.items():
    assert schema["additionalProperties"] is False
    Draft202012Validator.check_schema(schema)
  plugin = {"schema_version": 1, "plugins": {"health": {"id": "health", "source": "agents/omp/packages/health",
    "entrypoints": ["index.ts"], "tree_digest": "a" * 64, "license": "MIT",
    "compatibility": {"omp": "18.3.0"}}}}
  assert not tuple(Draft202012Validator(schemas["plugins"]).iter_errors(plugin))
  plugin["plugins"]["health"]["extra"] = True
  assert tuple(Draft202012Validator(schemas["plugins"]).iter_errors(plugin))


def test_native_intents_use_only_four_document_codecs_and_leaf_selectors():
  adapter = OmpAdapter(REPO)
  intents = adapter.render(omp_data())
  assert {Path(item.target.path).name for item in intents} <= {"config.yml", "models.yml", "RULES.md"}
  assert all(item.target.selector is None or item.target.selector.startswith("/") for item in intents)
  assert all(item.target.serialization in {"yaml", "bytes"} for item in intents)


def test_full_skill_package_is_copied_byte_for_byte_with_executable_intent():
  adapter = OmpAdapter(REPO)
  data = omp_data()
  scope = next(target for target in adapter.managed_targets(data) if target.serialization == "skill-directory")
  files = collect_skills(REPO, data["skills"], target_root=scope.path)
  assert {Path(item.target.path).name for item in files} == {"SKILL.md", "details.md", "check.sh"}
  script = next(item for item in files if item.target.path.endswith("/scripts/check.sh"))
  assert script.content == b"#!/bin/sh\nexit 99\n"
  assert script.mode == 0o700


def test_all_nine_capability_rows_render_with_explicit_locked_runtime_context(tmp_path):
  adapter = OmpAdapter(REPO)
  data = full_data()
  context = RenderContext("lock", tmp_path / "cache/runtimes/lock-linux-x64")
  result = {(item.target.path, item.target.selector): item for item in adapter.render_with_context(data, context)}
  assert any(path.endswith("/RULES.md") for path, selector in result)
  assert any("/prompts/rotom-review.md" in path for path, selector in result)
  theme = next(item for (path, selector), item in result.items() if path.endswith("/themes/rotom-dark.json"))
  assert json.loads(theme.content)["name"] == "rotom-dark"
  assert any(path.endswith("/keybindings.yml") and json.loads(item.content) == []
    for (path, selector), item in result.items())
  extension = next(item for (path, selector), item in result.items() if selector == "/extensions")
  assert json.loads(extension.content) == [str(context.runtime_root / "packages/rotom-health/index.ts")]
  command = next(item for (path, selector), item in result.items() if selector == "/mcpServers/echo-stdio/command")
  assert Path(json.loads(command.content)).is_absolute()
  args = next(item for (path, selector), item in result.items() if selector == "/mcpServers/echo-stdio/args")
  assert json.loads(args.content)[0] == str(context.runtime_root / "packages/echo-mcp/server.py")
  with pytest.raises(ConfigError, match="context"):
    adapter.render(data)


def test_checked_in_validation_fixture_resolves_and_renders_all_rows(tmp_path):
  adapter = OmpAdapter(REPO)
  schemas = adapter.schemas()
  sources = SourceInputs(tuple(sorted((REPO / "shared").glob("*.toml")))
    + (REPO / "agents/omp/content.toml", REPO / "tests/fixtures/omp/registry.toml"),
    (REPO / "profiles/omp-default.toml", REPO / "tests/fixtures/omp/profiles/omp-validation.toml"),
    {"omp": AdapterSources(REPO / "agents/omp/agent.toml", REPO / "agents/omp/bindings.toml",
      REPO / "agents/omp/plugins.toml")})
  catalog = load_sources(sources, adapter_schemas=schemas)
  private = tmp_path / "private"
  private.mkdir(mode=0o700)
  local_path = private / "local.toml"
  local_path.write_bytes((REPO / "examples/omp-validation.local.toml").read_bytes())
  local_path.chmod(0o600)
  local, _ = load_local(local_path, adapter_schemas=catalog.adapter_schemas)
  resolved = resolve_config(catalog, local, profile_id="omp-validation", adapter_schemas=catalog.adapter_schemas)
  scope = next(target.path for target in adapter.managed_targets(resolved.data)
    if target.serialization == "skill-directory")
  context = RenderContext("f" * 64, tmp_path / "cache/runtimes/synthetic-linux-x64")
  candidate = render_candidate(resolved, adapter=adapter, adapter_schemas=catalog.adapter_schemas,
    lock_identity=context.lock_identity, context=context, skill_root=REPO, skill_target_root=scope)
  paths = {item.target.path for item in candidate.artifacts}
  assert any(path.endswith("/RULES.md") for path in paths)
  assert any("/skills/full-package/SKILL.md" in path for path in paths)
  assert any("/prompts/rotom-review.md" in path for path in paths)
  assert any("/themes/rotom-dark.json" in path for path in paths)
  assert any(path.endswith("/keybindings.yml") for path in paths)
  assert any(path.endswith("/mcp.json") for path in paths)
