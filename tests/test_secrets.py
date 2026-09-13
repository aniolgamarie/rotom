"""秘密仅由运行时显式能力解析，不进入普通配置或默认展示。"""

from dataclasses import asdict
import importlib
import json
import pickle
import traceback

import pytest

from agentcfg.adapter import SecretRef


CANARY = 'PRIVATE-CANARY-"\n$()`never-run`'


def api():
  assert importlib.util.find_spec("agentcfg.secrets") is not None, "secret isolation missing"
  return importlib.import_module("agentcfg.secrets")


@pytest.mark.parametrize("value", [CANARY, "", None])
def test_explicit_resolution_is_the_only_secret_access(value):
  secrets = api()
  values = {} if value is None else {"private-key": value}
  store = secrets.SecretStore(values)
  values["private-key"] = "changed-after-construction"
  assert store.resolve(SecretRef("secret:private-key"), required=False) == (value or None)
  if value:
    assert store.resolve(SecretRef("secret:private-key")) == value
  else:
    with pytest.raises(secrets.CredentialError) as caught:
      store.resolve(SecretRef("secret:private-key"))
    assert caught.value.exit_code == 3
    assert "private-key" not in repr(caught.value)
  assert repr(store) == "SecretStore()"
  assert CANARY not in str(store)
  for operation in (vars, dict, list, asdict, json.dumps, pickle.dumps):
    with pytest.raises((TypeError, ValueError)):
      operation(store)


@pytest.mark.parametrize("values", [[], {"bad/key": ""}, {"key": False}, {"key": []}])
def test_invalid_secret_map_is_redacted(values):
  secrets = api()
  with pytest.raises(secrets.CredentialError) as caught:
    secrets.SecretStore(values)
  assert caught.value.__context__ is None
  assert "bad/key" not in repr(caught.value)


def test_invalid_runtime_resolution_is_sanitized():
  secrets = api()
  store = secrets.SecretStore({})
  for reference, required in ((CANARY, True), (SecretRef("secret:key"), 1)):
    with pytest.raises(secrets.CredentialError) as caught:
      store.resolve(reference, required=required)
    assert CANARY not in str(caught.value)


@pytest.mark.parametrize("value", [CANARY, "", "rotated", "秘密"])
def test_secret_mutations_leave_general_config_identical(tmp_path, value, capsys):
  api()
  config = importlib.import_module("agentcfg.config")
  text = 'schema_version = 1\n[machine]\nid = "private-machine"\n'
  path = tmp_path / "local.toml"
  path.write_text(text)
  baseline, _ = config.load_local(path)
  path.write_text(text + "[secrets]\nprivate_key = " + json.dumps(value, ensure_ascii=False) + "\n")
  local, store = config.load_local(path)
  assert local == baseline
  assert local.data == {"schema_version": 1, "machine": {"id": "private-machine"}}
  assert value not in repr(local) if value else True
  assert "private-machine" not in repr(local)
  assert store.resolve(SecretRef("secret:private_key"), required=False) == (value or None)
  assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("secrets_text", ['[secrets]\n"PRIVATE-CANARY-key" = 1\n',
                                         'secrets = ["PRIVATE-CANARY-key"]\n'])
def test_invalid_local_secrets_never_reach_schema_error_context(tmp_path, secrets_text):
  api()
  config = importlib.import_module("agentcfg.config")
  schema = importlib.import_module("agentcfg.schema")
  path = tmp_path / "private.toml"
  path.write_text("schema_version = 1\n" + secrets_text + '\n[machine]\nid = "m"\n')
  with pytest.raises(schema.ConfigError) as caught:
    config.load_local(path)
  assert caught.value.__context__ is None
  assert "PRIVATE-CANARY" not in "".join(traceback.format_exception(caught.value))
