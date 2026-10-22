"""work普通配置与秘密边界。"""

import os
from pathlib import Path

import pytest

from termcfg.errors import TermcfgError
from termcfg.work_config import read_settings, resolve_executable, check_config_location


def local_file(tmp_path, extra=""):
  parent = tmp_path / "private-config"
  parent.mkdir(mode=0o700)
  path = parent / "machine.toml"
  path.write_text('schema_version = 1\n[machine]\nid = "synthetic"\n'
    '[machine.work]\nherdr_binary = "/opt/herdr/herdr"\nsession = "main"\n' + extra)
  path.chmod(0o600)
  return path


def test_read_settings_does_not_resolve_credentials(tmp_path, monkeypatch):
  from agentcfg.secrets import SecretStore
  monkeypatch.setattr(SecretStore, "resolve", lambda *a, **k: pytest.fail("secret read"))
  settings = read_settings(local=local_file(tmp_path))
  assert settings.session == "main"
  assert settings.codex_daemon is False
  assert settings.selectors == ("--local", str(settings.local_path))
  assert "opt/herdr" not in repr(settings)


@pytest.mark.parametrize("extra", ['token = "forbidden"\n', 'session2 = "x"\n',
  'codex_daemon = "false"\n', 'pi_profile = ""\n'])
def test_unknown_or_invalid_work_fields_fail(tmp_path, extra):
  with pytest.raises(TermcfgError) as error:
    read_settings(local=local_file(tmp_path, extra))
  assert error.value.code == 2


def test_missing_work_and_selector_conflict(tmp_path):
  p = local_file(tmp_path)
  p.write_text('schema_version = 1\n[machine]\nid = "synthetic"\n')
  for kw in ({"local": p}, {"local": p, "machine": "x"}):
    with pytest.raises(TermcfgError) as error:
      read_settings(**kw)
    assert error.value.code == 2


@pytest.mark.parametrize("value", ["codex --no-daemon", "sh;touch sentinel", "../bin/herdr", "$(pwd)"])
def test_executable_is_single_literal(value):
  with pytest.raises(TermcfgError) as error:
    resolve_executable(value)
  assert error.value.code == 2


def test_absolute_executable_can_have_spaces_and_metacharacters(tmp_path):
  p = tmp_path / "中文 $literal executable"
  p.write_text("synthetic")
  p.chmod(0o700)
  assert resolve_executable(str(p)) == str(p.resolve())


def test_config_override_is_explicitly_rejected(tmp_path, monkeypatch):
  monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "different"))
  with pytest.raises(TermcfgError) as error:
    check_config_location()
  assert error.value.code == 2
  monkeypatch.setenv("XDG_CONFIG_HOME", str(Path(os.environ["HOME"]) / ".config"))
  check_config_location()
  monkeypatch.setenv("HERDR_CONFIG_PATH", str(tmp_path / "other.toml"))
  with pytest.raises(TermcfgError):
    check_config_location()


def test_valid_agent_options_override_uses_public_adapter_schemas(tmp_path, monkeypatch):
  from agentcfg.secrets import SecretStore
  monkeypatch.setattr(SecretStore, "resolve", lambda *a, **k: pytest.fail("secret read"))
  path = local_file(tmp_path)
  with path.open("a") as stream:
    stream.write("\n[overrides.profiles.dsh-default.agent_options]\nterminal_images=false\n")
  settings = read_settings(local=path)
  assert settings.session == "main"


def test_plain_settings_never_load_public_catalog(tmp_path, monkeypatch):
  import agentcfg.workspace as workspace
  monkeypatch.setattr(workspace, "load_public_catalog", lambda **kwargs: pytest.fail("unneeded public catalog"))
  assert read_settings(local=local_file(tmp_path)).session == "main"


def test_native_options_retry_same_strict_loader_with_full_context(tmp_path, monkeypatch):
  import agentcfg.config as config
  import agentcfg.workspace as workspace
  from agentcfg.secrets import SecretStore
  monkeypatch.setattr(SecretStore, "resolve", lambda *a, **k: pytest.fail("secret read"))
  path = local_file(tmp_path, '\n[overrides.profiles.dsh-default.agent_options]\nterminal_images=false\n')
  original_load = config.load_local
  original_catalog = workspace.load_public_catalog
  calls, catalogs = [], []
  def load(selected, **kwargs):
    calls.append((selected, kwargs))
    return original_load(selected, **kwargs)
  def catalog(**kwargs):
    result = original_catalog(**kwargs)
    catalogs.append(result[0].adapter_schemas)
    return result
  monkeypatch.setattr(config, "load_local", load)
  monkeypatch.setattr(workspace, "load_public_catalog", catalog)
  assert read_settings(local=path).session == "main"
  assert len(calls) == 2 and len(catalogs) == 1
  assert calls[0] == (path.absolute(), {"load_credentials": False})
  assert calls[1] == (path.absolute(), {"adapter_schemas": catalogs[0], "load_credentials": False})


@pytest.mark.parametrize("code", ["schema", "version", "reference", "path"])
def test_non_adapter_schema_error_never_retries_or_loads_catalog(tmp_path, monkeypatch, code):
  import agentcfg.config as config
  import agentcfg.workspace as workspace
  from agentcfg.schema import ConfigError
  calls = []
  def invalid(*args, **kwargs):
    calls.append(kwargs)
    raise ConfigError(code, ("synthetic",))
  monkeypatch.setattr(config, "load_local", invalid)
  monkeypatch.setattr(workspace, "load_public_catalog", lambda **kwargs: pytest.fail("unexpected schema fallback"))
  with pytest.raises(TermcfgError) as error:
    read_settings(local=local_file(tmp_path))
  assert error.value.code == 2 and calls == [{"load_credentials": False}]


@pytest.mark.parametrize("profile,options", [
  ("unregistered-profile", "terminal_images=false"),
  ("dsh-default", 'terminal_images="false"'),
  ("dsh-default", "unregistered_native_field=true"),
])
def test_invalid_native_override_still_rejected_after_catalog_retry(tmp_path, monkeypatch, profile, options):
  import agentcfg.workspace as workspace
  original = workspace.load_public_catalog
  calls = []
  def catalog(**kwargs):
    calls.append(kwargs)
    return original(**kwargs)
  monkeypatch.setattr(workspace, "load_public_catalog", catalog)
  path = local_file(tmp_path, '\n[overrides.profiles.' + profile + '.agent_options]\n' + options + '\n')
  with pytest.raises(TermcfgError) as error:
    read_settings(local=path)
  assert error.value.code == 2 and len(calls) == 1


@pytest.mark.parametrize("extra", ['token="synthetic"\n', 'codex_daemon="false"\n'])
def test_plain_unknown_fields_fail_without_catalog_fallback(tmp_path, monkeypatch, extra):
  import agentcfg.workspace as workspace
  monkeypatch.setattr(workspace, "load_public_catalog", lambda **kwargs: pytest.fail("unknown field fallback"))
  with pytest.raises(TermcfgError) as error:
    read_settings(local=local_file(tmp_path, extra))
  assert error.value.code == 2


@pytest.mark.parametrize("native", [False, True])
def test_both_paths_keep_secret_loading_deferred(tmp_path, monkeypatch, native):
  import agentcfg.config as config
  monkeypatch.setattr(config, "load_secrets", lambda *args, **kwargs: pytest.fail("secret loading"))
  extra = '\n[overrides.profiles.dsh-default.agent_options]\nterminal_images=false\n' if native else ""
  assert read_settings(local=local_file(tmp_path, extra)).session == "main"


def test_adapter_retry_rechecks_private_permissions(tmp_path, monkeypatch):
  import agentcfg.workspace as workspace
  path = local_file(tmp_path, '\n[overrides.profiles.dsh-default.agent_options]\nterminal_images=false\n')
  original = workspace.load_public_catalog
  def changed(**kwargs):
    result = original(**kwargs)
    path.chmod(0o644)
    return result
  monkeypatch.setattr(workspace, "load_public_catalog", changed)
  with pytest.raises(TermcfgError) as error:
    read_settings(local=path)
  assert error.value.code == 4


@pytest.fixture
def structured_document():
  return {"schema_version": 1, "machine": {"id": "synthetic", "work": {
    "model": "structured-v1", "herdr_binary": "fixture-herdr", "session": "trial",
    "include_rotom": False,
    "sources": [{"id": "projects", "path": "项目 $literal", "mode": "directory", "template": "development"}],
    "templates": {"development": {"order": ["shell"], "initial": "shell", "tab_types": {
      "shell": {"label": "终端", "launcher": "shell", "cwd": {"from": "workspace_start"}}}}},
    "workspaces": [{"kind": "project", "path": "project", "mode": "directory", "template": "development"},
      {"kind": "named", "id": "case-main", "title": "调查", "template": "development", "start_path": "~/cases"}]
  }}}


def structured_local(tmp_path, document):
  import tomlkit
  parent = tmp_path / "structured-private"
  parent.mkdir(mode=0o700)
  (parent / "项目 $literal").mkdir()
  (parent / "project").mkdir()
  (Path(os.environ["HOME"]) / "cases").mkdir(exist_ok=True)
  path = parent / "machine.toml"
  path.write_text(tomlkit.dumps(document))
  path.chmod(0o600)
  return path


def test_structured_settings_use_nonsecret_loader_and_preserve_literal_input(tmp_path, monkeypatch, structured_document):
  from copy import deepcopy
  import agentcfg.config as config
  monkeypatch.setattr(config, "load_secrets", lambda *a, **k: pytest.fail("credentials loaded"))
  before = deepcopy(structured_document)
  settings = read_settings(local=structured_local(tmp_path, structured_document))
  assert settings.model == "structured-v1"
  assert settings.structured["templates"] == structured_document["machine"]["work"]["templates"]
  assert settings.codex_daemon is False and structured_document == before
  assert settings.structured["sources"][0]["path"] == str(settings.local_path.parent / "项目 $literal")
  assert "调查" not in repr(settings)


def test_structured_document_settings_match_file_and_keep_legacy_constructor(tmp_path, structured_document):
  from termcfg.work_config import WorkSettings, settings_from_document
  path = structured_local(tmp_path, structured_document)
  direct = settings_from_document(structured_document, local=path)
  assert direct == read_settings(local=path)
  direct.structured["sources"][0]["path"] = "changed copy"
  assert structured_document["machine"]["work"]["sources"][0]["path"] == "项目 $literal"
  legacy = WorkSettings(path, "fixture-herdr", "main", None, None, None, None, False, tmp_path)
  assert legacy.model is None and legacy.structured is None


@pytest.mark.parametrize("field,value", [("include_rotom", False), ("rotom_template", "development"),
  ("sources", []), ("templates", {}), ("workspaces", [])])
def test_structured_fields_require_explicit_model(tmp_path, field, value):
  from agentcfg.schema import ConfigError, validate_document
  document = {"schema_version": 1, "machine": {"id": "synthetic", "work": {
    "herdr_binary": "fixture-herdr", "session": "main", field: value}}}
  with pytest.raises(ConfigError):
    validate_document("local", document)
  with pytest.raises(TermcfgError) as error:
    read_settings(local=structured_local(tmp_path, document))
  assert error.value.code == 2


@pytest.mark.parametrize("model", ["legacy", "structured-v2", "", False, 2])
def test_unknown_model_never_falls_back(tmp_path, model, structured_document):
  structured_document["machine"]["work"]["model"] = model
  with pytest.raises(TermcfgError) as error:
    read_settings(local=structured_local(tmp_path, structured_document))
  assert error.value.code == 2


@pytest.mark.parametrize("path,value", [
  (("unexpected",), True),
  (("sources", 0, "unexpected"), True),
  (("templates", "development", "unexpected"), True),
  (("templates", "development", "tab_types", "shell", "unexpected"), True),
  (("templates", "development", "tab_types", "shell", "cwd", "unexpected"), True),
  (("workspaces", 0, "unexpected"), True),
  (("workspaces", 1, "unexpected"), True),
  (("sources", 0, "depth"), True), (("sources", 0, "depth"), 0), (("sources", 0, "depth"), 33),
  (("sources", 0, "exclude_hidden"), "false"), (("sources", 0, "follow_symlinks"), 1),
  (("sources", 0, "exclude"), "cache"), (("sources", 0, "exclude"), ["a/b"]),
  (("sources", 0, "mode"), "guess"), (("sources", 0, "path"), ""),
  (("templates", "development", "order"), "shell"),
  (("templates", "development", "initial"), False),
  (("templates", "development", "tab_types", "shell", "launcher"), "sh -c echo"),
  (("templates", "development", "tab_types", "shell", "label"), ""),
  (("templates", "development", "tab_types", "shell", "cwd"), {}),
  (("templates", "development", "tab_types", "shell", "cwd"), {"from": "cwd"}),
  (("templates", "development", "tab_types", "shell", "cwd"), {"from": "workspace_start", "path": "x"}),
  (("templates", "development", "tab_types", "shell", "cwd"), {"path": ""}),
  (("workspaces", 0, "id"), "project-id"), (("workspaces", 0, "title"), "project title"),
  (("workspaces", 1, "path"), "project"), (("workspaces", 1, "mode"), "git"),
  (("workspaces", 1, "kind"), "other"), (("workspaces", 1, "title"), "bad\ncontrol"),
])
def test_structured_nested_shape_and_types_reject_invalid_input(structured_document, path, value):
  from agentcfg.schema import ConfigError, validate_document
  target = structured_document["machine"]["work"]
  for key in path[:-1]:
    target = target[key]
  target[path[-1]] = value
  with pytest.raises(ConfigError):
    validate_document("local", structured_document)


@pytest.mark.parametrize("identifier", ["9starts-digit", "bad.key", "non ASCII 中", "x" * 65, "tail\n"])
@pytest.mark.parametrize("location", ["source", "template", "type", "named"])
def test_structured_new_identifiers_use_ascii_full_match(structured_document, location, identifier):
  from agentcfg.schema import ConfigError, validate_document
  work = structured_document["machine"]["work"]
  if location == "source":
    work["sources"][0]["id"] = identifier
  elif location == "named":
    work["workspaces"][1]["id"] = identifier
  elif location == "template":
    work["templates"][identifier] = work["templates"].pop("development")
  else:
    types = work["templates"]["development"]["tab_types"]
    types[identifier] = types.pop("shell")
  with pytest.raises(ConfigError):
    validate_document("local", structured_document)


@pytest.mark.parametrize("value", ["hidden\x00value", "hidden\x1fvalue", "hidden\x7fvalue", "hidden\x85value", "hidden\ud800value"])
def test_work_literals_reject_controls_and_invalid_unicode_without_echo(value, structured_document, tmp_path):
  from agentcfg.schema import ConfigError, validate_document
  from termcfg.work_config import literal, settings_from_document
  with pytest.raises(TermcfgError) as error:
    literal(value)
  assert error.value.code == 2 and "hidden" not in str(error.value)
  structured_document["machine"]["work"]["workspaces"][1]["title"] = value
  with pytest.raises(ConfigError):
    validate_document("local", structured_document)
  with pytest.raises(TermcfgError) as error:
    settings_from_document(structured_document, local=tmp_path / "machine.toml")
  assert error.value.code == 2 and "hidden" not in str(error.value)


def test_structured_cwd_path_and_existing_profile_identifiers_remain_literal(tmp_path, structured_document):
  work = structured_document["machine"]["work"]
  work["pi_profile"] = "旧 profile"
  work["templates"]["development"]["tab_types"]["shell"]["cwd"] = {"path": "~/项目 $()"}
  settings = read_settings(local=structured_local(tmp_path, structured_document))
  assert settings.pi_profile == "旧 profile"
  assert settings.structured["templates"]["development"]["tab_types"]["shell"]["cwd"]["path"] == "~/项目 $()"


@pytest.mark.parametrize("depth", [1.0, 1.5, True])
@pytest.mark.parametrize("entry", ["load_local", "settings_from_document", "read_settings"])
def test_structured_depth_requires_actual_integer_across_entrypoints(tmp_path, structured_document, depth, entry):
  from agentcfg.config import load_local
  from agentcfg.schema import ConfigError
  from termcfg.work_config import settings_from_document
  structured_document["machine"]["work"]["sources"][0]["depth"] = depth
  path = structured_local(tmp_path, structured_document)
  with pytest.raises(ConfigError if entry == "load_local" else TermcfgError):
    if entry == "load_local":
      load_local(path, load_credentials=False)
    elif entry == "settings_from_document":
      settings_from_document(structured_document, local=path)
    else:
      read_settings(local=path)
