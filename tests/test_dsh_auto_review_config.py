"""正式审批配方的离线配置、常量工具和归档边界。"""

import json
from pathlib import Path
import re
import shutil
import tomllib

import pytest
from jsonschema import ValidationError, validate

from agentcfg import deployment as dep, native
from agentcfg.adapter import Artifact, Ownership
from agentcfg.dependencies import recipe_digest
from agentcfg.dsh import DshAdapter, OPTIONS
from agentcfg.process import DependencyError
from agentcfg.render import RenderCandidate
from agentcfg.storage import Conflict, Tree


ROOT = Path(__file__).resolve().parents[1]


def data(auto_review=True):
  defaults = tomllib.loads((ROOT / "agents/dsh/agent.toml").read_text())["defaults"]
  plugins = tomllib.loads((ROOT / "agents/dsh/plugins.toml").read_text())["plugins"]
  return {"providers": {}, "models": {}, "mcp": {}, "rules": {},
    "plugins": {key: plugins[key] for key in defaults["plugins"]},
    "profile": {"roles": {}, "rules": [], "agent_options": {**defaults["agent_options"], "auto_review": auto_review}},
    "adapter_documents": {"bindings": {}}}


def test_formal_review_config_is_owned_per_field_and_inherits_model():
  artifacts = tuple(DshAdapter(ROOT)._field_artifacts(data()))
  review = [a for a in artifacts if a.target.selector.startswith("/auto-review/")]
  assert review and all(a.target.ownership == Ownership.FIELDS for a in review)
  fields = {a.target.selector.removeprefix("/auto-review/config/"): json.loads(a.content) for a in review}
  assert fields == {
    "enableByDefault": True,
    "toolsPolicy": {"default": "human", "overrides": {"write": "ai", "edit": "ai"}},
    "reviewerProvider": "spawn", "reviewerPreset": "rotom-auto-review",
    "reviewerTools": ["rotom_review_context"],
    "riskRules": [{"field": "toolName", "pattern": "^(?!(?:bash|write|edit)$)", "policy": "human"},
      {"field": "reason", "pattern": "^escalate sandbox to (?:workspace-write|danger-full-access): .+$",
      "policy": "ai"}],
    "reviewerTimeoutMs": 90000, "reasonMaxChars": 256, "maxReviewsPerTurn": 3,
    "maxFailuresPerTurn": 1, "verdictCacheTtlMs": 0,
    "contextBudget": {"turns": 1, "maxChars": 6000},
    "riskPolicy": {"maxAutoAllow": "low", "onHighRisk": "delegate"},
    "fallbackPolicy": "delegate", "allowUnmarkedAudit": False,
    "reviewerPolicyText": fields["reviewerPolicyText"],
  }
  for phrase in ("当前用户任务明确授权", "批准指令不是用户授权", "delegate", "deny", "不得再次委派",
      "真实命令、目标和副作用", "名称不等于授权", "AI 路由也不代表 allow", "外部服务写入",
      "破坏性删除", "系统权限变更", "未确认的脚本副作用", "未知工具", "授权范围不清"):
    assert phrase in fields["reviewerPolicyText"]
  assert "reviewerModel" not in fields


@pytest.mark.parametrize("enabled", [True, False])
def test_review_toggle_disables_plugin_without_inserting_duplicate(enabled):
  adapter = DshAdapter(ROOT)
  rendered = adapter.render(data(enabled))
  patch = native.load(next(a.content for a in rendered if a.target.path == "dsh-home/agentcfg.patch.yml"))
  row = next(row for row in patch if row.get("id") == "auto-review")
  assert row == {"id": "auto-review", "disabled": not enabled}
  inserted = [item for row in patch for item in row.get("insert", [])]
  assert not any(item.get("id") == "auto-review" or item.get("name") == "dsh-auto-review" for item in inserted)
  assert sum(item.get("name") == "rotom-dsh-execution-environment" for item in inserted) == 1
  assert {"id": "subprocess", "disabled": True} in patch
  fields = {a.target.selector: json.loads(a.content) for a in rendered if a.target.selector}
  assert fields["/auto-review/config/enableByDefault"] is True
  dependencies = adapter.dependency_plan(data(enabled)).requirements
  assert "dsh-auto-review@0.15.0" in dependencies
  assert not any("rotom-dsh-review-context" in package or "file:" in package for package in dependencies)


def test_auto_review_option_is_boolean_and_defaults_on():
  options = data()["profile"]["agent_options"]
  validate(options, OPTIONS)
  with pytest.raises(ValidationError):
    validate({**options, "auto_review": "false"}, OPTIONS)
  assert options["auto_review"] is True
  fixture = data()
  fixture.pop("plugins")
  assert not any(a.target.selector.startswith("/auto-review/") for a in DshAdapter(ROOT)._field_artifacts(fixture))


@pytest.mark.parametrize("overrides, timeout, escalation", [
  ({}, 90000, True),
  ({"sandbox_escalation": False}, 90000, False),
  ({"reviewer_timeout_ms": 1000}, 1000, True),
  ({"reviewer_timeout_ms": 300000}, 300000, True),
  ({"sandbox_escalation": False, "reviewer_timeout_ms": 45000}, 45000, False),
])
def test_auto_review_options_allow_partial_overrides(overrides, timeout, escalation):
  fixture = data()
  fixture["profile"]["agent_options"]["auto_review_options"] = overrides
  validate(fixture["profile"]["agent_options"], OPTIONS)
  fields = dict(DshAdapter(ROOT)._auto_review_fields(fixture))
  assert fields["/auto-review/config/reviewerTimeoutMs"] == timeout
  rules = fields["/auto-review/config/riskRules"]
  assert bool(rules) is escalation
  if escalation:
    assert rules[0] == {"field": "toolName", "pattern": "^(?!(?:bash|write|edit)$)", "policy": "human"}
    assert rules[1]["field"] == "reason"
    assert rules[1]["policy"] == "ai"
    pattern = rules[1]["pattern"]
    for target in ("workspace-write", "danger-full-access"):
      assert re.fullmatch(pattern, "escalate sandbox to " + target + ": build fixture")
    for reason in ("bash", "run tests", "escalate sandbox to read-only: test",
        "prefix escalate sandbox to workspace-write: test", "escalate sandbox to workspace-write: "):
      assert not re.fullmatch(pattern, reason)
  assert fields["/auto-review/config/toolsPolicy"] == {
    "default": "human", "overrides": {"write": "ai", "edit": "ai"}}


@pytest.mark.parametrize("escalation", [True, False])
@pytest.mark.parametrize("tool", ["bash", "write", "edit", "read", "mcp_fixture", "unknown", "bash_extra"])
@pytest.mark.parametrize("reason", ["escalate sandbox to workspace-write: build fixture", "ordinary request"])
def test_public_first_match_routing_keeps_unknown_tools_human(escalation, tool, reason):
  fixture = data()
  fixture["profile"]["agent_options"]["auto_review_options"] = {"sandbox_escalation": escalation}
  config = DshAdapter(ROOT)._auto_review_config(fixture)
  request = {"toolName": tool, "reason": reason}
  # 公开规则先按顺序匹配，全部未匹配才使用工具覆盖及默认策略。
  policy = next((rule["policy"] for rule in config["riskRules"]
    if re.search(rule["pattern"], request[rule["field"]])),
    config["toolsPolicy"]["overrides"].get(tool, config["toolsPolicy"]["default"]))
  expected = "ai" if tool in ("write", "edit") or (
    escalation and tool == "bash" and reason.startswith("escalate sandbox to workspace-write: ")) else "human"
  assert policy == expected


def test_auto_review_options_are_optional():
  fixture = data()
  fixture["profile"]["agent_options"].pop("auto_review_options")
  validate(fixture["profile"]["agent_options"], OPTIONS)
  fields = dict(DshAdapter(ROOT)._auto_review_fields(fixture))
  assert fields["/auto-review/config/reviewerTimeoutMs"] == 90000
  assert fields["/auto-review/config/riskRules"]


@pytest.mark.parametrize("enabled, selected", [(True, True), (True, False), (False, True)])
def test_approval_diagnostics_is_a_configuration_preview(enabled, selected):
  fixture = data(enabled)
  fixture["profile"]["agent_options"]["auto_review_options"] = {
    "sandbox_escalation": False, "reviewer_timeout_ms": 45000}
  if not selected:
    fixture["plugins"].pop("auto-review")
  assert DshAdapter(ROOT).approval_diagnostics(fixture) == {
    "scope": "configuration-preview", "enabled": enabled and selected,
    "sandbox_escalation": False, "reviewer_timeout_ms": 45000,
    "max_reviews_per_turn": 3, "max_failures_per_turn": 1,
    "fallback_policy": "delegate", "persistent_verdict_audit": "unsupported", "runtime_checked": False}


@pytest.mark.parametrize("options", [False, [], {"unknown": True},
  {"sandbox_escalation": "false"}, {"sandbox_escalation": 0},
  {"reviewer_timeout_ms": 999}, {"reviewer_timeout_ms": 300001},
  {"reviewer_timeout_ms": True}, {"reviewer_timeout_ms": 1000.5},
  {"reviewer_timeout_ms": "90000"}])
def test_auto_review_options_reject_unknown_fields_and_invalid_values(options):
  with pytest.raises(ValidationError):
    validate({**data()["profile"]["agent_options"], "auto_review_options": options}, OPTIONS)


def test_review_context_public_bundle_and_constant_tool():
  package = json.loads((ROOT / "agents/dsh/packages/review-context/package.json").read_text())
  assert package["dsh"] == {"bundle": {"patch": "./cordis.patch.yml"}}
  assert package["peerDependencies"] == {"@deepseek-ai/" + name: "0.2.1-rc.3"
    for name in ("dsh-tools", "dsh-agent-preset", "dsh-agent-tool-presentation")}
  assert package["exports"]["./reviewer"] == "./reviewer.mjs"
  patch = native.load((ROOT / "agents/dsh/packages/review-context/cordis.patch.yml").read_bytes())
  assert patch == [{"insert": [
    {"id": "rotom-review-context", "name": "rotom-dsh-review-context"},
    {"id": "preset-rotom-auto-review", "name": "@deepseek-ai/dsh-agent-preset", "config": {
      "id": "rotom-auto-review", "plugins": [
        {"id": "reviewer-tool-face", "name": "rotom-dsh-review-context/reviewer"},
        {"id": "tool-presentation", "name": "@deepseek-ai/dsh-agent-tool-presentation", "config": {"mode": "native"}},
      ]}},
  ]}]
  source = (ROOT / "agents/dsh/packages/review-context/index.mjs").read_text()
  assert 'export const inject = ["tools"]' in source
  assert 'name: "rotom_review_context"' in source
  assert "execute: async () => context" in source
  assert "不提供当前用户任务或授权证据" in source
  assert source.count(".register(") == 1
  for forbidden in ("import ", "process.", "fetch(", "readFile", "spawn(", "exec("):
    assert forbidden not in source


@pytest.mark.parametrize("field, edited, desired", [
  ("reviewerTools", ["read"], []),
  ("reviewerPreset", "user-reviewer", "rotom-updated-reviewer"),
  ("reviewerTimeoutMs", 120000, 45000),
  ("riskRules", [{"field": "reason", "pattern": "manual", "policy": "human"}], []),
])
def test_review_fields_preserve_unknown_native_config_and_reject_drift(tmp_path, field, edited, desired):
  adapter = DshAdapter(ROOT)
  artifacts = tuple(a for a in adapter._field_artifacts(data()) if a.target.selector.startswith("/auto-review/"))
  candidate = RenderCandidate("review", artifacts)
  root, state = tmp_path / "instance", tmp_path / "state"
  binding = {"machine": "fixture", "local": "/synthetic/local.toml", "profile": "dsh-default"}
  launch = {"lock_identity": "fixture", "shared_files": list(adapter.shared_files)}
  dep.apply(root, state, candidate, binding, launch)
  with Tree(root) as tree:
    document = dep.parse_native(tree.read(adapter.shared_files[0])[0], "cordis-yaml")
    document["auto-review"]["config"]["unknown"] = {"keep": True}
    tree.write_state(adapter.shared_files[0], dep.encode_native(document, "cordis-yaml"))
  assert dep.apply(root, state, candidate, binding, launch)["changes"] == 0
  with Tree(root) as tree:
    document = dep.parse_native(tree.read(adapter.shared_files[0])[0], "cordis-yaml")
    assert document["auto-review"]["config"]["unknown"] == {"keep": True}
    document["auto-review"]["config"][field] = edited
    raw = dep.encode_native(document, "cordis-yaml")
    tree.write_state(adapter.shared_files[0], raw)
  updated = RenderCandidate("review-update", tuple(
    Artifact(a.target, json.dumps(desired).encode()) if a.target.selector.endswith("/" + field) else a for a in artifacts))
  with pytest.raises(Conflict):
    dep.apply(root, state, updated, binding, launch)
  with Tree(root) as tree:
    assert tree.read(adapter.shared_files[0])[0] == raw


def recipe_repository(tmp_path):
  repository = tmp_path / "repo"
  for relative in ("agents/dsh", "locks/dsh/vendor"):
    shutil.copytree(ROOT / relative, repository / relative)
  return repository


def test_undeclared_context_source_does_not_change_recipe(tmp_path):
  repository = recipe_repository(tmp_path)
  path = repository / "agents/dsh/dependencies.json"
  document = json.loads(path.read_text())
  document["dependencies"].pop("rotom-dsh-review-context", None)
  path.write_text(json.dumps(document))
  before = recipe_digest(repository)
  source = repository / "agents/dsh/packages/review-context/index.mjs"
  source.write_bytes(source.read_bytes() + b"\n// undeclared change\n")
  assert recipe_digest(repository) == before


@pytest.mark.parametrize("name", ["package.json", "index.mjs", "reviewer.mjs", "cordis.patch.yml"])
def test_declared_context_archive_refuses_unpacked_source(tmp_path, name):
  repository = recipe_repository(tmp_path)
  path = repository / "agents/dsh/dependencies.json"
  document = json.loads(path.read_text())
  document["dependencies"]["rotom-dsh-review-context"] = "file:vendor/rotom-dsh-review-context-0.2.1.tgz"
  path.write_text(json.dumps(document))
  recipe_digest(repository)
  source = repository / "agents/dsh/packages/review-context" / name
  source.write_bytes(source.read_bytes() + b"\n")
  with pytest.raises(DependencyError, match="重新打包"):
    recipe_digest(repository)


def formal_smoke_entry():
  import importlib.util
  spec = importlib.util.spec_from_file_location("formal_smoke", ROOT / "scripts/smoke-dsh-formal-review.py")
  entry = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(entry)
  return entry


def test_formal_smoke_refuses_host_without_explicit_flag(tmp_path):
  entry = formal_smoke_entry()
  evidence = tmp_path / "evidence"
  with pytest.raises(SystemExit) as error:
    entry.main(["--runtime", str(tmp_path / "missing"), "--evidence", str(evidence)])
  assert error.value.code == 2
  assert not evidence.exists()


def test_formal_smoke_rejects_unsealed_runtime_before_creating_fixture(tmp_path, monkeypatch):
  from types import SimpleNamespace
  from agentcfg import dependencies, runtime_packages
  entry = formal_smoke_entry()
  monkeypatch.setattr(dependencies, "read_lock", lambda _repo: SimpleNamespace(identity="fixture"))
  monkeypatch.setattr(runtime_packages, "status", lambda _root, _identity: "damaged")
  evidence = tmp_path / "evidence"
  with pytest.raises(SystemExit) as error:
    entry.main(["--allow-host", "--runtime", str(tmp_path / "missing"), "--evidence", str(evidence)])
  assert error.value.code == 2
  assert not evidence.exists()


@pytest.mark.parametrize("changed", ["package.json", "pnpm-lock.yaml"])
def test_formal_smoke_rejects_changed_runtime_inputs_before_creating_fixture(tmp_path, monkeypatch, changed):
  from types import SimpleNamespace
  from agentcfg import dependencies, runtime_packages
  entry = formal_smoke_entry()
  runtime = tmp_path / "runtime"
  runtime.mkdir()
  package, resolution = b"synthetic-package", b"synthetic-lock"
  (runtime / "package.json").write_bytes(package)
  (runtime / "pnpm-lock.yaml").write_bytes(resolution)
  (runtime / changed).write_bytes(b"changed")
  monkeypatch.setattr(dependencies, "read_lock", lambda _repo: SimpleNamespace(
    identity="fixture", package=package, installer_resolution=resolution))
  monkeypatch.setattr(runtime_packages, "status", lambda _root, _identity: "installed")
  evidence = tmp_path / "evidence"
  with pytest.raises(SystemExit) as error:
    entry.main(["--allow-host", "--runtime", str(runtime), "--evidence", str(evidence)])
  assert error.value.code == 2
  assert not evidence.exists()


def test_formal_smoke_rejects_memory_backed_evidence_before_fixture(tmp_path, monkeypatch):
  from types import SimpleNamespace
  from agentcfg import dependencies, runtime_packages
  entry = formal_smoke_entry()
  runtime = tmp_path / "runtime"
  runtime.mkdir()
  (runtime / "package.json").write_bytes(b"synthetic-package")
  (runtime / "pnpm-lock.yaml").write_bytes(b"synthetic-lock")
  monkeypatch.setattr(dependencies, "read_lock", lambda _repo: SimpleNamespace(
    identity="fixture", package=b"synthetic-package", installer_resolution=b"synthetic-lock"))
  monkeypatch.setattr(runtime_packages, "status", lambda _root, _identity: "installed")
  def filesystem(argv, **kwargs):
    assert argv[:4] == ["stat", "-f", "-c", "%T"]
    return SimpleNamespace(stdout="tmpfs\n")
  monkeypatch.setattr(entry.subprocess, "run", filesystem)
  evidence = tmp_path / "evidence"
  with pytest.raises(SystemExit) as error:
    entry.main(["--allow-host", "--runtime", str(runtime), "--evidence", str(evidence)])
  assert error.value.code == 2
  assert list(evidence.iterdir()) == []
