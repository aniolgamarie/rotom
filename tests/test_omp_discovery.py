import json
from pathlib import Path

import pytest

from agentcfg import deployment, runtime
from agentcfg.omp import OmpAdapter
from agentcfg.omp_discovery import DISABLED_PROVIDERS, SourcePolicy, assert_native_sources, inspect_project_sources
from agentcfg.omp_identity import native_identity
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict

from test_omp_adapter import REPO, omp_data
from test_omp_runtime_foundation import clear_omp_identity_environment, runtime_workspace


@pytest.fixture(autouse=True)
def stable_discovery_names(monkeypatch, tmp_path):
  # 宿主/tmp中的测试编排目录不是合成项目的一部分；保留本组实际覆盖的固定入口。
  monkeypatch.setattr("agentcfg.omp_discovery.DISCOVERY_NAMES",
    (".omp", ".agent", "AGENTS.md", "TITLE_SYSTEM.md", ".env"))
  monkeypatch.setattr("agentcfg.omp_discovery.source_present",
    lambda path: (path == tmp_path or path.is_relative_to(tmp_path)) and (path.exists() or path.is_symlink()))


def policy(root):
  return SourcePolicy.from_options({"project_resources": True, "project_roots": [str(root)]})


def test_project_opt_in_accepts_only_declared_skill_tree_and_reports_digests(tmp_path):
  project = tmp_path / "project"
  skill = project / ".omp/skills/review"
  skill.mkdir(parents=True)
  (skill / "SKILL.md").write_text("# review\n")
  report = inspect_project_sources(project, policy(project), managed_mcp_ids=())
  assert report == ({"category": "skill", "path": str(skill),
    "sha256": report[0]["sha256"]},)
  assert len(report[0]["sha256"]) == 64


def test_project_skill_can_be_declared_at_cwd_ancestor(tmp_path):
  root = tmp_path / "project"
  cwd = root / "src/sub"
  skill = root / ".omp/skills/review"
  cwd.mkdir(parents=True)
  skill.mkdir(parents=True)
  (skill / "SKILL.md").write_text("# review\n")
  assert inspect_project_sources(cwd, policy(root), managed_mcp_ids=())[0]["path"] == str(skill)


def test_declared_root_does_not_hide_generic_source_above_it(tmp_path):
  root = tmp_path / "project"
  cwd = root / "src"
  cwd.mkdir(parents=True)
  (tmp_path / ".env").write_text("MUST_NOT_LOAD=1")
  with pytest.raises(Conflict, match="未声明"):
    inspect_project_sources(cwd, policy(root), managed_mcp_ids=())


@pytest.mark.parametrize("relative", [".env", "AGENTS.md", ".omp/settings.json", ".omp/prompts/x.md",
  ".omp/extensions/x.ts", ".omp/RULES.md"])
def test_project_opt_in_does_not_allow_generic_dotenv_or_unsupported_omp_sources(tmp_path, relative):
  project = tmp_path / "project"
  path = project / relative
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text("sentinel")
  with pytest.raises(Conflict):
    inspect_project_sources(project, policy(project), managed_mcp_ids=())


def test_project_root_must_be_cwd_or_ancestor_and_links_are_rejected(tmp_path):
  cwd = tmp_path / "project/sub"
  cwd.mkdir(parents=True)
  other = tmp_path / "other"
  other.mkdir()
  with pytest.raises(Conflict, match="根"):
    inspect_project_sources(cwd, policy(other), managed_mcp_ids=())
  outside = tmp_path / "outside.md"
  outside.write_text("# external")
  skills = (tmp_path / "project/.omp/skills")
  skills.mkdir(parents=True)
  (skills / "linked").symlink_to(outside)
  with pytest.raises(Conflict, match="符号链接"):
    inspect_project_sources(cwd, policy(tmp_path / "project"), managed_mcp_ids=())


def test_project_mcp_is_cwd_only_strict_and_cannot_collide(tmp_path):
  cwd = tmp_path / "project"
  config = cwd / ".omp/mcp.json"
  config.parent.mkdir(parents=True)
  config.write_text(json.dumps({"mcpServers": {"local": {"type": "http", "url": "https://example.invalid/mcp"}}}))
  report = inspect_project_sources(cwd, policy(cwd), managed_mcp_ids=("managed",))
  assert report[0]["category"] == "mcp" and report[0]["path"] == str(config)
  config.write_text(json.dumps({"mcpServers": {"managed": {"type": "http", "url": "https://example.invalid/mcp"}}}))
  with pytest.raises(Conflict, match="MCP"):
    inspect_project_sources(cwd, policy(cwd), managed_mcp_ids=("managed",))
  config.write_text(json.dumps({"mcpServers": {"local": {"type": "http", "url": "https://u:p@example.invalid/mcp"}}}))
  with pytest.raises(Conflict, match="MCP"):
    inspect_project_sources(cwd, policy(cwd), managed_mcp_ids=())


def test_project_stdio_mcp_requires_locked_absolute_python_and_package(tmp_path):
  cwd = tmp_path / "project"
  config = cwd / ".omp/.mcp.json"
  config.parent.mkdir(parents=True)
  python = tmp_path / "python"
  echo = tmp_path / "runtime/packages/echo-mcp/server.py"
  value = {"mcpServers": {"local": {"type": "stdio", "command": str(python), "args": [str(echo), "literal"]}}}
  config.write_text(json.dumps(value))
  report = inspect_project_sources(cwd, policy(cwd), managed_mcp_ids=(), expected_python=python, expected_echo=echo)
  assert report[0]["category"] == "mcp"
  with pytest.raises(Conflict, match="MCP"):
    inspect_project_sources(cwd, policy(cwd), managed_mcp_ids=())
  value["mcpServers"]["local"]["args"][1] = "${TOKEN}"
  config.write_text(json.dumps(value))
  with pytest.raises(Conflict, match="MCP"):
    inspect_project_sources(cwd, policy(cwd), managed_mcp_ids=(), expected_python=python, expected_echo=echo)


def test_project_policy_renders_native_switches_and_conflicts_stay_disabled(tmp_path):
  data = omp_data()
  data["profile"]["agent_options"]["discovery"] = {
    "project_resources": True, "project_roots": [str(tmp_path)]}
  artifacts = OmpAdapter(REPO).render(data)
  values = {item.target.selector: json.loads(item.content) for item in artifacts if item.target.selector}
  assert values["/skills/enablePiProject"] is True
  assert values["/mcp/enableProjectConfig"] is True
  assert values["/disabledProviders"] == list(DISABLED_PROVIDERS)
  assert len(DISABLED_PROVIDERS) == 18
  data["providers"][DISABLED_PROVIDERS[0]] = data["providers"].pop("gateway")
  with pytest.raises(ConfigError, match="disabled-provider"):
    OmpAdapter(REPO).validate(data)


@pytest.mark.parametrize("selected", [False, True])
def test_native_alternate_mcp_file_is_never_implicitly_loaded(tmp_path, selected):
  identity = native_identity("managed", tmp_path / "instance")
  path = (identity.agent_dir if selected else identity.home / ".omp/agent") / ".mcp.json"
  path.parent.mkdir(parents=True)
  path.write_text('{"mcpServers": {}}')
  with pytest.raises(Conflict, match="profile配置来源"):
    assert_native_sources(identity)


def test_runtime_revalidates_allowed_project_content_immediately_before_spawn(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  workspace, lock = runtime_workspace(tmp_path)
  cwd = tmp_path / "project"
  skill = cwd / ".omp/skills/review"
  skill.mkdir(parents=True)
  source = skill / "SKILL.md"
  source.write_text("# safe\n")
  options = workspace.resolved.data["profile"]["agent_options"]["discovery"]
  options.update(project_resources=True, project_roots=[str(cwd)])
  workspace.backend.read_lock = lambda repository: lock
  candidate = workspace.adapter.render(workspace.resolved.data)
  with workspace.adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root,
      type("Candidate", (), {"generation": "project", "artifacts": candidate})(),
      workspace.binding, runtime.record(workspace, lock))
  workspace.backend.mutate = lambda: source.write_text("api_key=must-not-load\n")
  with pytest.raises(Conflict, match="秘密"):
    runtime.run(workspace, cwd=cwd)
  assert not fake_subprocess.calls
