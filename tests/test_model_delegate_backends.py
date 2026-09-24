"""只检查锁定 argv/环境；绝不调用真实 Pi/Codex。"""

import pytest
from pathlib import Path
from agentcfg.model_delegate_backends import backend_environment, codex_command
from agentcfg.model_delegate import selected_route
from agentcfg.schema import ConfigError
from test_model_delegate_contract import request

NATIVE = {"allow_shell": True, "tool_network": "none"}


@pytest.mark.parametrize("preset", ["general", "context", "challenge", "plan", "research", "review", "scout"])
def test_purpose_template_cannot_grant_web_search(preset):
  value = request("codex"); value["preset"] = preset
  permissions = {":root": "deny", ":minimal": "read"}
  argv = codex_command("/fixture/codex", value, "/fixture/output", permissions=permissions, native=NATIVE)
  assert 'web_search="disabled"' in argv and 'web_search="live"' not in argv
  explicit = codex_command("/fixture/codex", value, "/fixture/output", permissions=permissions, native={**NATIVE, "web_search": "live"})
  assert 'web_search="live"' in explicit


def test_codex_argv_has_exact_model_instance_controls_no_shell_or_implicit_last(tmp_path):
  value = request("codex"); value["requested_model"]["model_id"] = "literal model; $(not-a-command)"
  permissions = {":root": "deny", ":minimal": "read", "/fixture/project": "read"}
  argv = codex_command("/frozen/codex", value, tmp_path / "final.md", permissions=permissions, native=NATIVE)
  assert argv[0] == "/frozen/codex" and argv[-1] == "-"
  assert argv[argv.index("--model") + 1] == value["requested_model"]["model_id"]
  assert "--sandbox" not in argv
  assert 'default_permissions="agentcfg-delegate"' in argv
  assert "--ignore-user-config" in argv and "--ignore-rules" in argv
  resumed = codex_command("/frozen/codex", value, tmp_path / "final.md", permissions=permissions, native=NATIVE, resume_token="known-session")
  assert resumed[-3:] == ("resume", "known-session", "-") and "--last" not in resumed
  with pytest.raises(ConfigError):
    codex_command("/frozen/codex", value, tmp_path / "final.md", permissions=permissions, native=NATIVE, resume_token="--last")


def test_environment_never_inherits_global_proxy_auth_home_or_preloads(tmp_path, monkeypatch):
  for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "NODE_OPTIONS", "CODEX_HOME", "OPENAI_API_KEY"):
    monkeypatch.setenv(name, "synthetic-unselected-value")
  direct = backend_environment(home=tmp_path / "worker", instance=tmp_path / "instance", route={"mode": "direct"}, executable="/frozen/codex")
  assert "synthetic-unselected-value" not in str(direct)
  assert "HTTP_PROXY" not in direct and "OPENAI_API_KEY" not in direct
  proxy = backend_environment(home=tmp_path / "worker", instance=tmp_path / "instance", route={"mode": "proxy", "proxy_url": "http://fixture.invalid:9999"}, executable="/frozen/codex")
  assert proxy["HTTPS_PROXY"] == "http://fixture.invalid:9999" and proxy["NO_PROXY"] == ""


def test_codex_event_parser_uses_pinned_native_shape_without_exposing_reasoning_or_commands():
  from agentcfg.model_delegate_backends import CodexEvents
  from agentcfg.storage import Conflict
  parser = CodexEvents()
  assert parser.accept({"type": "thread.started", "thread_id": "fixture-thread"}) == ("ready", "started")
  parser.accept({"type": "turn.started"})
  assert parser.accept({"type": "item.completed", "item": {"id": "thought", "type": "reasoning", "text": "synthetic-private-thought"}}) is None
  parser.accept({"type": "item.started", "item": {"id": "command", "type": "command_execution", "command": "private-command"}})
  parser.accept({"type": "item.completed", "item": {"id": "final", "type": "agent_message", "text": "final"}})
  with pytest.raises(Conflict):
    parser.accept({"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 2}})
  assert parser.accept({"type": "item.completed", "item": {"id": "command", "type": "command_execution", "aggregated_output": "private-output"}}) == ("checkpoint", "tool-completed")
  assert parser.accept({"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 2}}) == ("completed", "turn-completed")
  assert parser.usage["cost"] is None
  with pytest.raises(Conflict): parser.accept({"type": "turn.started"})


def test_codex_permission_profile_cannot_reopen_denials_or_expand_partial_write(tmp_path):
  from agentcfg.model_delegate_backends import codex_permissions
  root = tmp_path / "project"; root.mkdir(); (root / ".git").mkdir(); (root / "private").mkdir(); (root / "private/nested").mkdir()
  runtime = tmp_path / "runtime"; runtime.mkdir()
  home = tmp_path / "codex-home"; home.mkdir()
  scratch = tmp_path / "scratch"; scratch.mkdir()
  read = {"id": "read", "kind": "file", "effect": "allow", "tool_ids": ["tk_read"], "operations": ["read"], "root_ref": "project", "relative_path": ".", "match": "subtree"}
  denied = {**read, "id": "private", "effect": "deny", "relative_path": "private"}
  reopen = {**read, "id": "reopen", "relative_path": "private/nested"}
  policy = {"schema_version": 1, "default": "deny", "rules": [read, denied, reopen]}
  grant = {"execution_mode": "delegate-readonly", "root_bindings": {"project": {"path": str(root)}}}
  result = codex_permissions(policy, grant, runtime_root=runtime, codex_home=home, scratch=scratch, native=NATIVE)
  assert result[str(root)] == "read" and result.get(str(home), result[":root"]) == "deny"
  assert result[str(root / "private")] == "deny" and str(root / "private/nested") not in result
  assert result[str(root / ".git")] == "deny" and result[":root"] == "deny"
  with pytest.raises(ConfigError, match="root-denial-unrepresentable"):
    codex_permissions({**policy, "rules": [read, {**denied, "root_ref": "external"}]}, grant, runtime_root=runtime, codex_home=home, scratch=scratch, native=NATIVE)
  writer = {**read, "id": "write", "tool_ids": ["tk_write"], "operations": ["write"]}
  with pytest.raises(ConfigError, match="unrepresentable"):
    codex_permissions({**policy, "rules": [read, writer]}, {**grant, "execution_mode": "delegate-write"}, runtime_root=runtime, codex_home=home, scratch=scratch, native=NATIVE)


def test_readonly_retries_are_bounded_and_write_can_never_enable_them(tmp_path):
  value = request("codex")
  permissions = {":root": "deny", ":minimal": "read", "/fixture/project": "read"}
  command = codex_command("/frozen/codex", value, tmp_path / "final", permissions=permissions, native=NATIVE, retry_limit=2)
  assert "model_providers.agentcfg-delegate.request_max_retries=2" in command
  assert "model_providers.agentcfg-delegate.stream_max_retries=0" in command
  for retry_limit in (-1, 4, True):
    with pytest.raises(ConfigError): codex_command("/frozen/codex", value, tmp_path / "final", permissions=permissions, native=NATIVE, retry_limit=retry_limit)
  value["mode"] = "implement"
  with pytest.raises(ConfigError): codex_command("/frozen/codex", value, tmp_path / "final", permissions=permissions, native=NATIVE, retry_limit=1)


@pytest.mark.parametrize("name", ["项目😀", 'project.with.dots/quoted\"name', "project=equals"])
def test_native_toml_arguments_preserve_workspace_names_under_cli_key_splitting(tmp_path, name):
  import tomllib
  value = request("codex"); value["cwd"] = str(tmp_path / name)
  permissions = {":root": "deny", ":minimal": "read", value["cwd"]: "read"}
  argv = codex_command("/frozen/codex", value, tmp_path / "final", permissions=permissions, native=NATIVE)
  documents = [tomllib.loads(argv[index + 1]) for index, argument in enumerate(argv[:-1]) if argument == "-c"]
  project = next(row["projects"] for row in documents if "projects" in row)
  assert project[value["cwd"]]["trust_level"] == "untrusted"
  # 与固定 CLI 一样先拆 key/value，再按点拆 key；不能用整段 TOML 解析替代。
  setting = next(item for item in argv if item.startswith("projects="))
  key, encoded = setting.split("=", 1)
  cli_document = tomllib.loads("value=" + encoded)["value"]
  for component in reversed(key.split(".")):
    cli_document = {component: cli_document}
  assert cli_document == {"projects": {value["cwd"]: {"trust_level": "untrusted"}}}
  native = next(row["permissions"] for row in documents if "permissions" in row and "filesystem" in row["permissions"]["agentcfg-delegate"])
  assert native["agentcfg-delegate"]["filesystem"][value["cwd"]] == "read"


def test_controlled_mcp_events_need_owned_server_tool_and_complete_identity_pair():
  from agentcfg.model_delegate_backends import CodexEvents
  from agentcfg.storage import Conflict
  parser = CodexEvents(mcp_tools={"read", "edit"})
  parser.accept({"type": "thread.started", "thread_id": "fixture"})
  parser.accept({"type": "turn.started"})
  item = {"id": "tool-1", "type": "mcp_tool_call", "server": "agentcfg_delegate", "tool": "read", "status": "in_progress",
    "arguments": {"path": "synthetic-private-path"}}
  for replacement in ({"server": "unselected"}, {"tool": "shell"}):
    with pytest.raises(Conflict, match="UNDECLARED"):
      parser.accept({"type": "item.started", "item": {**item, **replacement}})
  with pytest.raises(Conflict, match="EVENT_GAP"):
    parser.accept({"type": "item.completed", "item": {**item, "status": "completed"}})
  assert parser.accept({"type": "item.started", "item": item}) is None
  with pytest.raises(Conflict, match="EVENT_GAP"):
    parser.accept({"type": "item.completed", "item": {**item, "tool": "edit", "status": "completed"}})
  parser.accept({"type": "item.completed", "item": {"id": "answer", "type": "agent_message", "text": "final"}})
  with pytest.raises(Conflict, match="EVENT_GAP"):
    parser.accept({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})
  result = parser.accept({"type": "item.completed", "item": {**item, "status": "failed", "error": {"message": "synthetic-private-error"}}})
  assert result == ("checkpoint", "tool-completed")
  assert "synthetic-private" not in str(result)
  with pytest.raises(Conflict, match="EVENT_REPLAY"):
    parser.accept({"type": "item.completed", "item": {**item, "status": "completed"}})
  assert parser.accept({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}) == ("completed", "turn-completed")


@pytest.mark.parametrize("kind", ["command_execution", "file_change"])
def test_controlled_mcp_never_accepts_native_business_io_as_success(kind):
  from agentcfg.model_delegate_backends import CodexEvents
  from agentcfg.storage import Conflict
  parser = CodexEvents(mcp_tools={"read"})
  parser.accept({"type": "thread.started", "thread_id": "fixture"}); parser.accept({"type": "turn.started"})
  with pytest.raises(Conflict, match="NATIVE_TOOL_FORBIDDEN"):
    parser.accept({"type": "item.completed", "item": {"id": "native", "type": kind}})


def test_native_shell_needs_explicit_authorization_and_stays_inside_native_sandbox(tmp_path):
  from agentcfg.pi_delegate_policy import execution_policy
  from test_pi_delegate import fixture
  _, host, _, _ = fixture(tmp_path)
  host.manifest()["options"]["model_delegate"]["codex"] = {}
  with pytest.raises(ConfigError, match="native-execution-required"):
    execution_policy(host.manifest(), "codex")
  value = request("codex"); permissions = {":root": "deny", ":minimal": "read"}
  with pytest.raises(ConfigError): codex_command("/frozen/codex", value, tmp_path / "out", permissions=permissions)
  argv = codex_command("/frozen/codex", value, tmp_path / "out", permissions=permissions,
    native={"allow_shell": False, "tool_network": "none"})
  assert "features.shell_tool=false" in argv and "permissions.agentcfg-delegate.network.enabled=false" in argv
  assert not any("mcp_servers" in item or "pi-delegate-mcp" in item for item in argv)


def test_native_machine_root_limits_are_never_silently_ignored(tmp_path):
  from agentcfg.pi_delegate_policy import execution_policy
  from test_pi_delegate import fixture
  _, host, _, _ = fixture(tmp_path)
  host.manifest()["options"]["model_delegate"]["codex"] = {"native_execution": NATIVE}
  for name in ("readonly_roots", "denied_roots"):
    host.manifest()["options"]["permissions"] = {name: ["project"]}
    value = execution_policy(host.manifest(), "codex")
    assert value["root_limits"][name] == ["project"]
    assert value["root_limits"]["bindings"]["project"]["identity"]
def test_codex_pre_turn_nonfatal_notice_is_not_execution_or_completion():
  from agentcfg.model_delegate_backends import CodexEvents
  from agentcfg.storage import Conflict
  import pytest
  decoder = CodexEvents()
  notice = {"type": "item.completed", "item": {"id": "notice", "type": "error", "message": "synthetic private diagnostic"}}
  with pytest.raises(Conflict): decoder.accept(notice)
  decoder.accept({"type": "thread.started", "thread_id": "fixture-thread"})
  assert decoder.accept(notice) is None
  assert not decoder.started and not decoder.completed and not decoder.active
  with pytest.raises(Conflict): decoder.accept({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})
  decoder.accept({"type": "turn.started"})
  decoder.accept({"type": "item.completed", "item": {"id": "answer", "type": "agent_message", "text": "fixture final"}})
  assert decoder.accept({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}) == ("completed", "turn-completed")


def test_codex_fatal_error_can_be_followed_by_turn_failed_without_becoming_success():
  from agentcfg.model_delegate_backends import CodexEvents
  from agentcfg.storage import Conflict
  import pytest
  decoder = CodexEvents()
  decoder.accept({"type": "thread.started", "thread_id": "fixture-thread"})
  decoder.accept({"type": "turn.started"})
  assert decoder.accept({"type": "error", "message": "synthetic private failure"}) == ("failed", "terminated")
  assert decoder.accept({"type": "turn.failed", "error": {"message": "synthetic private failure"}}) is None
  assert decoder.failed and not decoder.completed
  with pytest.raises(Conflict): decoder.accept({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})


def test_linux_native_sparse_policy_keeps_runtime_and_scratch_without_exposing_private_siblings(tmp_path, monkeypatch):
  import agentcfg.model_delegate_backends as backend
  monkeypatch.setattr(backend.sys, "platform", "linux")
  project = tmp_path / "project"; project.mkdir(); (project / ".git").mkdir()
  instance = tmp_path / "instance"; runtime = instance / "runtimes/fixture"; runtime.mkdir(parents=True)
  home = instance / "codex-home"; home.mkdir()
  state = tmp_path / "state"; scratch = state / "worker/tools"; scratch.mkdir(parents=True)
  local = tmp_path / "local.toml"; local.write_text("synthetic private configuration")
  rule = {"id": "read", "kind": "file", "effect": "allow", "tool_ids": ["tk_read"], "operations": ["read"],
    "root_ref": "project", "relative_path": ".", "match": "subtree"}
  policy = {"schema_version": 1, "default": "deny", "rules": [rule]}
  grant = {"execution_mode": "delegate-readonly", "root_bindings": {"project": {"path": str(project)}}}
  value = backend.codex_permissions(policy, grant, runtime_root=runtime, codex_home=home, scratch=scratch,
    protected_roots=[instance, state, local], native=NATIVE)
  assert value[str(runtime)] == "read" and value[str(scratch)] == "write"
  assert value[":root"] == "deny" and ":slash_tmp" not in value and ":tmpdir" not in value
  allowed = [Path(name) for name, access in value.items() if not name.startswith(":") and access != "deny"]
  assert all(not private.is_relative_to(root) for private in (home, local, state / "lease.json") for root in allowed)
  # 宽到包含私有实例和可信代码的项目布局须拒绝，不能靠更具体 allow 重开整个实例。
  grant["root_bindings"]["project"]["path"] = str(tmp_path)
  with pytest.raises(ConfigError, match="private-root-overlap"):
    backend.codex_permissions(policy, grant, runtime_root=runtime, codex_home=home, scratch=scratch,
      protected_roots=[instance, state, local], native=NATIVE)
