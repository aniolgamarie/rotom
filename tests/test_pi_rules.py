"""规则读取仅限已选择根，正文读前拒绝链接与机器 deny。"""
from pathlib import Path
import pytest
from agentcfg.pi_rules import read_rules
from agentcfg.storage import Conflict
from agentcfg.pi_supervisor import Principal
from test_pi_operations import setup


def fixture(tmp_path):
  _, host, _, manager = setup(tmp_path)
  rules = tmp_path / "declared-rules"; rules.mkdir(); (rules / "one.md").write_text("project convention")
  manifest = host.manifest(); manifest["plugins"] = ["pi-rules"]
  manifest["options"]["paths"]["roots"]["rules"] = {"path": str(rules), "purpose": "read"}
  manifest["options"]["rules"] = {"root_refs": ["rules"]}
  return host, manager, rules


def test_selected_rules_only_and_disabled_has_no_fallback(tmp_path):
  host, manager, root = fixture(tmp_path)
  (tmp_path / "unselected.md").write_text("must not inject")
  assert read_rules(host, manager, {}) == {"rules": [{"id": "rules/one.md", "body": "project convention"}]}
  host.manifest()["options"]["rules"]["enabled"] = False
  assert read_rules(host, manager, {}) == {"rules": []}


@pytest.mark.parametrize("change", ["link", "denied", "worker", "missing"])
def test_rules_fail_closed_on_unavailable_scope(tmp_path, change):
  host, manager, root = fixture(tmp_path)
  if change == "link": (root / "linked.md").symlink_to(tmp_path / "unselected.md")
  if change == "denied": host.manifest()["options"]["permissions"] = {"denied_roots": ["rules"]}
  if change == "worker": manager = Principal("worker")
  if change == "missing": host.manifest()["options"]["paths"]["roots"]["rules"]["path"] = str(tmp_path / "missing")
  with pytest.raises(Conflict): read_rules(host, manager, {})
