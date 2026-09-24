"""原生验收输入的静态边界；不运行宿主，不把临时夹具当真实密封运行包。"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from agentcfg.pi_validation_runtime import inspect_runtime
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from agentcfg.deployment import json_bytes


def fixture(tmp_path):
  root = tmp_path / "prepared-runtime"
  installed = {"schema_version": 1, "engine": "bun", "platform": "linux-x86_64", "runtime_identity": "a" * 64,
    "lock_identity": "b" * 64, "slice_identity": "c" * 64, "toolchains": {"bun": "1.4.0", "node": "v24.14.0", "npm": "11.19.1"},
    "entrypoint": "pi-cursor/node_modules/@earendil-works/pi-coding-agent/dist/index.js", "sdk_package": "@earendil-works/pi-coding-agent", "sdk_version": "0.84.4"}
  receipt = {"identity": installed["runtime_identity"], "lock_identity": installed["lock_identity"], "slice_identity": installed["slice_identity"],
    "platform": installed["platform"], "toolchains": installed["toolchains"], "slice": {"package_path": "pi-cursor/package.json"}}
  with Tree(root, create=True) as tree:
    tree.write_new("runtime/profile.json", json_bytes(installed)); tree.write_new(".agentcfg-receipt.json", json_bytes(receipt))
    tree.write_new(installed["entrypoint"], b"synthetic SDK fixture, never execute"); tree.write_new("runtime/launch.mjs", b"synthetic entry, never execute")
  return root, installed, receipt


def test_native_runtime_checks_actual_seal_and_keeps_cursor_engine_identity(tmp_path):
  root, installed, _ = fixture(tmp_path); calls = []
  def check(path, identity): calls.append((path, identity)); return "installed"
  value = inspect_runtime(root, check=check, current_platform=lambda: "linux-x86_64")
  assert calls == [(root, "a" * 64)] and value.engine == "bun" and value.profile == "pi-cursor"
  assert value.public_identity()["toolchains"]["bun"] == "1.4.0"
  with pytest.raises(Conflict, match="DAMAGED"):
    inspect_runtime(root, check=lambda *_: "damaged", current_platform=lambda: "linux-x86_64")
  # 真实校验器不会接受这个只有元数据的测试夹具。
  with pytest.raises(Conflict): inspect_runtime(root, current_platform=lambda: "linux-x86_64")


@pytest.mark.parametrize("field,value", [("engine", "node"), ("platform", "darwin-arm64"), ("runtime_identity", "d" * 64),
  ("sdk_version", "0.84.5"), ("entrypoint", "../escape"), ("entrypoint", "pi-default/index.js")])
def test_runtime_contract_mismatch_never_reaches_execution(tmp_path, field, value):
  root, installed, _ = fixture(tmp_path); installed[field] = value
  with Tree(root) as tree: tree.write_state("runtime/profile.json", json_bytes(installed))
  with pytest.raises((ConfigError, Conflict)):
    inspect_runtime(root, check=lambda *_: "installed", current_platform=lambda: "linux-x86_64")


def test_absent_and_linked_runtime_inputs_are_rejected(tmp_path):
  root, _, _ = fixture(tmp_path)
  alias = tmp_path / "alias"; alias.symlink_to(root)
  with pytest.raises(ConfigError): inspect_runtime(alias)
  empty = tmp_path / "empty"; empty.mkdir()
  with pytest.raises(Conflict, match="UNSEALED"): inspect_runtime(empty)


@pytest.mark.parametrize("failure,attempt,expected", [("EVIDENCE_EMPTY", "current", True), ("EXECUTION_FAILED", "current", False), ("EVIDENCE_EMPTY", "another", False)])
def test_missing_result_proof_requires_the_current_worker_and_specific_failure(tmp_path, failure, attempt, expected):
  from agentcfg.pi_validation_runtime import worker_failure_observed
  from agentcfg.deployment import json_bytes
  from agentcfg.storage import Tree
  lease = {"kind": "worker", "lease_id": "fixture-lease", "attempt_id": "current"}
  with Tree(tmp_path) as tree:
    tree.write_new("activity/worker-homes/fixture-lease/reports/result.json", json_bytes({"attempt_id": attempt,
      "state": "execution_failed", "failure_code": failure, "structured_result": None}))
  assert worker_failure_observed(tmp_path, [lease], {"EVIDENCE_EMPTY", "EVIDENCE_MISSING"}) is expected
