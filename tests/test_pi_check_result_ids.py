"""固定 required IDs 进入真实 Host 编译契约；不执行 checker 或 SDK。"""

import pytest

from agentcfg.pi_catalog import validate
from agentcfg.pi_trusted_checks import contract_digest
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from agentcfg.pi_checks import verify_check
from test_pi_trusted_checks import fixture


def test_required_test_ids_bind_host_result_contract_and_source_identity(tmp_path):
  f = fixture(tmp_path)
  baseline = f.compile()
  f.binding["required_test_ids"] = ["case:one", "case:two"]
  validate("options", {"checks": {"test": f.binding}})
  check = f.compile(); verify_check(check)
  assert check["result_contract"]["required_test_ids"] == ["case:one", "case:two"]
  assert contract_digest(check) != contract_digest(baseline)
  f.binding["required_test_ids"] = ["case:one", "case:three"]
  f.compile()
  with pytest.raises(Conflict): verify_check(check)


@pytest.mark.parametrize("value", [None, [], ["same", "same"], [True], ["bad/name"], [""], ["x" * 201]])
def test_invalid_required_ids_are_rejected_by_schema_and_compile(tmp_path, value):
  f = fixture(tmp_path); f.binding["required_test_ids"] = value
  with pytest.raises(ConfigError): validate("options", {"checks": {"test": f.binding}})
  with pytest.raises(ConfigError): f.compile()


@pytest.mark.parametrize("kind,parser", [("build", "exit-code"), ("tests", "pytest"), ("tests", "tap")])
def test_required_ids_cannot_be_inferred_from_aggregate_only_formats(tmp_path, kind, parser):
  f = fixture(tmp_path); f.binding.update(kind=kind, parser=parser, required_test_ids=["case:one"])
  with pytest.raises(ConfigError, match="pi-check-test-id-contract"): f.compile()


def test_absent_required_ids_preserve_the_existing_binding_shape(tmp_path):
  f = fixture(tmp_path); check = f.compile(); verify_check(check)
  assert "required_test_ids" not in check["result_contract"]


@pytest.mark.parametrize("parser", ["json", "tap", "pytest"])
def test_normal_catalog_and_adapter_validate_supported_schema_without_conditional_keywords(tmp_path, parser):
  from pathlib import Path
  from agentcfg.workspace import load_public_catalog
  from agentcfg.pi import PiAdapter
  from test_pi_adapter import pi_data
  root = Path(__file__).resolve().parents[1]
  catalog, _ = load_public_catalog(repository=root)
  assert catalog is not None
  data = pi_data(tmp_path)
  options = data["profile"]["agent_options"]
  options["paths"] = {"roots": {"project": {"path": str(tmp_path), "purpose": "project"}}}
  options["checks"] = {"test": {"executable": "/usr/bin/true", "args": [], "project_root": "project",
    "foreground": True, "timeout_seconds": 5, "kind": "tests", "parser": parser, "minimum_tests": 1,
    "inputs": [], "required_test_ids": ["fixed:case"]}}
  if parser == "json": PiAdapter(root).validate(data)
  else:
    with pytest.raises(ConfigError, match="pi-check-test-id-contract"): PiAdapter(root).validate(data)
