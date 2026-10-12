"""准备工件的闭合协议与诱饵完整性；默认从不 import/运行官方 SDK。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


FIXTURE = Path(__file__).resolve().parent / "fixtures/pi/official-sdk-probe"


def document(name):
  return json.loads((FIXTURE / name).read_bytes())


def test_probe_fixture_is_closed_and_every_mounted_source_has_content_identity():
  plan = document("plan.json")
  Draft202012Validator(document("plan.schema.json")).validate(plan)
  actual = {path.relative_to(FIXTURE).as_posix() for path in FIXTURE.rglob("*") if path.is_file()} - {"plan.json", "plan.schema.json", "result.schema.json"}
  assert actual == set(plan["files"])
  for relative, expected in plan["files"].items():
    path = FIXTURE / relative
    assert not path.is_symlink() and path.resolve().is_relative_to(FIXTURE)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
  targets = [item["target"] for item in plan["placements"]]
  assert len(targets) == len(set(targets))
  assert all(Path(target).is_relative_to("/work") and ".." not in Path(target).parts for target in targets)
  assert all(item["source"] in plan["files"] for item in plan["placements"])
  assert {"/work/agent/AGENTS.md", "/work/ancestor/AGENTS.md", "/work/ancestor/project/AGENTS.md"} <= set(targets)


@pytest.mark.parametrize("fault", ["external-provider", "real-auth-route", "unknown-field", "home", "source-escape", "target-escape", "version", "hash"])
def test_probe_protocol_rejects_external_routes_or_mount_source_substitution(fault):
  plan = deepcopy(document("plan.json"))
  if fault == "external-provider": plan["provider"]["base_url"] = "https://api.openai.com/v1"
  if fault == "real-auth-route": plan["provider"]["api_key"] = "$ACCOUNT_TOKEN"
  if fault == "unknown-field": plan["provider"]["oauth"] = True
  if fault == "home": plan["paths"]["home"] = "/home/real-user"
  if fault == "source-escape": plan["placements"][0]["source"] = "../../outside"
  if fault == "target-escape": plan["placements"][0]["target"] = "/work/../home/real-user/config"
  if fault == "version": plan["versions"]["pi"] = "latest"
  if fault == "hash": plan["files"]["approved-extension.mjs"] = "f" * 64
  assert not Draft202012Validator(document("plan.schema.json")).is_valid(plan)


@pytest.mark.parametrize("fault", ["passed", "approval", "unknown-case", "private-error", "secret-value"])
def test_probe_output_protocol_does_not_issue_product_pass_or_authorization(fault):
  value = {"schema_version": 1, "probe_id": "official-sdk-1.0.1", "versions": {"pi": None, "pi_ai": None},
    "status": "failed", "cases": [], "limitations": ["Synthetic protocol fixture, not native execution evidence"]}
  checker = Draft202012Validator(document("result.schema.json"))
  assert checker.is_valid(value)
  if fault == "passed": value["status"] = "passed"
  if fault == "approval": value["accepted"] = True
  if fault == "unknown-case": value["cases"] = [{"case_id": "production-release", "outcome": "observed", "observations": {}}]
  if fault == "private-error": value["error"] = "private SDK exception"
  if fault == "secret-value": value["credentials"] = {"account": "secret"}
  assert not checker.is_valid(value)
