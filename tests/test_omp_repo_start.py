import pytest

from agentcfg import deployment, runtime
from agentcfg.omp_discovery import IGNORED_PROVIDER_SOURCES
from agentcfg.storage import Conflict

from test_omp_runtime_foundation import clear_omp_identity_environment, runtime_workspace


@pytest.mark.parametrize("project_resources", [False, True])
def test_managed_run_ignores_disabled_provider_shape_of_repository(
    tmp_path, monkeypatch, fake_subprocess, project_resources):
  clear_omp_identity_environment(monkeypatch)
  # 真实仓库祖先可能有合法的原生.omp来源；默认测试只使用合成来源形状。
  repository = tmp_path / "repository-shape"
  repository.mkdir()
  for name in IGNORED_PROVIDER_SOURCES:
    source = repository / name
    if name.endswith(".md"):
      source.write_text("# synthetic disabled provider instructions\n")
    else:
      source.mkdir()
      (source / "provider-fixture").write_text("synthetic disabled provider content\n")
  monkeypatch.setattr("agentcfg.omp_discovery.source_present", lambda path:
    path.is_relative_to(tmp_path) and (path.exists() or path.is_symlink()))
  workspace, lock = runtime_workspace(tmp_path)
  if project_resources:
    discovery = workspace.resolved.data["profile"]["agent_options"]["discovery"]
    discovery.update(project_resources=True, project_roots=[str(repository)])
    candidate = workspace.adapter.render(workspace.resolved.data)
    with workspace.adapter.apply_lifecycle_guard(workspace):
      deployment.apply(workspace.instance, workspace.state_root,
        type("Candidate", (), {"generation": "repo-shape", "artifacts": candidate})(),
        workspace.binding, runtime.record(workspace, lock))
    workspace.backend.read_lock = lambda repository: lock
  fake_subprocess.queue(returncode=0)
  assert runtime.run(workspace, cwd=repository) == 0
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
