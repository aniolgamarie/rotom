"""启动只使用已部署契约；真实进程由默认隔离 fixture 替代。"""

import json
from pathlib import Path

import pytest

from agentcfg import deployment, runtime
from agentcfg.dependencies import read_lock, runtime_root
from agentcfg.dsh import env_name
from agentcfg.storage import Tree, ensure_private
from agentcfg.workspace import load_workspace


CANARY = 'synthetic-"\n$()`key`'


def local_file(path, provider="one", used=CANARY):
  path.write_text('schema_version=1\n[machine]\nid="runtime"\n'
    f'[overrides.providers.{provider}]\nprotocol="openai-compatible"\nauth_kind="api-key"\n'
    f'base_url="https://{provider}.example.invalid/v1"\ncredential_ref="secret:{provider}"\n'
    f'[overrides.models.{provider}]\nprovider="{provider}"\nremote_id="fictional-model"\ninput=["text"]\n'
    f'[overrides.profiles.dsh-default]\nproviders=["{provider}"]\nmodels=["{provider}"]\n'
    f'[overrides.profiles.dsh-default.roles]\nmain="{provider}"\n'
    f'[secrets]\none={json.dumps(used)}\ntwo="synthetic-unselected"\nunused="synthetic-unused"\n')


def test_run_keeps_deployed_selection_uses_current_secret_and_cwd(tmp_path, fake_subprocess, monkeypatch, capsys, prepared_runtime):
  path = tmp_path / "local.toml"
  local_file(path)
  w = load_workspace(path)
  lock = read_lock(w.repository)
  deployment.apply(w.instance, w.state_root, w.candidate(lock.identity), w.binding, runtime.record(w, lock))
  prepared_runtime(w, lock)
  local_file(path, provider="two", used=CANARY + "rotated")
  changed = load_workspace(path)
  monkeypatch.setenv("UNRELATED_PARENT_SECRET", "synthetic-parent")
  fake_subprocess.queue(returncode=0, stdout=lock.metadata["node"])
  fake_subprocess.queue(returncode=17)
  cwd = tmp_path / "业务 空格"
  cwd.mkdir()
  assert runtime.run(changed, cwd=cwd, arguments=("--native-flag",)) == 17
  assert CANARY + "rotated" not in fake_subprocess.calls[0]["env"].values()
  call = fake_subprocess.calls[-1]
  assert call["cwd"] == cwd
  assert call["env"][env_name("KEY", "one")] == CANARY + "rotated"
  assert env_name("KEY", "two") not in call["env"]
  assert "UNRELATED_PARENT_SECRET" not in call["env"]
  assert "synthetic-unused" not in call["env"].values()
  assert all(CANARY not in arg for arg in call["argv"])
  assert len(call["pass_fds"]) == 1
  assert CANARY not in capsys.readouterr().out
  assert CANARY.encode() not in (w.state_root / "deployment.json").read_bytes()


def test_native_environment_guard_is_a_managed_asset(tmp_path):
  path = tmp_path / "local.toml"
  local_file(path)
  w = load_workspace(path)
  lock = read_lock(w.repository)
  candidate = w.candidate(lock.identity)
  assert any(a.target.path == "env-guard.mjs" for a in candidate.artifacts)
  contract = runtime.record(w, lock)
  assert "--import" in contract["argv"]
  assert contract["shared_files"] == ["dsh-home/settings.yaml"]
