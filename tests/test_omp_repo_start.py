import pytest

from agentcfg import deployment, runtime
from agentcfg.storage import Conflict

from test_omp_adapter import REPO
from test_omp_runtime_foundation import clear_omp_identity_environment, runtime_workspace


@pytest.mark.parametrize("project_resources", [False, True])
def test_managed_run_ignores_disabled_provider_shape_of_real_repository(
    tmp_path, monkeypatch, fake_subprocess, project_resources):
  clear_omp_identity_environment(monkeypatch)
  workspace, lock = runtime_workspace(tmp_path)
  if project_resources:
    discovery = workspace.resolved.data["profile"]["agent_options"]["discovery"]
    discovery.update(project_resources=True, project_roots=[str(REPO)])
    candidate = workspace.adapter.render(workspace.resolved.data)
    with workspace.adapter.apply_lifecycle_guard(workspace):
      deployment.apply(workspace.instance, workspace.state_root,
        type("Candidate", (), {"generation": "repo-shape", "artifacts": candidate})(),
        workspace.binding, runtime.record(workspace, lock))
    workspace.backend.read_lock = lambda repository: lock
  fake_subprocess.queue(returncode=0)
  assert runtime.run(workspace, cwd=REPO) == 0
  assert len(fake_subprocess.calls) == 1


@pytest.mark.parametrize("relative", [
  ".env", "TITLE_SYSTEM.md", ".omp/.env", ".omp/AGENTS.md", ".omp/extensions/outside.ts",
  ".omp/hooks/outside.ts", ".omp/tools/outside.ts", ".omp/agents/outside.md", ".omp/config.yml",
])
def test_managed_run_still_rejects_direct_native_project_sources(
    tmp_path, monkeypatch, fake_subprocess, relative):
  clear_omp_identity_environment(monkeypatch)
  project = tmp_path / "project"
  project.mkdir()
  path = project / relative
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text("must-not-load")
  workspace, _ = runtime_workspace(tmp_path / "workspace")
  with pytest.raises(Conflict):
    runtime.run(workspace, cwd=project)
  assert not fake_subprocess.calls
