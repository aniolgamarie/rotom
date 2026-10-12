"""T038纯静态准备验收；不import/执行恶意扩展、Node、Pi、Docker或网络。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_pi_adapter import ROOT

FIXTURE = ROOT / "tests/fixtures/pi/whole-process"


def closed_json(raw):
  def pairs(items):
    result = {}
    for key, value in items:
      if key in result: raise ValueError("whole-process-duplicate-key")
      result[key] = value
    return result
  return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("whole-process-nonfinite")))


def validate(plan):
  schema = closed_json((FIXTURE / "plan.schema.json").read_bytes())
  Draft202012Validator.check_schema(schema)
  Draft202012Validator(schema).validate(plan)
  return plan


def test_whole_process_preparation_is_closed_inert_and_source_complete():
  plan = validate(closed_json((FIXTURE / "plan.json").read_bytes()))
  assert plan["execution_state"] == "prepared-only" and all(plan["freeze"][key] is None for key in ("image_digest", "candidate_receipt_sha256", "node_sha256", "container_uid", "container_gid"))
  assert set(path.name for path in FIXTURE.iterdir()) == {*plan["source_pins"], "plan.json"}
  for name, expected in plan["source_pins"].items():
    path = FIXTURE / name
    assert path.is_file() and not path.is_symlink() and path.stat().st_size <= 96 * 1024 and not path.stat().st_mode & 0o111
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
  assert len(plan["cases"]) == 8 and len({row["id"] for row in plan["cases"]}) == 8
  assert plan["budgets"]["child_count_per_case"] == 1


@pytest.mark.parametrize("change", [
  lambda p: p.update(unknown=True),
  lambda p: p["docker"].update(privileged=True),
  lambda p: p["docker"].update(network="host"),
  lambda p: p["docker"]["mounts"].append({"id": "host-docker", "guest": "/var/run/docker.sock", "source_kind": "host", "read_only": False}),
  lambda p: p["docker"]["mounts"][4].update(guest="/home/real-account"),
  lambda p: p["child"].update(program="/bin/sh", allowed_args=[["-c", "arbitrary"]]),
  lambda p: p["network"]["denied"].update(host="live.example.com"),
  lambda p: p["budgets"].update(child_count_per_case=20),
], ids=["unknown", "privileged", "host-network", "docker-socket", "host-home", "arbitrary-child", "live-url", "unbounded-child"])
def test_whole_process_closed_plan_rejects_capability_or_scope_expansion(change):
  plan = deepcopy(closed_json((FIXTURE / "plan.json").read_bytes())); change(plan)
  with pytest.raises(Exception) as caught: validate(plan)
  assert caught.type.__module__.startswith("jsonschema")


def test_whole_process_freeze_requires_concrete_nonroot_identity_but_is_not_authorization():
  plan = closed_json((FIXTURE / "plan.json").read_bytes()); plan["execution_state"] = "frozen-pending-separate-authorization"
  with pytest.raises(Exception) as caught: validate(plan)
  assert caught.type.__module__.startswith("jsonschema")
  plan["freeze"].update(image_digest="sha256:" + "a" * 64, candidate_receipt_sha256="b" * 64, node_sha256="c" * 64, container_uid=1234, container_gid=1234)
  with pytest.raises(Exception) as caught: validate(plan)
  assert caught.type.__module__.startswith("jsonschema")
  plan["freeze"]["native_pi_entry"] = "/candidate/synthetic-base-package/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
  validate(plan)
  assert "separate-explicit-native-authorization" in plan["prerequisites"]
  plan["freeze"]["container_uid"] = 0
  with pytest.raises(Exception) as caught: validate(plan)
  assert caught.type.__module__.startswith("jsonschema")


def test_whole_process_has_both_allow_and_deny_oracles_and_honest_native_credential_visibility():
  plan = validate(closed_json((FIXTURE / "plan.json").read_bytes()))
  facts = {row["id"]: row["expected_fact"] for row in plan["cases"]}
  assert facts["allowed-file-read-write"] and facts["allowed-loopback-connect"] and facts["allowed-fixed-child"]
  assert not facts["denied-host-file-read"] and not facts["denied-host-file-write"] and not facts["denied-outbound-connect"] and not facts["denied-child-host-read"]
  assert facts["container-credential-readable"]
  assert closed_json((FIXTURE / "auth.json").read_bytes()) == {"synthetic-whole-process": {"type": "api_key", "key": "synthetic-no-account"}}
  assert "parent-observed-positive-and-negative-facts" in plan["prerequisites"] and "confirmed-container-and-child-termination" in plan["prerequisites"]


@pytest.mark.parametrize("raw", [b'{"schema_version":1,"schema_version":2}', b'{"budget":NaN}'], ids=["duplicate", "nonfinite"])
def test_whole_process_json_cannot_rebind_or_hide_nonfinite_budget(raw):
  with pytest.raises(ValueError): closed_json(raw)


@pytest.mark.parametrize("entry", [
  "/candidate/../outside/node_modules/@earendil-works/pi-coding-agent/dist/cli.js",
  "/candidate/./node_modules/@earendil-works/pi-coding-agent/dist/cli.js",
  "/candidate/package\\nested/node_modules/@earendil-works/pi-coding-agent/dist/cli.js",
  "/candidate/node_modules/@earendil-works/pi-coding-agent/dist/cli.js\n",
], ids=["parent", "dot", "backslash", "control"] )
def test_whole_process_concrete_cli_entry_rejects_noncanonical_paths(entry):
  plan = closed_json((FIXTURE / "plan.json").read_bytes()); plan["freeze"]["native_pi_entry"] = entry
  with pytest.raises(Exception) as caught: validate(plan)
  assert caught.type.__module__.startswith("jsonschema")
