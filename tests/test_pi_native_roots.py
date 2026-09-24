"""原生权限投影仅用临时Git形状/文件身份，不运行Git、Codex或沙箱。"""

from copy import deepcopy
from pathlib import Path
import pytest

from agentcfg.activity import digest
from agentcfg.model_delegate_backends import codex_permissions
from agentcfg.pi_delegate_policy import execution_policy
from agentcfg.pi_native_roots import project_root_limits, restrict_permissions
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_delegate_files import writer


def fixture(tmp_path):
  def configure(host):
    source = Path(host.manifest()["options"]["paths"]["roots"]["project"]["path"])
    candidate = tmp_path / "candidate"
    for base in (source, candidate):
      for name in ("library/generated", "private/nested", "code"):
        (base / name).mkdir(parents=True)
    external = tmp_path / "external"; external.mkdir()
    options = host.manifest()["options"]
    options["paths"]["roots"].update({name: {"path": str(path), "purpose": "read"} for name, path in
      (("library", source / "library"), ("private", source / "private"), ("external", external))})
    options["permissions"] = {"readonly_roots": ["library", "external"], "denied_roots": ["private"]}
    rule = host.manifest()["permission_policy"]["rules"][0]
    rule["operations"] = ["read", "list", "search", "write", "create", "delete", "rename"]
    host.manifest()["permission_policy"]["rules"] += [{**rule, "id": "reopen-library", "relative_path": "library/generated"},
      {**rule, "id": "reopen-private", "relative_path": "private/nested"}]
  controller, host, source, candidate, request, _ = writer(tmp_path, configure=configure)
  home = tmp_path / "native-home"; home.mkdir(mode=0o700)
  scratch = tmp_path / "scratch"; scratch.mkdir(mode=0o700)
  data = controller.input(request["run_id"])
  def compile(*, limits=None, policy=None, mode=None):
    grant = deepcopy(data["grant"])
    if mode: grant["execution_mode"] = mode
    return codex_permissions(policy or data["execution_policy"]["file_policy"], grant,
      runtime_root=host.runtime_root, codex_home=home, scratch=scratch,
      native=data["execution_policy"]["native_execution"], root_limits=limits or data["execution_policy"]["root_limits"])
  return controller, host, source, candidate, request, data, compile


def test_candidate_inherits_restrictions_and_more_specific_allow_cannot_reopen_them(tmp_path):
  _, _, source, candidate, _, _, compile = fixture(tmp_path)
  result = compile()
  assert result[str(candidate)] == "write"
  assert result[str(candidate / "library")] == "read"
  assert result[str(candidate / "library/generated")] == "read"
  assert result[str(candidate / "private")] == result[str(source / "private")] == "deny"
  assert result.get(str(candidate / "private/nested"), "deny") == "deny"
  assert str(source / "library") not in result  # 不因只读声明而开放原checkout。
  assert str(tmp_path / "external") not in result  # 不因只读声明而授予新的读取权。


def test_whole_project_readonly_rejects_write_but_allows_native_readonly(tmp_path):
  _, _, _, candidate, _, data, compile = fixture(tmp_path)
  limits = deepcopy(data["execution_policy"]["root_limits"])
  limits["readonly_roots"].append("project")
  with pytest.raises(ConfigError, match="project-write-denied"): compile(limits=limits)
  assert compile(limits=limits, mode="delegate-readonly")[str(candidate)] == "read"
  limits["denied_roots"].append("project")
  with pytest.raises(ConfigError, match="project-access-denied"): compile(limits=limits, mode="delegate-readonly")


def test_nonproject_file_deny_is_bound_to_both_source_and_candidate(tmp_path):
  _, _, source, candidate, _, data, compile = fixture(tmp_path)
  policy = deepcopy(data["execution_policy"]["file_policy"])
  policy["rules"].append({"id": "native-reference-deny", "kind": "file", "effect": "deny", "root_ref": "library",
    "relative_path": "generated", "match": "subtree", "tool_ids": ["tk_read"], "operations": ["read"]})
  result = compile(policy=policy)
  assert result[str(source / "library/generated")] == result[str(candidate / "library/generated")] == "deny"
  policy["rules"][-1]["root_ref"] = "unknown"
  with pytest.raises(ConfigError, match="root-denial-unrepresentable"): compile(policy=policy)


def test_source_root_identity_change_invalidates_projection_and_requests_stop(tmp_path):
  controller, host, source, _, request, data, compile = fixture(tmp_path)
  original = data["request"]["execution_policy_digest"]
  (source / "library").rename(source / "old-library"); (source / "library").mkdir()
  with pytest.raises(Conflict, match="NATIVE_ROOT_STALE"): compile()
  assert digest(execution_policy(host.manifest(), "codex")) != original
  controller.tick()
  assert host.store.read(request["lease_id"])["state"] == "cancel_requested"
  assert host.store.reconcile(request["lease_id"])["protected"] is True


def test_removed_root_during_run_stops_without_crashing_supervisor_tick(tmp_path):
  controller, host, source, _, request, _, _ = fixture(tmp_path)
  (source / "library").rename(source / "moved-library")
  controller.tick()
  assert host.store.read(request["lease_id"])["state"] == "cancel_requested"


def test_candidate_symlink_cannot_move_parent_restriction_to_another_path(tmp_path):
  _, _, _, candidate, _, _, compile = fixture(tmp_path)
  (candidate / "library").rename(candidate / "original-library")
  (candidate / "library").symlink_to("code", target_is_directory=True)
  with pytest.raises(Conflict, match="NATIVE_ROOT_ALIAS"): compile()


def test_missing_candidate_restriction_is_not_silently_dropped_or_created(tmp_path):
  _, _, _, candidate, _, _, compile = fixture(tmp_path)
  (candidate / "private").rename(candidate / "old-private")
  with pytest.raises(ConfigError, match="path-denial-unrepresentable"): compile()
  assert not (candidate / "private").exists()


def test_readonly_never_reopens_a_deny_and_does_not_grant_new_paths():
  result = restrict_permissions({":root": "deny", "/project": "write", "/project/blocked/child": "write"},
    readonly=["/project/readonly", "/project/blocked", "/outside"], denied=["/project/blocked"])
  assert result == {":root": "deny", "/project": "write", "/project/blocked/child": "deny",
    "/project/readonly": "read", "/project/blocked": "deny"}


def test_file_allow_with_symlink_parent_cannot_grant_an_external_file(tmp_path):
  _, _, _, candidate, _, data, compile = fixture(tmp_path)
  external = tmp_path / "external/data.txt"; external.write_text("outside scope")
  (candidate / "portal").symlink_to(external.parent, target_is_directory=True)
  policy = deepcopy(data["execution_policy"]["file_policy"])
  policy["rules"].append({"id": "alias-allow", "kind": "file", "effect": "allow", "root_ref": "project",
    "relative_path": "portal/data.txt", "match": "exact", "tool_ids": ["tk_read"], "operations": ["read"]})
  with pytest.raises(ConfigError, match="path-denial-unrepresentable"): compile(policy=policy)


def test_alias_restriction_is_projected_by_directory_identity(tmp_path, monkeypatch):
  from agentcfg import pi_native_roots
  controller, host, source, candidate, _, _, _ = fixture(tmp_path)
  alias = tmp_path / "alias"; (alias / "library").mkdir(parents=True)
  options = host.manifest()["options"]
  options["paths"]["roots"]["aliased"] = {"path": str(alias / "library"), "purpose": "read"}
  options["permissions"]["denied_roots"] = ["aliased"]
  limits = execution_policy(host.manifest(), "codex")["root_limits"]
  original = pi_native_roots.same_object
  monkeypatch.setattr(pi_native_roots, "same_object", lambda left, right:
    original(left, right) or Path(left) == alias and Path(right) == source)
  projected = project_root_limits(limits, candidate)
  assert candidate / "library" in projected["denied"]


def test_restriction_alias_inside_nonproject_write_root_does_not_escape_cap(monkeypatch):
  from agentcfg import pi_native_roots
  monkeypatch.setattr(pi_native_roots, "same_object", lambda left, right:
    Path(left) == Path("/alias") and Path(right) == Path("/scratch"))
  result = restrict_permissions({":root": "deny", "/scratch": "write", "/scratch/private/nested": "write"},
    readonly=["/alias/cache"], denied=["/alias/private"])
  assert result["/scratch/cache"] == "read"
  assert result["/scratch/private"] == "deny"
  assert result["/scratch/private/nested"] == "deny"


def test_real_spawn_resolver_records_machine_root_projection_without_executing_cli(tmp_path, monkeypatch):
  import json
  from types import SimpleNamespace
  from agentcfg.pi_delegate_spawn import resolve_delegate
  from agentcfg.storage import Tree
  from agentcfg import pi_codex_admission
  calls = []
  monkeypatch.setattr(pi_codex_admission, "admit_codex_execution", lambda home: calls.append(home))
  controller, host, source, candidate, request, _, _ = fixture(tmp_path)
  host.delegates = controller
  host.repository = tmp_path / "frozen"
  host.server = SimpleNamespace(endpoint=tmp_path / "control")
  host.service.issue_capability = lambda *_args: "synthetic-worker-capability"
  with Tree(Path(host.config["instance_root"]), create=True) as tree:
    tree.write_state("codex-home/auth.json", b"synthetic-auth-body-not-read")
  lease = host.store.read(request["lease_id"])
  command = resolve_delegate(host, lease, "delegate-codex", {"run_id": request["run_id"]})
  assert calls == [Path(host.config["instance_root"]) / "codex-home"]
  document = json.loads(Path(command.argv[-1]).read_text())
  assert document["native_permissions"][str(candidate / "library")] == "read"
  assert document["native_permissions"][str(candidate / "private")] == "deny"
  assert "synthetic-auth-body-not-read" not in json.dumps(document)
  proof = json.loads((controller.root / "native-authorizations" / (request["run_id"] + ".json")).read_text())
  assert proof["execution_policy_digest"] == request["execution_policy_digest"]
  assert proof["permissions"] == document["native_permissions"]
  (source / "library").rename(source / "old-library"); (source / "library").mkdir()
  with pytest.raises(Conflict, match="POLICY_MISMATCH"):
    resolve_delegate(host, lease, "delegate-codex", {"run_id": request["run_id"]})
