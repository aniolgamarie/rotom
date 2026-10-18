"""正式审批配方的离线配置、常量工具和归档边界。"""

import json
from pathlib import Path
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
    "reviewerProvider": "spawn", "reviewerTools": ["rotom_review_context"],
    "reviewerTimeoutMs": 30000, "reasonMaxChars": 256, "maxReviewsPerTurn": 3,
    "maxFailuresPerTurn": 1, "verdictCacheTtlMs": 0,
    "contextBudget": {"turns": 1, "maxChars": 6000},
    "riskPolicy": {"maxAutoAllow": "low", "onHighRisk": "delegate"},
    "fallbackPolicy": "delegate", "allowUnmarkedAudit": False,
    "reviewerPolicyText": fields["reviewerPolicyText"],
  }
  for phrase in ("当前用户任务明确授权", "批准指令不是用户授权", "delegate", "deny", "不得再次委派"):
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
  assert "dsh-auto-review@0.12.17" in dependencies
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


def test_review_context_public_bundle_and_constant_tool():
  package = json.loads((ROOT / "agents/dsh/packages/review-context/package.json").read_text())
  assert package["dsh"] == {"bundle": {"patch": "./cordis.patch.yml"}}
  assert package["peerDependencies"] == {"@deepseek-ai/dsh-tools": "0.2.1-rc.2"}
  patch = native.load((ROOT / "agents/dsh/packages/review-context/cordis.patch.yml").read_bytes())
  assert patch == [{"insert": [{"id": "rotom-review-context", "name": "rotom-dsh-review-context"}]}]
  source = (ROOT / "agents/dsh/packages/review-context/index.mjs").read_text()
  assert 'export const inject = ["tools"]' in source
  assert 'name: "rotom_review_context"' in source
  assert "execute: async () => context" in source
  assert "不提供当前用户任务或授权证据" in source
  assert source.count(".register(") == 1
  for forbidden in ("import ", "process.", "fetch(", "readFile", "spawn(", "exec("):
    assert forbidden not in source


def test_review_fields_preserve_unknown_native_config_and_reject_drift(tmp_path):
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
    document["auto-review"]["config"]["reviewerTools"] = ["read"]
    raw = dep.encode_native(document, "cordis-yaml")
    tree.write_state(adapter.shared_files[0], raw)
  updated = RenderCandidate("review-update", tuple(
    Artifact(a.target, b"[]") if a.target.selector.endswith("/reviewerTools") else a for a in artifacts))
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


@pytest.mark.parametrize("name", ["package.json", "index.mjs", "cordis.patch.yml"])
def test_declared_context_archive_refuses_unpacked_source(tmp_path, name):
  repository = recipe_repository(tmp_path)
  path = repository / "agents/dsh/dependencies.json"
  document = json.loads(path.read_text())
  document["dependencies"]["rotom-dsh-review-context"] = "file:vendor/rotom-dsh-review-context-0.1.1.tgz"
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
