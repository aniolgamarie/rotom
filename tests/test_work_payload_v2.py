"""一次性 v2 JSON 边界；仅解析合成输入。"""
from copy import deepcopy
import json
from pathlib import Path
import time

import pytest

from termcfg.errors import TermcfgError


def payload(tmp_path, *, action="workspace-initial", launcher="shell"):
  from termcfg.work_state import launch_digest
  launch = {"launcher": launcher, "argv": ["/bin/synthetic-launcher"],
    "runtime": ({"generation": "c" * 64, "identity": "synthetic-runtime", "policy": "isolated"}
      if launcher in ("pi", "dsh") else None), "paths": {"HOME": str(tmp_path)}}
  value = {"version": 2, "action": action, "kind": "default", "op": "a" * 32,
    "instance": "b" * 32, "epoch": "c" * 32, "owner": "d" * 64,
    "context_kind": "named", "type": "problem", "workspace_start": str(tmp_path),
    "cwd": str(tmp_path), "captured_home": str(tmp_path), "launch": launch,
    "binding_digest": launch_digest(tmp_path, tmp_path, launch), "local": str(tmp_path / "local.toml"),
    "session": "trial", "socket_path": str(tmp_path / "api.sock"), "endpoint_dev": 7,
    "endpoint_ino": 11, "rotom_root": str(tmp_path / "trusted-root"), "source_digest": "e" * 64,
    "selection_digest": "f" * 64, "intent_path": str(tmp_path / "intents" / ("a" * 32 + ".json")),
    "expires_at_ns": time.monotonic_ns() + 20_000_000_000}
  if action == "tab":
    value["workspace_id"] = "workspace-1"
  return value


def encoded(value):
  return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@pytest.mark.parametrize("action", ["workspace-initial", "tab"])
@pytest.mark.parametrize("launcher", ["shell", "editor", "pi", "dsh", "codex"])
def test_complete_v2_envelope_roundtrip(tmp_path, action, launcher):
  from termcfg.work_shell import parse_payload_v2
  value = payload(tmp_path, action=action, launcher=launcher)
  assert parse_payload_v2(encoded(value)) == value


@pytest.mark.parametrize("change", [
  lambda p: p.update(version=True), lambda p: p.update(version=2.0),
  lambda p: p.update(version=1), lambda p: p.update(unknown="not allowed"),
  lambda p: p.pop("intent_path"), lambda p: p.update(action="replay"),
  lambda p: p.update(kind="extra"), lambda p: p.update(type="problem1;exec"),
  lambda p: p.update(type="\u4e2d\u6587"), lambda p: p.update(context_kind="problem"),
  lambda p: p.update(workspace_id="not-known-before-creation"),
  lambda p: p.update(endpoint_dev=True), lambda p: p.update(endpoint_ino=11.0),
  lambda p: p.update(cwd="relative"), lambda p: p.update(local="/unsafe/../file"),
  lambda p: p.update(captured_home="/bad\nvalue"), lambda p: p.update(owner="g" * 64),
  lambda p: p.update(binding_digest="a" * 64),
  lambda p: p.update(expires_at_ns=time.monotonic_ns() - 1),
  lambda p: p.update(expires_at_ns=time.monotonic_ns() + 90_000_000_000),
  lambda p: p["launch"].update(command="not allowed"),
  lambda p: p["launch"]["paths"].update(TOKEN="forbidden"),
  lambda p: p["launch"].update(runtime={"generation": "a" * 64, "identity": "x", "policy": "caller"}),
])
def test_invalid_v2_envelope_fails_without_raw_payload(tmp_path, change):
  from termcfg.work_shell import parse_payload_v2
  value = payload(tmp_path)
  change(value)
  with pytest.raises(TermcfgError) as error:
    parse_payload_v2(encoded(value))
  assert error.value.code == 2
  assert str(tmp_path) not in str(error.value)


def test_tab_requires_workspace_and_initial_never_accepts_extra(tmp_path):
  from termcfg.work_shell import parse_payload_v2
  value = payload(tmp_path, action="tab")
  value["kind"] = "extra"
  assert parse_payload_v2(encoded(value))["kind"] == "extra"
  value.pop("workspace_id")
  with pytest.raises(TermcfgError):
    parse_payload_v2(encoded(value))


def test_v2_duplicate_nonfinite_invalid_unicode_depth_and_size(tmp_path):
  from termcfg.work_shell import parse_payload_v2
  value = encoded(payload(tmp_path))
  invalid = [value.replace('"version":2', '"version":2,"version":2'),
    value.replace('"version":2', '"version":NaN'),
    value.replace('"version":2', '"version":Infinity'),
    value.replace('"type":"problem"', '"type":"\\ud800"'),
    "[" * 2000 + "0" + "]" * 2000]
  huge = payload(tmp_path)
  huge["launch"]["argv"].append("x" * 17000)
  invalid.append(encoded(huge))
  for text in invalid:
    with pytest.raises(TermcfgError):
      parse_payload_v2(text)


def test_managed_agent_budget_uses_launcher_not_type_name(tmp_path):
  from termcfg.work_shell import parse_payload_v2
  for launcher in ("pi", "dsh"):
    value = payload(tmp_path, launcher=launcher)
    value["expires_at_ns"] = time.monotonic_ns() + 50_000_000_000
    assert parse_payload_v2(encoded(value))["type"] == "problem"
