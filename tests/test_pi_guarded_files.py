"""真实临时文件 IO，不启动宿主；覆盖权限与实际 fd 操作之间的边界。"""

from datetime import datetime, timedelta, timezone
import os

import pytest

from agentcfg.pi_guarded_files import FilePolicy, GuardedFiles, root_identity
from agentcfg.storage import Conflict


def fixture(tmp_path, *, extra_rules=(), writer=True):
  root = tmp_path / "project"
  root.mkdir()
  (root / "src").mkdir()
  (root / "src/a.txt").write_text("original")
  (root / "src2").mkdir()
  (root / "src2/a.txt").write_text("outside rule")
  (root / ".env").write_text("synthetic secret")
  roots = {"project": {"path": str(root), "identity": root_identity(root)}}
  tools = ["tk_read", "tk_write", "tk_edit"]
  policy = {"schema_version": 1, "default": "deny", "rules": [
    {"id": "source", "kind": "file", "effect": "allow", "tool_ids": tools, "operations": ["read", "write", "create", "rename"],
      "root_ref": "project", "relative_path": "src", "match": "subtree"}, *extra_rules]}
  ceiling = {"allowed_tools": tools, "read_roots": ["project"], "write_roots": ["project"] if writer else []}
  grant = {**ceiling, "grant_generation": 1, "executor": "managed-process", "context_mode": "fresh", "nested": False,
    "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
  state = {"valid": True, "writer": writer}
  calls = []
  def mutation(phase, detail):
    calls.append((phase, detail))
    return "fixture-ticket"
  compiled = FilePolicy(policy=policy, roots=roots, ceiling=ceiling, grant=grant, mode="managed",
    verify=lambda *args: state["valid"], workspace=lambda *args: state["writer"])
  return root, GuardedFiles(compiled, mutation=mutation), state, calls


def test_future_account_anchor_under_parent_project_is_denied_without_creating_it(tmp_path):
  root, files, _, _ = fixture(tmp_path)
  original = files.policy
  original.policy["rules"][0]["relative_path"] = "."
  anchor = root / "os-account" / ".agentcfg-workspaces"
  # 合成Git父项目覆盖账户控制路径；即使哨兵尚未创建，普通业务目录仍可用。
  (root / ".git").mkdir()
  compiled = FilePolicy(policy=original.policy, roots=original.roots, ceiling=original.ceiling,
    grant=original.grant, mode=original.mode, verify=original.verify, workspace=original.workspace,
    secret_roots=[anchor])
  assert compiled.authorize("read", "read", root / "src/a.txt")
  target = anchor / "reviewer-budget/reviewer-ledger.json"
  for tool, operation in (("read", "read"), ("write", "create")):
    with pytest.raises(Conflict, match="PERMISSION_DENIED"):
      compiled.authorize(tool, operation, target)
  assert not anchor.exists()


def test_guarded_read_write_and_rename_apply_policy_to_real_files(tmp_path):
  root, files, _, calls = fixture(tmp_path)
  assert files.read("read", "src/a.txt") == b"original"
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    files.read("read", "src2/a.txt")
  assert files.write("write", "src/a.txt", b"changed")["changed"]
  assert (root / "src/a.txt").read_bytes() == b"changed"
  assert [phase for phase, _ in calls] == ["prepare", "settle"]
  files.rename("edit", "src/a.txt", "src/b.txt")
  assert not (root / "src/a.txt").exists()
  assert (root / "src/b.txt").read_bytes() == b"changed"


def test_metadata_is_permission_checked_and_does_not_read_file_body(tmp_path, monkeypatch):
  from agentcfg.storage import Tree
  root, files, state, _ = fixture(tmp_path)
  monkeypatch.setattr(Tree, "read", lambda *_args, **_kwargs: pytest.fail("metadata must not read body"))
  assert files.metadata("read", "src/a.txt")["size"] == len("original")
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    files.metadata("read", ".env")
  state["valid"] = False
  with pytest.raises(Conflict): files.metadata("read", "src/a.txt")


def test_deny_destination_and_revocation_leave_sentinels_unchanged(tmp_path):
  deny = {"id": "deny-destination", "kind": "file", "effect": "deny", "tool_ids": ["tk_edit"], "operations": ["rename"],
    "root_ref": "project", "relative_path": "src/denied.txt", "match": "exact"}
  root, files, state, calls = fixture(tmp_path, extra_rules=[deny])
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    files.rename("edit", "src/a.txt", "src/denied.txt")
  assert calls == []
  state["valid"] = False
  with pytest.raises(Conflict, match="GRANT_STALE"):
    files.write("write", "src/a.txt", b"changed")
  assert (root / "src/a.txt").read_bytes() == b"original"
  assert (root / ".env").read_text() == "synthetic secret"


def test_writer_loss_or_path_swap_after_mutation_intent_cannot_escape(tmp_path):
  root, files, state, calls = fixture(tmp_path)
  outside = tmp_path / "outside"
  outside.mkdir()
  (outside / "a.txt").write_text("outside sentinel")
  def replace_path(phase, detail):
    assert phase == "prepare"
    (root / "src").rename(root / "old-src")
    (root / "src").symlink_to(outside, target_is_directory=True)
    return "intent"
  files.mutation = replace_path
  with pytest.raises(Conflict, match="ROOT_IDENTITY"):
    files.write("write", "src/a.txt", b"changed")
  assert (outside / "a.txt").read_text() == "outside sentinel"
  assert (root / "old-src/a.txt").read_text() == "original"


def test_shared_writer_recheck_and_missing_durable_intent_block_actual_write(tmp_path):
  root, files, state, calls = fixture(tmp_path)
  state["writer"] = False
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"):
    files.write("write", "src/a.txt", b"changed")
  state["writer"] = True
  files.mutation = lambda *args: None
  with pytest.raises(Conflict, match="MUTATION_INTENT_MISSING"):
    files.write("write", "src/a.txt", b"changed")
  assert (root / "src/a.txt").read_text() == "original"


def test_owned_candidate_inside_private_instance_does_not_expose_sibling_credentials(tmp_path):
  root, files, state, calls = fixture(tmp_path)
  # Task Keeper 的候选位于私人实例内，但兄弟账号文件仍不是项目内容。
  files.policy.private_roots = (tmp_path,)
  files.policy.secrets = (root / ".env",)
  assert files.read("read", "src/a.txt") == b"original"
  files.write("write", "src/a.txt", b"candidate change")
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    files.read("read", ".env")
  assert (root / ".env").read_text() == "synthetic secret"


def test_explicit_candidate_policy_requires_live_grant_and_preserves_default_deny(tmp_path):
  import tomllib
  from pathlib import Path
  from agentcfg.pi_catalog import validate_policy
  policies = tomllib.loads((Path(__file__).resolve().parents[1] / "agents/pi/agent.toml").read_text())["policies"]
  assert policies["project-default"]["rules"] == []
  policy = policies["task-keeper-candidate"]
  validate_policy(policy)
  root, files, state, _ = fixture(tmp_path)
  previous = files.policy
  compiled = FilePolicy(policy=policy, roots=previous.roots, ceiling=previous.ceiling, grant=previous.grant, mode="managed",
    verify=lambda *args: state["valid"], workspace=lambda *args: state["writer"], secret_roots=[root / ".env"])
  files = GuardedFiles(compiled, mutation=lambda *args: "ticket")
  assert files.read("tk_read", "src/a.txt") == b"original"
  assert files.write("tk_write", "src/a.txt", b"candidate")["changed"]
  assert files.write("tk_write", "src/new.txt", b"new candidate file")["changed"]
  for name in (".env", ".git/HEAD"):
    with pytest.raises(Conflict):
      files.read("tk_read", name)
  with pytest.raises(Conflict):
    files.rename("tk_edit", "src/a.txt", "src/b.txt")
  state["writer"] = False
  with pytest.raises(Conflict):
    files.write("tk_write", "src/a.txt", b"unauthorized")
  assert (root / "src/a.txt").read_bytes() == b"candidate"


def test_atomic_rename_cannot_overwrite_destination_created_after_validation(tmp_path, monkeypatch):
  from agentcfg import pi_guarded_files
  root, files, state, calls = fixture(tmp_path)
  original = pi_guarded_files.rename_exclusive
  def concurrent_destination(source_fd, source_name, target_fd, target_name):
    (root / "src/b.txt").write_text("concurrent sentinel")
    return original(source_fd, source_name, target_fd, target_name)
  monkeypatch.setattr(pi_guarded_files, "rename_exclusive", concurrent_destination)
  with pytest.raises(Conflict, match="RENAME_DESTINATION_CONFLICT"):
    files.rename("edit", "src/a.txt", "src/b.txt")
  assert (root / "src/a.txt").read_text() == "original"
  assert (root / "src/b.txt").read_text() == "concurrent sentinel"


def test_exact_file_create_does_not_implicitly_authorize_missing_parent_directories(tmp_path):
  root, files, state, calls = fixture(tmp_path)
  previous = files.policy
  rule = {"id": "one-file", "kind": "file", "effect": "allow", "root_ref": "project", "relative_path": "new-dir/file.txt",
    "match": "exact", "tool_ids": ["tk_write"], "operations": ["write", "create"]}
  files.policy = FilePolicy(policy={"schema_version": 1, "default": "deny", "rules": [rule]}, roots=previous.roots, ceiling=previous.ceiling,
    grant=previous.grant, mode="managed", verify=lambda *_: True, workspace=lambda *_: True)
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    files.write("write", "new-dir/file.txt", b"new")
  assert not (root / "new-dir").exists() and calls == []


def test_existing_inode_alias_cannot_bypass_an_exact_denial(tmp_path):
  deny = {"id": "denied-inode", "kind": "file", "effect": "deny", "tool_ids": ["tk_read"], "operations": ["read"],
    "root_ref": "project", "relative_path": "src/a.txt", "match": "exact"}
  root, files, _, _ = fixture(tmp_path, extra_rules=[deny])
  os.link(root / "src/a.txt", root / "src/alias.txt")
  # 决策层本身拒绝对象别名，不依赖之后read的多链接检查兜底。
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    files.policy.authorize("read", "read", "src/alias.txt")


def test_macos_case_insensitive_denial_covers_future_paths_without_creating_a_probe(tmp_path, monkeypatch):
  from agentcfg import pi_guarded_files
  deny = {"id": "private", "kind": "file", "effect": "deny", "tool_ids": ["tk_write"], "operations": ["write", "create"],
    "root_ref": "project", "relative_path": "src/private", "match": "subtree"}
  monkeypatch.setattr(pi_guarded_files.sys, "platform", "darwin")
  monkeypatch.setattr(pi_guarded_files.os, "fpathconf", lambda fd, name: 0 if name == 11 else pytest.fail("unexpected query"))
  root, files, _, calls = fixture(tmp_path, extra_rules=[deny])
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    files.write("write", "src/PRIVATE/new.txt", b"must not write")
  assert not (root / "src/PRIVATE").exists() and not calls
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    files.policy.authorize("write", "write", "src/.GIT/config")


def test_unbound_parent_file_rule_is_not_silently_ignored(tmp_path):
  from agentcfg.schema import ConfigError
  deny = {"id": "missing-root", "kind": "file", "effect": "deny", "tool_ids": ["tk_read"], "operations": ["read"],
    "root_ref": "unbound", "relative_path": ".", "match": "subtree"}
  with pytest.raises(ConfigError, match="permission-root-unbound"):
    fixture(tmp_path, extra_rules=[deny])


@pytest.mark.parametrize("target_kind", ["secret", "policy", "outside", "symlink"])
def test_allowed_source_io_cannot_read_or_rewrite_protected_sentinels(tmp_path, sentinel_factory, target_kind):
  root, files, _, _ = fixture(tmp_path)
  allowed = root / "src/allowed.txt"; allowed.write_text("allowed source")
  target = root / "src/protected.txt"; target.write_text("synthetic protected sentinel")
  if target_kind == "outside":
    target = tmp_path / "outside.txt"; target.write_text("synthetic outside sentinel")
  if target_kind == "symlink":
    outside = tmp_path / "outside.txt"; outside.write_text("synthetic outside sentinel")
    target.unlink(); target.symlink_to(outside)
    sentinel = sentinel_factory(outside)
  else:
    sentinel = sentinel_factory(target)
  if target_kind in ("secret", "policy"):
    # 私密账号与权威配置即便落在允许子树中，也不能由任务重新授权。
    files.policy.secrets = (target,)
  assert files.read("read", str(allowed)) == b"allowed source"
  assert files.write("write", str(allowed), b"changed source")["changed"]
  for operation in (lambda: files.read("read", str(target)), lambda: files.write("write", str(target), b"must not write")):
    with pytest.raises(Conflict): operation()
  sentinel.assert_unchanged()
  assert allowed.read_bytes() == b"changed source"


def test_explicit_ordinary_project_policy_uses_file_authority_and_preserves_default_deny(tmp_path):
  import tomllib
  from pathlib import Path
  from agentcfg.pi_catalog import validate_policy
  policies = tomllib.loads((Path(__file__).resolve().parents[1] / "agents/pi/agent.toml").read_text())["policies"]
  assert policies["project-default"]["rules"] == []
  policy = policies["ordinary-project"]; validate_policy(policy)
  assert all(row["kind"] == "file" for row in policy["rules"])
  root, files, state, _ = fixture(tmp_path)
  before = files.policy
  files.policy = FilePolicy(policy=policy, roots=before.roots, ceiling=before.ceiling, grant=before.grant, mode="managed",
    verify=lambda *_: state["valid"], workspace=lambda *_: state["writer"], secret_roots=[root / "private-control"])
  assert files.read("read", "src/a.txt") == b"original"
  assert files.write("write", "src/a.txt", b"ordinary change")["changed"]
  files.rename("edit", "src/a.txt", "src/moved.txt")
  assert files.policy.authorize("write", "create", "src/next.txt")["approval"] == "deterministic-policy"
  for path in (root / ".env", root / ".git/HEAD", root / "private-control/future", tmp_path / "outside.txt"):
    with pytest.raises(Conflict): files.policy.authorize("read", "read", path)
    with pytest.raises(Conflict): files.policy.authorize("write", "create", path)
  assert not (root / ".git").exists() and not (root / "private-control").exists()
  state["writer"] = False
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"): files.write("write", "src/moved.txt", b"never written")
  assert (root / "src/moved.txt").read_bytes() == b"ordinary change"


def test_agent_policy_schema_matches_existing_approval_and_mcp_reference_contract():
  from copy import deepcopy
  import json
  from pathlib import Path
  import tomllib
  from jsonschema import Draft202012Validator
  from agentcfg.pi_catalog import validate_policy
  from agentcfg.schema import ConfigError, _strict_schema
  from agentcfg.pi import PiAdapter
  root = Path(__file__).resolve().parents[1]
  schema = json.loads((root / "agents/pi/schemas/agent.schema.json").read_text())
  _strict_schema(schema)
  rule_schema = schema["properties"]["policies"]["additionalProperties"]["properties"]["rules"]["items"]
  validator = Draft202012Validator(rule_schema)
  allow = tomllib.loads((root / "agents/pi/agent.toml").read_text())["policies"]["ordinary-project"]["rules"][0]
  assert validator.is_valid(allow)
  for change in ({"approval": "unknown"}, {"unknown": True}):
    assert not validator.is_valid({**deepcopy(allow), **change})
  # 原Adapter文档回调复用共同policy validator；不复制第二套条件schema。
  with pytest.raises(ConfigError):
    validate_policy({"schema_version": 1, "default": "deny", "rules": [{**deepcopy(allow), "effect": "deny"}]})
  document = tomllib.loads((root / "agents/pi/agent.toml").read_text())
  document["policies"]["ordinary-project"]["rules"][0]["effect"] = "deny"
  with pytest.raises(ConfigError):
    PiAdapter(root).schemas().bundles["pi"].validate("agent", document)
  mcp = {"id": "mcp-explicit", "kind": "command", "effect": "allow", "approval": "human",
    "tool_ids": ["mcp"], "operations": ["execute"], "command_ref": "mcp:fixture"}
  assert validator.is_valid(mcp)
