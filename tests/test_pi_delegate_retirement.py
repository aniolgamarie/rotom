"""旧执行器完全缺席的迁移契约；启动使用假宿主，不计原生通过。"""

import json
from pathlib import Path
import tomllib

import pytest

from agentcfg.deployment import json_bytes
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Tree
from test_pi_delegate import fixture

ROOT = Path(__file__).resolve().parents[1]
PRESETS = ("general", "context", "challenge", "plan", "research", "review", "scout")


def test_published_registrations_and_all_frozen_callers_retire_legacy_executor():
  agent = tomllib.loads((ROOT / "agents/pi/agent.toml").read_text())
  plugins = tomllib.loads((ROOT / "agents/pi/plugins.toml").read_text())["plugins"]
  skills = tomllib.loads((ROOT / "shared/content.toml").read_text())["skills"]
  roles = json.loads((ROOT / "agents/pi/migration/role-map.json").read_text())["roles"]
  assert set(row["preset"] for row in roles.values()) == set(PRESETS)
  assert all(not row["register_legacy_role"] and row["tool"] == "model_delegate" for row in roles.values())
  assert not set(roles) & agent["resources"].keys()
  assert "codex-agents" not in plugins and "codex-delegate" not in skills
  assert "model-delegate" in plugins and "model-delegate" in skills
  assert not (ROOT / "agents/pi/packages/codex-agents").exists()
  assert not (ROOT / "shared/skills/codex-delegate").exists()
  baseline = json.loads((ROOT / "agents/pi/migration/source-baseline.json").read_text())
  callers = json.loads((ROOT / "agents/pi/migration/caller-map.json").read_text())
  source = {row["path"]: row["git_blob"] for row in baseline["files"]}
  assert callers["source_revision"] == baseline["revision"]
  assert len(callers["entries"]) == 37
  for row in callers["entries"]:
    assert row["source_blob"] == source[row["source_path"]]
    assert row["legacy_runtime_dependency"] is False
    if row["disposition"] != "source-history-only": assert row["target_paths"]
    for path in row["target_paths"]:
      assert (ROOT / path).is_file()
      assert "run-codex.sh" not in (ROOT / path).read_text()
  for name in ("pi-default", "pi-managed", "pi-codex", "pi-cursor"):
    profile = tomllib.loads((ROOT / "profiles" / (name + ".toml")).read_text())
    assert not set(roles) & set(profile["agent_options"]["resources"]["roles"])
    assert "codex-delegate" not in profile["skills"] and "codex-agents" not in profile["plugins"]


@pytest.mark.parametrize("backend", ["pi", "codex"])
@pytest.mark.parametrize("preset", PRESETS)
def test_two_backends_seven_purposes_start_without_legacy_home_or_runner(tmp_path, backend, preset):
  controller, host, args, calls = fixture(tmp_path)
  options = host.manifest()["options"]["model_delegate"]
  options.update(backends=["pi", "codex"], presets=list(PRESETS), codex={"model": "fictional-codex", "mode": "readonly", "network_route": "direct", "native_execution": {"allow_shell": True, "tool_network": "none"}})
  purpose = (ROOT / "shared/skills/model-delegate/presets" / (preset + ".md")).read_bytes()
  with Tree(host.runtime_root) as tree:
    tree.write_state("supervisor/shared/skills/model-delegate/presets/" + preset + ".md", purpose)
    tree.write_state("runtime/commands.json", json_bytes({"schema_version": 1, "programs": {
      "delegate-" + backend: {"entrypoint": "runtime/fake-entry", "kind": "codex" if backend == "codex" else "external", "engine": "python", **({"backend_entrypoint": "bin/fake-codex"} if backend == "codex" else {})}}}))
    tree.write_state("runtime/fake-entry", b"never execute: fake spawn only")
    if backend == "codex": tree.write_state("bin/fake-codex", b"never execute: fake native asset")
  request = controller.prepare(Principal("manager"), {**args, "backend": backend, "preset": preset,
    "model": {"provider_id": "openai", "model_id": "fictional-codex"} if backend == "codex" else args["model"]})
  assert purpose.decode() in controller.input(request["run_id"])["prompt"]
  assert request["execution_mode"] == "delegate-readonly" and request["workspace_write_lease_ids"] == []
  assert controller.start(Principal("manager"), request["run_id"])["state"] == "start_unknown"
  assert len(calls) == 1
  assert not list(tmp_path.rglob("run-codex.sh"))
  assert not list(tmp_path.rglob("codex-agents"))
