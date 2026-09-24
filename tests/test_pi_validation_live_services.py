"""SDK 服务验收的宿主、凭据解析和回收均使用替身。"""
import json
from types import SimpleNamespace
import subprocess
import pytest

from agentcfg.adapter import EnvironmentBinding, SecretRef
from agentcfg.deployment import json_bytes
from agentcfg.storage import Tree, ensure_private, Conflict
import agentcfg.pi_validation_live_services as live


def fixture(tmp_path):
  runtime, instance, state, project = (tmp_path / name for name in ("runtime", "instance", "state", "project"))
  for path in (runtime, instance, state, project): ensure_private(path)
  with Tree(runtime) as tree: tree.write_new("runtime/service-validation.mjs", b"fixture, never execute")
  with Tree(instance) as tree: tree.write_new("pi-home/agentcfg-manifest.json", json_bytes({"permission_policy": {"schema_version": 1, "default": "deny", "rules": []}}))
  options = {"mcp": {"servers": {"fixture": {}}}, "network": {"routes": {
    "service": {"service_ids": ["mcp:fixture"], "provider_ids": [], "credential_ref": "secret:proxy"},
    "unrelated": {"service_ids": [], "provider_ids": ["other"], "credential_ref": "secret:unrelated-proxy"}}}}
  data = {"profile": {"roles": {"main": "main"}, "mcp": ["fixture"], "agent_options": options}, "plugins": {"pi-mcp": {}},
    "models": {"main": {"provider": "api"}}, "providers": {"api": {"credential_ref": "secret:main"}}, "mcp": {"fixture": {"credential_ref": "secret:mcp"}}}
  workspace = SimpleNamespace(instance=instance, state_root=state, local_path=tmp_path / "local.toml", binding={"profile": "pi-default"}, resolved=SimpleNamespace(data=data))
  return {"workspace": workspace, "runtime": SimpleNamespace(root=runtime, identity="a" * 64, lock_identity="b" * 64, slice_identity="c" * 64, engine="node"),
    "project": project, "item": {"capability_id": "mcp", "scenario_id": "pi-default.live-mcp"}, "identity": {"fixture": True}, "scope_digest": "d" * 64}


@pytest.mark.parametrize("fault", [None, "nonce", "facts", "exit", "physical", "timeout"])
def test_service_runner_keeps_supervision_and_rejects_unmatched_or_incomplete_proof(tmp_path, monkeypatch, fault):
  context = fixture(tmp_path); calls = []
  def execute(workspace, *, cwd, launch_operation, select_environment):
    assert select_environment(EnvironmentBinding("MAIN", SecretRef("secret:main"), True))
    assert select_environment(EnvironmentBinding("MCP", SecretRef("secret:mcp"), True))
    assert not select_environment(EnvironmentBinding("OTHER", SecretRef("secret:unrelated-proxy"), True))
    spec = SimpleNamespace(argv=("/fixture/node", str(context["runtime"].root / "runtime/launch.mjs")), cwd=cwd)
    return launch_operation(workspace, spec, {"HOME": "/fixture/home"}, 42, {}, lifecycle_fd=43)
  class Child:
    attempts = 0
    def __init__(self, argv, **kwargs):
      assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
      assert kwargs["env"]["AGENTCFG_SERVICE_VALIDATION"] == "1"
      assert kwargs["pass_fds"][1:] == (42, 43)
      path = tmp_path / "unused"
      from pathlib import Path
      path = Path(argv[argv.index("--input") + 1])
      document = json.loads(path.read_text())
      result = {"schema_version": 1, "nonce": "wrong" if fault == "nonce" else document["nonce"], "capability": "mcp", "runtime_identity": context["runtime"].identity,
        "status": "passed", "failure_code": None, "facts": {"sdk_session": True, "capability": "mcp", "mcp_servers_verified": 1, "metadata_refreshed": fault != "facts"}}
      with Tree(path.parent) as tree: tree.write_new("service-result.json", json_bytes(result))
      calls.append("spawn")
    def wait(self, **kwargs):
      self.attempts += 1
      if fault == "timeout" and self.attempts == 1: raise subprocess.TimeoutExpired("fixture", 1)
      return 5 if fault == "exit" else 0
  def inactive(_):
    if fault == "physical": raise Conflict("fixture unknown activity")
  monkeypatch.setattr(live, "assert_inactive", inactive)
  result = live.execute_services(context, recheck=lambda: context, execute=execute, popen=Child, cancel=lambda _: calls.append("cancel"))
  assert result["status"] == ("passed" if fault is None else "failed")
  assert calls == (["spawn", "cancel"] if fault == "timeout" else ["spawn"])


def test_missing_service_binding_does_not_resolve_secrets_or_start_host(tmp_path):
  context = fixture(tmp_path)
  context["workspace"].resolved.data["profile"]["mcp"] = []
  result = live.execute_services(context, recheck=lambda: pytest.fail("must not inspect"), execute=lambda *a, **k: pytest.fail("must not execute"))
  assert result["status"] == "not-run" and result["reason"] == "live-mcp-binding-required"


def test_service_proof_requires_real_counts_and_never_accepts_arbitrary_extra_fields():
  facts = {"sdk_session": True, "capability": "mcp", "mcp_servers_verified": 1, "metadata_refreshed": True}
  assert live.service_facts_valid(facts, "mcp", 1)
  assert not live.service_facts_valid(facts, "mcp", 2)
  assert not live.service_facts_valid({**facts, "mcp_servers_verified": True}, "mcp", 1)
  assert not live.service_facts_valid({**facts, "private_response": "do not publish"}, "mcp", 1)


def managed_fixture(tmp_path):
  from test_pi_live_project import make_project
  context = fixture(tmp_path); context["project"].rmdir(); make_project(context["project"])
  context["item"] = {"capability_id": "task-keeper", "scenario_id": "pi-managed.live-direct.inspect-fix-review"}
  context["native_transports"] = ["direct"]
  data = context["workspace"].resolved.data; data["plugins"]["task-keeper"] = {}
  data["profile"]["roles"].update({role: "worker" for role in ("task_keeper_reader", "task_keeper_writer", "task_keeper_reviewer")})
  data["models"]["worker"] = {"provider": "worker-api"}; data["providers"]["worker-api"] = {"credential_ref": "secret:worker"}
  options = data["profile"]["agent_options"]
  options["network"]["routes"]["worker"] = {"mode": "direct", "provider_ids": ["worker-api"]}
  options["task_keeper"] = {"enabled": True, "project_root": "probe", "check_ids": ["test"]}
  options["paths"] = {"roots": {"probe": {"path": str(context["project"]), "purpose": "project"}}}
  return context


@pytest.mark.parametrize("fault", [None, "route", "native", "project", "second-view"])
def test_managed_preflight_requires_own_probe_and_matching_native_transport(tmp_path, fault):
  context = managed_fixture(tmp_path)
  if fault == "route": context["workspace"].resolved.data["profile"]["agent_options"]["network"]["routes"]["worker"]["mode"] = "proxy"
  if fault == "native": context["native_transports"] = []
  if fault == "project": (context["project"] / "code.txt").write_text("business content")
  if fault == "second-view": context["item"]["scenario_id"] = "pi-managed.live-direct.second-view"
  assert (live.service_preflight(context) is None) == (fault is None)
  assert "secret:worker" in live.selected_secrets(context)
  assert "secret:unrelated-proxy" not in live.selected_secrets(context)


def test_managed_facts_need_both_workflows_and_current_checks_and_review():
  facts = {"sdk_session": True, "capability": "task-keeper", "inspect_verified": True, "fix_verified": True,
    "checks_verified": True, "review_verified": True, "second_view_verified": False, "job_count": 2}
  assert live.service_facts_valid(facts, "task-keeper", 2)
  for key in ("inspect_verified", "fix_verified", "checks_verified", "review_verified"):
    assert not live.service_facts_valid({**facts, key: False}, "task-keeper", 2)
