"""init-local 按目标 profile 推导并幂等补齐私人占位。"""

import os
from pathlib import Path
import time
import tomllib

import pytest

from agentcfg import cli
from agentcfg.local import initialize_local
from agentcfg.storage import Conflict, Tree


def paths(machine="work"):
  root = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg"
  return root / "machines" / f"{machine}.toml", root / "secrets.toml"


def test_new_omp_kernel_has_two_urls_and_five_keys():
  result = initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"],
    profile_id="omp-kernel")
  machine_path, shared_path = paths()
  machine = tomllib.loads(machine_path.read_text())
  shared = tomllib.loads(shared_path.read_text())
  assert machine["local_values"] == {"tf_openai_url": "", "tf_anthropic_url": ""}
  assert set(shared["shared"]) == {"deepseek_key", "kimi_key", "glm_key"}
  assert shared["providers"] == {
    "kimi_tf": {"omp_kimi_tf_key": ""}, "zhipu_tf": {"omp_zhipu_tf_key": ""}}
  assert set(result.secret_fields) == {
    "deepseek_key", "kimi_key", "glm_key", "omp_kimi_tf_key", "omp_zhipu_tf_key"}


def test_existing_preserves_values_comments_default_and_adapter_override():
  machine_path, _ = paths()
  initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  source = '''schema_version = 1
# keep top
[machine]
id = "work"
default_profile = "dsh-default" # keep default

[local_values]
tf_openai_url = "https://existing.invalid/v1" # keep URL

[overrides.profiles.omp-kernel.agent_options.ui]
theme_dark = "kanagawa"
'''
  machine_path.write_text(source, encoding="utf-8")
  result = initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"],
    profile_id="omp-kernel")
  content = machine_path.read_text()
  document = tomllib.loads(content)
  assert result.profile == "omp-kernel" and result.machine_action == "supplemented"
  assert document["machine"]["default_profile"] == "dsh-default"
  assert document["local_values"]["tf_openai_url"] == "https://existing.invalid/v1"
  assert document["local_values"]["tf_anthropic_url"] == ""
  assert "# keep top" in content and "# keep URL" in content and "# keep default" in content
  assert document["overrides"]["profiles"]["omp-kernel"]["agent_options"]["ui"]["theme_dark"] == "kanagawa"


def test_repeat_is_byte_and_mtime_idempotent():
  initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"], profile_id="omp-kernel")
  machine_path, shared_path = paths()
  before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in (machine_path, shared_path)]
  time.sleep(0.002)
  result = initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  after = [(path.read_bytes(), path.stat().st_mtime_ns) for path in (machine_path, shared_path)]
  assert result.profile == "omp-kernel"
  assert (result.machine_action, result.secrets_action) == ("unchanged", "unchanged")
  assert after == before


def test_literal_provider_url_needs_no_local_placeholder():
  machine_path, _ = paths()
  initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  machine_path.write_text('''schema_version = 1
[machine]
id = "work"
default_profile = "omp-kernel"

[overrides.providers.kimi_tf]
base_url = "https://literal.invalid/v1"
''', encoding="utf-8")
  initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  values = tomllib.loads(machine_path.read_text())["local_values"]
  assert values == {"tf_anthropic_url": ""}


def test_multiple_machines_share_keys_without_overwriting_values():
  initialize_local("first", config_home=os.environ["XDG_CONFIG_HOME"])
  _, shared_path = paths("first")
  content = shared_path.read_text().replace('deepseek_key = ""', 'deepseek_key = "kept"')
  shared_path.write_text(content, encoding="utf-8")
  initialize_local("second", config_home=os.environ["XDG_CONFIG_HOME"], profile_id="omp-kernel")
  shared = tomllib.loads(shared_path.read_text())
  assert shared["shared"]["deepseek_key"] == "kept"
  assert set(shared["providers"]) == {"kimi_tf", "zhipu_tf"}


def test_legacy_shared_and_inline_declarations_are_not_duplicated():
  machine_path, shared_path = paths()
  initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  machine_path.write_text('''schema_version = 1
[machine]
id = "work"
default_profile = "dsh-default"
[secrets]
kimi_key = ""
glm_key = "inline-kept"
''', encoding="utf-8")
  shared_path.write_text('''schema_version = 1
[secrets]
deepseek_key = "legacy-kept"
''', encoding="utf-8")
  result = initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  assert result.secret_fields == ()
  assert tomllib.loads(shared_path.read_text()) == {
    "schema_version": 1, "secrets": {"deepseek_key": "legacy-kept"}}


def test_inline_declarations_still_create_empty_shared_file():
  initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  machine_path, shared_path = paths()
  shared_path.unlink()
  machine_path.write_text('''schema_version = 1
[machine]
id = "work"
[secrets]
deepseek_key = ""
kimi_key = ""
glm_key = ""
''', encoding="utf-8")
  result = initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  assert result.secrets_action == "created"
  assert tomllib.loads(shared_path.read_text()) == {"schema_version": 1, "shared": {}}


@pytest.mark.parametrize("failure", ["schema", "permission", "duplicate"])
def test_invalid_shared_candidate_never_changes_machine(failure):
  initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  machine_path, shared_path = paths()
  machine_path.write_text('''schema_version = 1
[machine]
id = "work"
default_profile = "omp-kernel"
''', encoding="utf-8")
  before = machine_path.read_bytes()
  if failure == "schema":
    shared_path.write_text("schema_version = 2\n", encoding="utf-8")
  elif failure == "permission":
    shared_path.chmod(0o640)
  else:
    machine_path.write_text(machine_path.read_text() + '[secrets]\ndeepseek_key = "inline"\n',
      encoding="utf-8")
    before = machine_path.read_bytes()
    shared_path.write_text('schema_version = 1\n[shared]\ndeepseek_key = "shared"\n', encoding="utf-8")
  with pytest.raises(Exception) as caught:
    initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  assert caught.value.exit_code in (2, 4)
  assert machine_path.read_bytes() == before


def test_machine_commit_failure_rolls_back_new_shared_file(monkeypatch):
  machine_path, shared_path = paths()
  original = Tree.write_new
  def fail_machine(self, path, data):
    if self.root == machine_path.parent and path == machine_path.name:
      raise OSError("synthetic machine failure")
    return original(self, path, data)
  monkeypatch.setattr(Tree, "write_new", fail_machine)
  with pytest.raises(Exception) as caught:
    initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  assert caught.value.exit_code == 6
  assert not machine_path.exists() and not shared_path.exists()


def test_shared_rollback_cas_preserves_concurrent_update(monkeypatch):
  machine_path, shared_path = paths()
  original = Tree.write_new
  concurrent = b'schema_version = 1\n[shared]\ndeepseek_key = "concurrent"\n'
  def race_machine(self, path, data):
    if self.root == machine_path.parent and path == machine_path.name:
      shared_path.write_bytes(concurrent)
      raise OSError("synthetic machine failure")
    return original(self, path, data)
  monkeypatch.setattr(Tree, "write_new", race_machine)
  with pytest.raises(Conflict, match="回滚发生冲突"):
    initialize_local("work", config_home=os.environ["XDG_CONFIG_HOME"])
  assert shared_path.read_bytes() == concurrent
  assert not machine_path.exists()


@pytest.mark.parametrize("content", [b"not = [valid", b"schema_version = 2\n"])
def test_bad_existing_machine_is_usage(content):
  machine_path, _ = paths()
  machine_path.parent.mkdir(parents=True, mode=0o700)
  machine_path.parent.parent.chmod(0o700)
  machine_path.write_bytes(content)
  machine_path.chmod(0o600)
  assert cli.main(["init-local", "--machine", "work"]) == 2
