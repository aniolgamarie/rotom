"""两组路径下使用真实 Pi 适配器与完整虚构依赖锁；宿主和安装器均为替身。"""

import json
from pathlib import Path
import shutil

import pytest

from agentcfg import cli, commands, workspace
from agentcfg.pi import PiAdapter
from agentcfg.pi_dependencies import recipe_digest
from agentcfg.storage import ensure_private
from test_pi_dependencies import fixture_repository, payload, digest, fake_installer


ROOT = Path(__file__).resolve().parents[1]


def fixture_workspace(tmp_path, monkeypatch):
  root, manifest = fixture_repository(tmp_path)
  for name in ("agent.toml", "plugins.toml", "bindings.toml"):
    shutil.copyfile(ROOT / "agents/pi" / name, root / "agents/pi" / name)
  for name in ("templates", "roles", "themes", "runtime"):
    shutil.copytree(ROOT / "agents/pi" / name, root / "agents/pi" / name, ignore=shutil.ignore_patterns("tests"))
  registry = root / "shared/content.toml"
  registry.parent.mkdir()
  registry.write_text('''schema_version = 1
[providers.fixture]
protocol = "openai-compatible"
base_url = "https://example.invalid/v1"
auth_kind = "api-key"
credential_ref = "secret:fixture"
[models.main]
provider = "fixture"
remote_id = "fictional-main"
input = ["text"]
[skills.fixture-skill]
path = "shared/skills/fixture-skill"
''')
  skill = root / "shared/skills/fixture-skill"
  skill.mkdir(parents=True)
  (skill / "SKILL.md").write_text("---\nname: fixture-skill\ndescription: Synthetic fixture only\n---\nRead local fixture files.\n")
  (skill / "reference.txt").write_text("complete relative resource")
  profiles = root / "profiles"
  profiles.mkdir()
  (profiles / "pi-fixture.toml").write_text('''schema_version=1
id="pi-fixture"
agent="pi"
providers=["fixture"]
models=["main"]
plugins=[]
skills=["fixture-skill"]
rules=[]
mcp=[]
[roles]
main="main"
scout="main"
[agent_options.resources]
roles=["scout"]
prompts=[]
themes=["everforest-dark"]
extensions=[]
''')
  manifest["recipe_digest"] = recipe_digest(root)
  manifest.pop("identity")
  manifest["identity"] = digest(manifest)
  (root / "locks/pi/manifest.json").write_bytes(payload(manifest))
  local_root = tmp_path / "private"
  ensure_private(local_root)
  local = local_root / "machine.toml"
  local.write_text('schema_version=1\n[machine]\nid="fixture"\ndefault_profile="pi-fixture"\n'
    + '[machine.paths]\n' + '\n'.join(key + '=' + json.dumps(str(tmp_path / key)) for key in ("instances_root", "state_root", "cache_root"))
    + '\n[secrets]\nfixture="synthetic-fixture-secret"\n')
  local.chmod(0o600)
  monkeypatch.setattr(workspace, "ADAPTER_TYPES", {"pi": PiAdapter})
  original = workspace.load_workspace
  monkeypatch.setattr(commands, "load_workspace", lambda path, profile=None, **kw: original(path, profile, **{**kw, "repository": root}))
  return local, original(local, repository=root)


@pytest.mark.parametrize("name", ["first-path", "中文 空格 relocated"])
def test_full_pi_fixture_pipeline(name, tmp_path, monkeypatch, capsys, fake_subprocess):
  import agentcfg.pi_dependencies as dependencies
  directory = tmp_path / name
  directory.mkdir()
  local, w = fixture_workspace(directory, monkeypatch)
  installs = []
  monkeypatch.setattr(dependencies, "checked", fake_installer(installs))
  args = ["--local", str(local)]
  for command in ("validate", "render", "plan", "sync", "apply"):
    assert cli.main([*args, command]) == 0
  assert cli.main([*args, "apply"]) == 0
  result = json.loads(capsys.readouterr().out.splitlines()[-1])
  assert result["changes"] == 0
  assert cli.main([*args, "doctor"]) == 0
  diagnosis = json.loads(capsys.readouterr().out.splitlines()[-1])
  assert diagnosis["platform_evidence"] == "not-recorded"
  assert diagnosis["capabilities"][0]["dependencies"] == "installed"
  manifest = json.loads((w.instance / "pi-home/agentcfg-manifest.json").read_bytes())
  assert manifest["engine"] == "node"
  assert manifest["plugins"] == []
  assert manifest["resources"]["roles"] == ["pi-home/agents/scout.md"]
  assert (w.instance / "pi-home/skills/fixture-skill/reference.txt").read_text() == "complete relative resource"
  assert not (w.instance / "codex-home").exists()
  fake_subprocess.queue(returncode=0, stdout="v24.14.0")
  fake_subprocess.queue(returncode=17)
  cwd = directory / "business"
  cwd.mkdir()
  assert cli.main([*args, "run", "pi", "--cwd", str(cwd), "--", "-p", "a b"]) == 17
  call = fake_subprocess.calls[-1]
  assert call["cwd"] == cwd
  assert call["argv"][-2:] == ["-p", "a b"]
  assert call["env"]["HOME"] == str(w.instance / "user-home")
  assert call["env"]["PI_CODING_AGENT_DIR"] == str(w.instance / "pi-home")
  assert "synthetic-fixture-secret" not in (w.state_root / "deployment.json").read_text()
  before = len(fake_subprocess.calls)
  assert cli.main([*args, "run", "pi", "--", "-e", "npm:undeclared"]) == 2
  assert len(fake_subprocess.calls) == before


def test_agent_profile_mismatch_fails_before_installer(tmp_path, monkeypatch):
  local, _ = fixture_workspace(tmp_path, monkeypatch)
  assert cli.main(["--local", str(local), "lock", "--agent", "dsh"]) == 2
  assert cli.main(["--local", str(local), "run", "dsh"]) == 2


def test_pi_missing_secret_and_damaged_runtime_fail_before_host(tmp_path, monkeypatch, fake_subprocess):
  import agentcfg.pi_dependencies as dependencies
  local, w = fixture_workspace(tmp_path, monkeypatch)
  monkeypatch.setattr(dependencies, "checked", fake_installer([]))
  args = ["--local", str(local)]
  assert cli.main([*args, "sync"]) == 0
  assert cli.main([*args, "apply"]) == 0
  local.write_text(local.read_text().replace('fixture="synthetic-fixture-secret"', 'fixture=""'))
  fake_subprocess.queue(returncode=0, stdout="v24.14.0")
  assert cli.main([*args, "run", "pi"]) == 3
  assert len(fake_subprocess.calls) == 1
  lock = w.backend.read_lock(w.repository)
  identity = w.backend.runtime_identity(w, lock)
  (w.backend.root(w, identity) / lock.metadata["profile_slices"][w.profile]["entrypoint"]).unlink()
  assert cli.main([*args, "run", "pi"]) == 5
  assert len(fake_subprocess.calls) == 1


def test_pi_run_rejects_literal_credential_drift_without_host(tmp_path, monkeypatch, fake_subprocess, capsys):
  import agentcfg.pi_dependencies as dependencies
  local, w = fixture_workspace(tmp_path, monkeypatch)
  monkeypatch.setattr(dependencies, "checked", fake_installer([]))
  args = ["--local", str(local)]
  assert cli.main([*args, "sync"]) == 0
  assert cli.main([*args, "apply"]) == 0
  path = w.instance / "pi-home/models.json"
  native = json.loads(path.read_bytes())
  native["providers"]["agentcfg-fixture"]["apiKey"] = "synthetic-literal-drift"
  path.write_text(json.dumps(native))
  assert cli.main([*args, "run", "pi"]) == 4
  assert fake_subprocess.calls == []
  assert "synthetic-literal-drift" not in capsys.readouterr().err


def test_modified_runtime_manifest_cannot_bypass_deployed_permissions(tmp_path, monkeypatch, fake_subprocess):
  import agentcfg.pi_dependencies as dependencies
  local, w = fixture_workspace(tmp_path, monkeypatch)
  monkeypatch.setattr(dependencies, "checked", fake_installer([]))
  args = ["--local", str(local)]
  assert cli.main([*args, "sync"]) == 0
  assert cli.main([*args, "apply"]) == 0
  path = w.instance / "pi-home/agentcfg-manifest.json"
  value = json.loads(path.read_bytes())
  value["plugins"] = ["unselected"]
  path.write_text(json.dumps(value))
  assert cli.main([*args, "run", "pi"]) == 4
  assert fake_subprocess.calls == []
