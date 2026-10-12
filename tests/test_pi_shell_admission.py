"""实际 Shell 准备器接一次许可账本；只核对准入，不启动命令或分配 Writer。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg.pi_shell_preparation import prepare_shell
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_operation_admission import fixture
from test_pi_shell_preparation import shell_case


def admitted(shell_case):
  ledger, current, _, _, clock = fixture()
  current["cwd"] = shell_case["cwd"]
  # 此组合测试采用只读 Shell；写入口另须绑定实际工作区身份与 ExecutionStore。
  shell_case["binding"]["write_roots"] = []
  part = prepare_shell(**shell_case)
  operation = ledger.prepare("actual-shell-input", current=current, resolved=part["resolution"],
    private_input=part["private_input"])
  return ledger, current, part, operation, clock


def human_permit(ledger, current, operation):
  return ledger.issue(operation["operation_id"], operation_digest=operation["operation_digest"],
    current=current, source="human")


def test_actual_prepared_script_requires_a_decision_and_is_consumed_without_body_projection(shell_case):
  ledger, current, part, operation, _ = admitted(shell_case)
  with pytest.raises(Conflict, match="HUMAN_REQUIRED"):
    ledger.issue(operation["operation_id"], operation_digest=operation["operation_digest"],
      current=current, source="deterministic-policy")
  permit = human_permit(ledger, current, operation)
  # 修改调用者副本不能替换已经批准的脚本；消费返回账本内的原始私有正文。
  part["private_input"]["command"] = "printf replacement"
  result = ledger.consume(permit, current=current, resolved=prepare_shell(**shell_case)["resolution"])
  assert result["private_input"] == {"command": shell_case["command"]}
  public = json.dumps([operation, permit, ledger.status(operation["operation_id"])], sort_keys=True)
  assert "private shell marker" not in public
  assert hashlib.sha256(shell_case["command"].encode()).hexdigest() not in public


@pytest.mark.parametrize("change", ["executable", "root", "timeout", "policy", "restrictions"])
def test_reprepared_physical_or_policy_change_invalidates_the_actual_shell_permit(shell_case, change):
  ledger, current, part, operation, _ = admitted(shell_case)
  permit = human_permit(ledger, current, operation)
  if change == "executable":
    path = Path(shell_case["binding"]["executable"])
    path.write_bytes(b"replaced synthetic executable, never executed")
  elif change == "root":
    path = Path(shell_case["cwd"])
    path.rename(path.with_name("old-project"))
    path.mkdir()
  elif change == "timeout": shell_case["timeout_seconds"] = 1
  elif change == "policy": shell_case["permission_policy"]["rules"][0]["id"] = "replacement-allow"
  else: shell_case["permissions"] = {"policy_ref": "new-policy-reference"}
  fresh = prepare_shell(**shell_case)
  assert fresh["resolution"] != part["resolution"]
  with pytest.raises(Conflict, match="RESOLUTION_STALE"):
    ledger.consume(permit, current=current, resolved=fresh["resolution"])
  with pytest.raises(Conflict, match="PERMIT_USED"):
    ledger.consume(permit, current=current, resolved=part["resolution"])


def test_writer_preparation_cannot_enter_ledger_before_workspace_identity_binding(shell_case):
  ledger, current, _, _, _ = fixture()
  current["cwd"] = shell_case["cwd"]
  part = prepare_shell(**shell_case)
  assert part["resolution"]["write_roots"] and part["resolution"]["workspace_keys"] == []
  with pytest.raises(ConfigError):
    ledger.prepare("incomplete-writer", current=current, resolved=part["resolution"], private_input=part["private_input"])


def test_changed_private_script_cannot_reuse_actual_preparation_request(shell_case):
  ledger, current, _, _, _ = admitted(shell_case)
  changed = deepcopy(shell_case)
  changed["command"] = "printf 'new private shell marker'"
  part = prepare_shell(**changed)
  with pytest.raises(Conflict, match="IDEMPOTENCY_CONFLICT"):
    ledger.prepare("actual-shell-input", current=current, resolved=part["resolution"], private_input=part["private_input"])


def test_replacing_cwd_below_unchanged_project_root_invalidates_the_permit(shell_case):
  cwd = Path(shell_case["cwd"]) / "build"
  cwd.mkdir()
  shell_case["cwd"] = str(cwd)
  ledger, current, part, operation, _ = admitted(shell_case)
  permit = human_permit(ledger, current, operation)
  cwd.rename(cwd.with_name("old-build"))
  cwd.mkdir()
  fresh = prepare_shell(**shell_case)
  assert fresh["resolution"]["read_roots"] == part["resolution"]["read_roots"]
  with pytest.raises(Conflict, match="RESOLUTION_STALE"):
    ledger.consume(permit, current=current, resolved=fresh["resolution"])
