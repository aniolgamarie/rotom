"""共享凭据分组保持全局引用语义、局部编辑和失败回滚。"""

import os
from pathlib import Path
import tomllib

import pytest

from agentcfg.adapter import SecretRef
from agentcfg.schema import ConfigError
from agentcfg.secret_files import (
  _flatten_credentials,
  credential_section,
  load_secrets,
  read_secrets_document,
  save_shared_key,
  section_label,
)
from agentcfg.storage import Conflict


CANARY = "PRIVATE-GROUP-CANARY"


def machine():
  return Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines/default.toml"


def shared():
  return Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/secrets.toml"


def write_shared(content):
  shared().parent.mkdir(parents=True, mode=0o700)
  shared().write_text(content, encoding="utf-8")
  shared().chmod(0o600)


def test_missing_document_defaults_to_shared():
  assert read_secrets_document(shared()) == {"schema_version": 1, "shared": {}}


def test_mixed_groups_flatten_without_changing_runtime_reference():
  write_shared(f'''schema_version = 1
[secrets]
legacy_key = "legacy"
[shared]
kimi_key = "{CANARY}"
[providers.private_gateway]
private_gateway_key = "provider"
''')
  document = read_secrets_document(shared())
  assert _flatten_credentials(document) == {
    "legacy_key": "legacy", "kimi_key": CANARY, "private_gateway_key": "provider"}
  store = load_secrets({}, machine())
  assert store.resolve(SecretRef("secret:kimi_key")) == CANARY
  assert store.resolve(SecretRef("secret:private_gateway_key")) == "provider"


@pytest.mark.parametrize("content", [
  'schema_version = 1\nunknown = "PRIVATE-GROUP-CANARY"\n[shared]\n',
  'schema_version = 1\n[providers."bad/id"]\nkey = "PRIVATE-GROUP-CANARY"\n',
  'schema_version = 1\n[providers.good]\nkey = ["PRIVATE-GROUP-CANARY"]\n',
  'schema_version = 2\n[shared]\n',
  'schema_version = 1\nproviders = "PRIVATE-GROUP-CANARY"\n',
])
def test_invalid_group_documents_fail_redacted(content):
  write_shared(content)
  with pytest.raises(ConfigError) as caught:
    read_secrets_document(shared())
  assert CANARY not in str(caught.value)
  assert caught.value.__context__ is None


@pytest.mark.parametrize("content", [
  'schema_version = 1\n[shared]\nsame = ""\n[providers.one]\nsame = "value"\n',
  'schema_version = 1\n[secrets]\nsame = "old"\n[shared]\nsame = "new"\n',
])
def test_duplicate_references_across_groups_have_specific_redacted_error(content):
  write_shared(content)
  with pytest.raises(ConfigError, match="duplicate-credential-reference") as caught:
    read_secrets_document(shared())
  assert caught.value.__context__ is None


def test_new_keys_are_classified_and_existing_legacy_key_stays_put():
  write_shared('schema_version = 1\n# keep note\n[secrets]\nlegacy_key = "old"\n')
  save_shared_key({}, machine(), "legacy_key", "rotated", provider_id="gateway")
  save_shared_key({}, machine(), "kimi_key", CANARY, provider_id="ignored")
  save_shared_key({}, machine(), "gateway_key", "provider", provider_id="gateway")
  data = tomllib.loads(shared().read_text(encoding="utf-8"))
  assert data == {"schema_version": 1, "secrets": {"legacy_key": "rotated"},
    "shared": {"kimi_key": CANARY}, "providers": {"gateway": {"gateway_key": "provider"}}}
  assert "# keep note" in shared().read_text(encoding="utf-8")


def test_updating_provider_key_preserves_every_other_group():
  write_shared('''schema_version = 1
[shared]
kimi_key = "shared"
[providers.one]
one_key = "old"
[providers.two]
two_key = "untouched"
''')
  before = shared().read_text(encoding="utf-8")
  save_shared_key({}, machine(), "one_key", CANARY, provider_id="wrong-provider")
  after = shared().read_text(encoding="utf-8")
  assert tomllib.loads(after)["providers"]["one"]["one_key"] == CANARY
  assert '[providers.two]\ntwo_key = "untouched"' in after
  assert before.replace('one_key = "old"', f'one_key = "{CANARY}"') == after


def test_grouped_write_rolls_back_if_callback_fails():
  write_shared('schema_version = 1\n[providers.gateway]\nkey = "old"\n')
  before = shared().read_bytes()
  def fail():
    raise Conflict("synthetic config conflict")
  with pytest.raises(Conflict, match="synthetic"):
    save_shared_key({}, machine(), "key", CANARY, provider_id="gateway", after_write=fail)
  assert shared().read_bytes() == before


def test_credential_section_and_labels_report_actual_or_expected_group():
  write_shared('''schema_version = 1
[secrets]
legacy_key = "old"
[shared]
kimi_key = "shared"
[providers."private.gateway"]
gateway_key = "provider"
''')
  assert credential_section({}, machine(), "legacy_key") == ("secrets",)
  assert credential_section({}, machine(), "kimi_key", provider_id="x") == ("shared",)
  assert credential_section({}, machine(), "gateway_key") == ("providers", "private.gateway")
  assert credential_section({}, machine(), "new_key", provider_id="new.gateway") == (
    "providers", "new.gateway")
  assert credential_section({}, machine(), "other_key") == ("shared",)
  assert credential_section({"secrets": {"inline_key": "value"}}, machine(), "inline_key") == (
    "inline",)
  assert section_label(("shared",)) == "[shared]"
  assert section_label(("providers", "private.gateway")) == '[providers."private.gateway"]'
  assert section_label(("inline",)) == "旧机器文件 [secrets]"
  assert section_label(("secrets",)) == "[secrets]（旧格式）"
