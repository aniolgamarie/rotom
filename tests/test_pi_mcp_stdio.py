"""stdio 服务通过专用准入分类，不由模型声明自己不占执行槽。"""
from pathlib import Path
import pytest
from agentcfg.storage import Conflict
from agentcfg.schema import ConfigError
from test_pi_operations import setup


def test_only_selected_stdio_service_can_register_persistent_capacity(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  executable = tmp_path / "server"; executable.write_text("#!/bin/sh\nexit 0\n"); executable.chmod(0o700)
  manifest = host.manifest(); manifest["plugins"] = ["pi-mcp"]
  manifest["options"]["external_tools"] = {"fixture": {"executable": str(executable), "version": "fixture", "project_root": "project",
    "read_roots": ["project"], "write_roots": [], "timeout_seconds": 300, "interactive": True}}
  manifest["options"]["mcp"] = {"servers": {"docs": {"transport": "stdio", "command_ref": "fixture"}, "other": {"transport": "stdio", "command_ref": "fixture"}}}
  manifest["permission_policy"]["rules"].append({"id": "server", "kind": "command", "effect": "allow", "command_ref": "tool:fixture", "tool_ids": ["bash"], "operations": ["execute"]})
  args = {"operation_id": "fixture", "server_name": "docs"}
  ticket = operations.handle(principal, "ordinary_mcp_stdio_prepare", args)
  assert ticket["execution_class"] == "service" and ticket["lease_id"] in host.service.service_leases
  assert operations.handle(principal, "ordinary_mcp_stdio_prepare", args) == ticket
  with pytest.raises(Conflict): operations.handle(principal, "ordinary_mcp_stdio_prepare", {**args, "server_name": "other"})
  with pytest.raises(ConfigError): operations.handle(principal, "ordinary_mcp_stdio_prepare", {**args, "server_name": "missing"})
