"""状态增强全关与迟到/子任务提示均不改变项目/用途控制。"""

from agentcfg.process import environment
from termcfg.herdr import Deadline
from termcfg.work import enter_project, open_role
from termcfg.work_config import WorkSettings
from work_helpers import FakeHerdr


def test_agent_environment_does_not_implicitly_inherit_control_socket(monkeypatch):
  for name in ("HERDR_ENV", "HERDR_PANE_ID", "HERDR_BIN_PATH", "HERDR_SOCKET_PATH"):
    monkeypatch.setenv(name, "synthetic")
  env = environment({"environment": {"inherit": []}})
  assert not any(key.startswith("HERDR_") for key in env)
  chosen = environment({"environment": {"inherit": ["HERDR_PANE_ID"]}})
  assert chosen["HERDR_PANE_ID"] == "synthetic"
  assert "HERDR_SOCKET_PATH" not in chosen


def test_all_status_off_core_roles_work_and_untrusted_status_cannot_change_target(tmp_path, monkeypatch):
  api = FakeHerdr(deadline=Deadline())
  ws = enter_project(api, tmp_path)
  caller = next(iter(api.panes))
  settings = WorkSettings(tmp_path / "local", "herdr", "main")
  monkeypatch.setattr("termcfg.work.prepare_tool", lambda *a: ["/synthetic/tool"])
  for role in ("build", "debug", "edit", "pi", "codex", "dsh"):
    primary = open_role(api, settings, role, caller_id=caller)
    extra = open_role(api, settings, role, new=True, caller_id=caller)
    for name in (primary["pane_id"], extra["pane_id"]):
      api.panes[name]["agent_status"] = "idle"
      api.panes[name]["agent_session"] = {"session_id": "synthetic-child-or-delayed-root"}
    result = open_role(api, settings, role, caller_id=caller)
    assert result["pane_id"] == primary["pane_id"]
    assert result["pane_id"] != extra["pane_id"]
  assert len(api.workspaces) == 1 and len(api.panes) == 13
  assert not any("send" in method or "close" in method or method.startswith("agent.") for method, _ in api.requests)


def test_managed_agent_reapplies_environment_filter_before_host_exec(tmp_path):
  from agentcfg.adapter import LaunchSpec
  from agentcfg.execution_environment import prepare, apply_bindings
  spec = LaunchSpec(("fixture-agent",), tmp_path, "fixture-lock", (), environment_policy="caller")
  caller = {"HOME": str(tmp_path), "API_KEY": "SYNTHETIC_CREDENTIAL_CANARY",
    "ROTOM_TEST_TERMINAL_CUSTOM": "synthetic-terminal-setting",
    "HERDR_SOCKET_PATH": "/synthetic/socket"}
  result = apply_bindings(prepare(spec, {"environment": {"inherit": []}}, caller=caller), spec)
  assert result == {"HOME": str(tmp_path)}
  declared = {"environment": {"inherit": ["ROTOM_TEST_TERMINAL_CUSTOM"]}}
  result = apply_bindings(prepare(spec, declared, caller=caller), spec)
  assert result["ROTOM_TEST_TERMINAL_CUSTOM"] == "synthetic-terminal-setting"
  assert "API_KEY" not in result and "HERDR_SOCKET_PATH" not in result
