"""CFG-09 阶段三 API 证据；虚构 JSON adapter，不是原生 DSH 或 macOS 验收。"""

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import tomllib
import traceback

import pytest

from agentcfg import cli, config, schema
from agentcfg.adapter import Adapter, AdapterDeclaration, Artifact, DependencyPlan, ManagedTarget, Ownership
from agentcfg.secrets import SecretStore


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
NAMES = ("local", "xdg", "custom-paths", "ssh", "macos", "private-gateway", "multi-profile")
PROFILES = ("dsh-default", "dsh-ssh")
CANARY = "synthetic-private-example-canary"


def closed(properties, required=()):
  return {"type": "object", "additionalProperties": False,
          "properties": properties, "required": list(required)}


class ExampleAdapter(Adapter):
  # profile 名字来自框架示例，实际 agent 身份始终是测试专用 adapter。
  declaration = AdapterDeclaration("example-fixture-json", 2, "example-mapping-v1")

  def validate(self, data):
    assert "secrets" not in data
    assert set(data["profile"]["roles"]) <= set(data["adapter_documents"]["bindings"]["roles"])
    for provider in data["providers"].values():
      assert provider["protocol"] == "openai-compatible"
      assert provider["auth_kind"] == "api-key"
    assert all(model["input"] == ["text"] for model in data["models"].values())
    for server in data["mcp"].values():
      if server["transport"] == "stdio":
        assert "command" in server and "url" not in server
      else:
        assert server["transport"] == "http" and "url" in server
        assert "command" not in server and "args" not in server
    assert all(plugin["package"] == "fictional-plugin" for plugin in data["plugins"].values())

  def render(self, data):
    self.validate(data)
    projection = {"roles": data["profile"]["roles"], "models": data["models"],
                  "providers": data["providers"], "mcp": data["mcp"],
                  "terminal_images": data["profile"]["agent_options"]["terminal_images"]}
    return (Artifact(self.managed_targets(data)[0],
                     json.dumps(projection, ensure_ascii=False, sort_keys=True).encode("utf-8")),)

  def managed_targets(self, data):
    return (ManagedTarget("example-fixture.json", Ownership.FILE, "json"),)

  def dependency_plan(self, data):
    return DependencyPlan(())

  def launch_spec(self, data, **kwargs):
    raise AssertionError("example tests must never launch a host")

  def capture(self, projection):
    raise AssertionError("example tests must not capture native files")

  def doctor(self, projection):
    raise AssertionError("example tests must not inspect native files")


@pytest.fixture
def example_framework(tmp_path):
  # 所有文档真实落在临时目录并经 load_sources 校验；不导入其他测试模块的 helper。
  adapter = ExampleAdapter()
  selection = {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
  options = closed({"terminal_images": {"type": "boolean"}}, ("terminal_images",))
  defaults = closed({"providers": selection, "models": selection, "mcp": selection,
                     "agent_options": deepcopy(options)}, ("providers", "models", "mcp", "agent_options"))
  version = {"type": "integer", "const": 2}
  documents = {
    "agent": closed({"schema_version": version, "defaults": defaults}, ("schema_version", "defaults")),
    "bindings": closed({"schema_version": version,
                        "owner": {"type": "string", "const": "fixture-auth"},
                        "roles": closed({name: {"type": "string", "const": "fixture-model"}
                                         for name in ("main", "small")}, ("main", "small"))},
                       ("schema_version", "owner", "roles")),
    "plugins": closed({"schema_version": version, "packages": closed({
      "optional": closed({"package": {"type": "string", "const": "fictional-plugin"}}, ("package",))},
      ("optional",))}, ("schema_version", "packages")),
  }

  def validate(kind, data):
    if kind == "resolved":
      adapter.validate(data)

  bundle = schema.AdapterSchemaBundle(
    adapter.declaration, documents, options, validate,
    policy=lambda docs: schema.AdapterPolicy(defaults=docs["agent"]["defaults"],
      plugins=docs["plugins"]["packages"], credential_targets=frozenset({"EXAMPLE_GATEWAY_KEY"})),
    authentication_claims=lambda data: tuple(schema.AuthenticationClaim(
      provider, data["adapter_documents"]["bindings"]["owner"]) for provider in data["providers"]))
  context = schema.AdapterSchemas({adapter.declaration.adapter_id: bundle},
                                 {name: adapter.declaration.adapter_id for name in PROFILES})
  contents = {
    "registry": '''schema_version = 1
[providers.public_gateway]
protocol = "openai-compatible"
base_url = "https://public.example.invalid/v1"
auth_kind = "api-key"
credential_ref = "secret:public_gateway_key"
[models.public_main]
provider = "public_gateway"
remote_id = "fictional-public-chat"
input = ["text"]
[models.public_small]
provider = "public_gateway"
remote_id = "fictional-public-small"
input = ["text"]
[mcp.first]
transport = "stdio"
command = "fictional-mcp-first"
[mcp.second]
transport = "stdio"
command = "fictional-mcp-second"
[rules.baseline]
path = "shared/rules/fictional.md"
[skills.baseline]
path = "shared/skills/fictional"
''',
    "agent": '''schema_version = 2
[defaults]
providers = ["public_gateway"]
models = ["public_main", "public_small"]
mcp = ["first", "second"]
[defaults.agent_options]
terminal_images = true
''',
    "bindings": '''schema_version = 2
owner = "fixture-auth"
[roles]
main = "fixture-model"
small = "fixture-model"
''',
    "plugins": '''schema_version = 2
[packages.optional]
package = "fictional-plugin"
''',
  }
  for name in PROFILES:
    contents[name] = f'''schema_version = 1
id = "{name}"
agent = "example-fixture-json"
rules = ["baseline"]
skills = ["baseline"]
plugins = ["optional"]
[roles]
main = "public_main"
'''
  paths = {}
  for kind, text in contents.items():
    paths[kind] = tmp_path / f"{kind}.toml"
    paths[kind].write_text(text, encoding="utf-8")
  sources = config.SourceInputs((paths["registry"],), tuple(paths[name] for name in PROFILES), {
    adapter.declaration.adapter_id: config.AdapterSources(*(paths[kind] for kind in ("agent", "bindings", "plugins")))})
  return sources, context, adapter


def resolve_example(name, tmp_path, example_framework, *, profile_id=None):
  path = tmp_path / "copied-local.toml"
  path.write_bytes((EXAMPLES / f"{name}.example.toml").read_bytes())
  sources, context, adapter = example_framework
  local, store = config.load_local(path, adapter_schemas=context)
  catalog = config.load_sources(sources, adapter_schemas=context)
  result = config.resolve_config(catalog, local, profile_id=profile_id, adapter_schemas=context)
  return result, local, store, adapter


@pytest.mark.parametrize("name", NAMES)
def test_config_examples_load_resolve_validate_render_offline(name, tmp_path, example_framework,
                                                            monkeypatch, sentinel_factory, capsys):
  def forbidden(*args, **kwargs):
    raise AssertionError("offline examples must not resolve credentials")

  monkeypatch.setattr(SecretStore, "resolve", forbidden)
  before = sentinel_factory(EXAMPLES)
  home = sentinel_factory(Path(os.environ["HOME"]))
  cwd = Path.cwd()
  result, local, store, adapter = resolve_example(name, tmp_path, example_framework)
  assert result.validated_profiles == 2
  assert result.data["profile"]["agent"] == "example-fixture-json"
  adapter.validate(result.data)
  artifacts = adapter.render(result.data)
  assert artifacts == adapter.render(result.data)
  native = json.loads(artifacts[0].content)
  assert native["roles"] == result.data["profile"]["roles"]
  assert native["models"] == result.data["models"]
  assert artifacts[0].mode == 0o600
  assert "secrets" not in local.data and "secrets" not in result.data
  assert not (tmp_path / artifacts[0].target.path).exists()
  # TOML 检查只是额外的发布内容断言，不能代替以上真实 API 路径。
  document = tomllib.loads((EXAMPLES / f"{name}.example.toml").read_text(encoding="utf-8"))
  assert all(value == "" for value in document.get("secrets", {}).values())
  assert "框架 TOML" in (EXAMPLES / f"{name}.example.toml").read_text(encoding="utf-8")
  public = repr((result, result.provenance, store, config.public_diagnostics(result)))
  for provider in result.data["providers"].values():
    assert provider["base_url"].split("/")[2].endswith("example.invalid")
    assert provider["base_url"] not in public
  for model in result.data["models"].values():
    assert model["remote_id"].startswith("fictional-")
    assert model["remote_id"] not in public
  assert capsys.readouterr() == ("", "")
  assert Path.cwd() == cwd
  before.assert_unchanged()
  home.assert_unchanged()


@pytest.mark.parametrize("xdg", [False, True])
def test_config_examples_xdg_missing_only_defaults(xdg, tmp_path, example_framework, monkeypatch):
  home = Path(os.environ["HOME"])
  for name in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    if not xdg:
      monkeypatch.delenv(name)
  result, local, _, _ = resolve_example("xdg", tmp_path, example_framework)
  assert "paths" not in local.data["machine"]
  assert result.data["machine"]["paths"] == {
    "instances_root": str(home / ("data" if xdg else ".local/share") / "agentcfg/instances"),
    "state_root": str(home / ("state" if xdg else ".local/state") / "agentcfg"),
    "cache_root": str(home / ("cache" if xdg else ".cache") / "agentcfg"),
  }
  assert result.data["profile"]["providers"] == ["public_gateway"]
  assert result.data["profile"]["models"] == ["public_main", "public_small"]
  assert result.data["profile"]["agent_options"]["terminal_images"] is True
  assert result.data["profile"]["mcp"] == ["first", "second"]


@pytest.mark.parametrize("name,paths,editor", [
  ("custom-paths", {"instances_root": "/示例 磁盘/私人 实例", "state_root": "~/中文 状态/agentcfg",
                    "cache_root": "~/中文 缓存/agentcfg"}, "~/工具 空格/editor"),
  ("ssh", {"instances_root": "~/远程 工作/instances"}, "nvim"),
  ("macos", {"instances_root": "~/Library/Application Support/agentcfg/instances",
             "state_root": "~/Library/Application Support/agentcfg/state",
             "cache_root": "~/Library/Caches/agentcfg"}, "/Applications/示例 编辑器.app/Contents/MacOS/editor"),
])
def test_config_examples_paths_are_literal_data_not_host_checks(name, paths, editor, tmp_path,
                                                              example_framework, monkeypatch):
  accessed = []
  original_stat, original_open = Path.stat, Path.open

  def guard(path):
    text = str(path)
    accessed.append(text)
    assert not text.startswith(("/示例 磁盘", "/Applications/示例 编辑器.app"))
    assert "/Library/" not in text and "/远程 工作/" not in text and "/工具 空格/" not in text

  def checked_stat(path, *args, **kwargs):
    guard(path)
    return original_stat(path, *args, **kwargs)

  def checked_open(path, *args, **kwargs):
    guard(path)
    return original_open(path, *args, **kwargs)

  monkeypatch.setattr(Path, "stat", checked_stat)
  monkeypatch.setattr(Path, "open", checked_open)
  result, _, _, _ = resolve_example(name, tmp_path, example_framework)
  expand = lambda value: value.replace("~/", os.environ["HOME"] + "/", 1) if value.startswith("~/") else value
  for key, value in paths.items():
    assert result.data["machine"]["paths"][key] == expand(value)
    assert result.provenance[("machine", "paths", key)] == "local"
  assert result.data["machine"]["editor"] == expand(editor)
  if name == "ssh":
    assert result.data["machine"]["paths"]["state_root"] == os.environ["XDG_STATE_HOME"] + "/agentcfg"
    assert result.data["machine"]["environment"] == {
      "inherit": ["TERM", "SSH_TTY", "TMUX"], "values": {"LANG": "zh_CN.UTF-8"}}
    assert result.data["profile"]["agent_options"]["terminal_images"] is False
  assert accessed


@pytest.mark.parametrize("name,selected_mcp", [("local", []), ("private-gateway", ["private_docs"])])
def test_config_examples_private_additions_and_empty_selection(name, selected_mcp, tmp_path, example_framework):
  result, local, _, _ = resolve_example(name, tmp_path, example_framework)
  assert result.data["profile"]["providers"] == ["private_gateway"]
  assert result.data["profile"]["models"] == ["private_main"]
  assert result.data["profile"]["roles"] == {"main": "private_main"}
  assert list(result.data["mcp"]) == selected_mcp
  assert "private_docs" in local.data["overrides"]["mcp"]
  assert result.data["profile"]["agent_options"]["terminal_images"] is False
  assert result.provenance[("profile", "mcp")] == "local"
  assert result.provenance[("profile", "rules")] == "profile"
  assert result.data["rules"] and result.data["skills"] and result.data["plugins"]


@pytest.mark.parametrize("profile_id", PROFILES)
def test_config_examples_multiple_declared_profiles_select_independently(profile_id, tmp_path, example_framework):
  result, local, _, _ = resolve_example("multi-profile", tmp_path, example_framework, profile_id=profile_id)
  assert set(local.data["overrides"]["profiles"]) == set(PROFILES)
  assert result.validated_profiles == 2
  assert result.data["profile"]["id"] == profile_id
  if profile_id == "dsh-default":
    assert list(result.data["models"]) == ["private_main"]
    assert list(result.data["mcp"]) == ["private_docs"]
    assert result.data["profile"]["agent_options"]["terminal_images"] is True
  else:
    assert list(result.data["providers"]) == ["public_gateway"]
    assert list(result.data["models"]) == ["public_small"]
    assert result.data["profile"]["roles"] == {"main": "public_small", "small": "public_small"}
    assert result.data["profile"]["agent_options"]["terminal_images"] is False
    assert all(result.data[kind] == {} for kind in ("rules", "skills", "plugins", "mcp"))


@pytest.mark.parametrize("mutation,code", [
  ("version", "version"), ("unknown-table", "schema"), ("unknown-path", "schema"),
  ("unknown-option", "schema"), ("unknown-profile", "reference"),
  ("reserved-inherit", "environment"), ("reserved-values", "environment"),
  ("empty-path", "schema"), ("unsupported-transport", "adapter"),
  ("unsupported-unselected-profile", "adapter"),
])
def test_config_examples_invalid_mutations_fail_redacted(mutation, code, tmp_path, example_framework, capsys):
  text = (EXAMPLES / "multi-profile.example.toml").read_text(encoding="utf-8")
  # 测试内注入秘密 canary；发布示例仍全部为空，任意失败路径都不得回显它。
  text = text.replace('private_gateway_key = ""', f'private_gateway_key = "{CANARY}"')
  if mutation == "version":
    text = text.replace("schema_version = 1", "schema_version = 99", 1)
  elif mutation == "unknown-table":
    text += f'\n[{CANARY}]\nvalue = "{CANARY}"\n'
  elif mutation == "unknown-path":
    text += f'\n[machine.paths]\n{CANARY} = "{CANARY}"\n'
  elif mutation == "unknown-option":
    text = text.replace("terminal_images = false", f'{CANARY} = "{CANARY}"')
  elif mutation == "unknown-profile":
    text += f'\n[overrides.profiles.{CANARY}]\nmcp = []\n'
  elif mutation == "reserved-inherit":
    text += '\n[machine.environment]\ninherit = ["EXAMPLE_GATEWAY_KEY"]\n'
  elif mutation == "reserved-values":
    text += f'\n[machine.environment.values]\nDSH_HOME = "{CANARY}"\n'
  elif mutation == "empty-path":
    text += '\n[machine.paths]\nstate_root = ""\n'
  elif mutation == "unsupported-transport":
    text = text.replace('transport = "http"', f'transport = "{CANARY}"')
  else:
    # 保留默认选择 dsh-default，错误来自未选择的 dsh-ssh。
    text = text.replace("[overrides.profiles.dsh-ssh.roles]",
                        f'[overrides.profiles.dsh-ssh.roles]\n{CANARY} = "public_small"')
  path = tmp_path / "invalid-local.toml"
  path.write_text(text, encoding="utf-8")
  before = path.read_bytes()
  sources, context, _ = example_framework
  with pytest.raises(schema.ConfigError) as caught:
    local, _ = config.load_local(path, adapter_schemas=context)
    catalog = config.load_sources(sources, adapter_schemas=context)
    config.resolve_config(catalog, local, adapter_schemas=context)
  assert caught.value.code == code
  assert caught.value.path
  assert caught.value.__context__ is None
  output = "".join(traceback.format_exception(caught.value)) + repr(caught.value) + repr(capsys.readouterr())
  for private in (CANARY, "gateway.example.invalid", "fictional-private-chat", str(path)):
    assert private not in output
  assert path.read_bytes() == before


def test_config_examples_init_local_and_production_cli_are_runnable(example_framework, capsys):
  assert cli.main(["init-local", "--machine", "example-init"]) == 0
  path = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines/example-init.toml"
  sources, context, adapter = example_framework
  local, _ = config.load_local(path, adapter_schemas=context)
  catalog = config.load_sources(sources, adapter_schemas=context)
  result = config.resolve_config(catalog, local, adapter_schemas=context)
  assert adapter.render(result.data)
  assert stat.S_IMODE(path.stat().st_mode) == 0o600
  for command in ("validate", "render"):
    assert cli.main(["--local", str(path), command]) == 0
    assert "尚未实现" not in capsys.readouterr().err
  # 注入的测试 adapter 不使生产 dsh 身份受支持。
  catalog.profiles["dsh-default"]["agent"] = "dsh"
  with pytest.raises(schema.ConfigError) as caught:
    config.resolve_config(catalog, local, adapter_schemas=context)
  assert caught.value.code == "adapter-schema"
