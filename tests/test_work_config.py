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
