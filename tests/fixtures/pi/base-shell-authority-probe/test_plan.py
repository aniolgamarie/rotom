import importlib.util
import json
from pathlib import Path
import pytest


def test_shell_plan_is_exact_and_cannot_enable_extra_commands():
  file = Path(__file__).with_name("driver.py")
  spec = importlib.util.spec_from_file_location("own_shell_authority", file)
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  plan = json.loads(file.with_name("plan.json").read_text())
  assert module.validate_plan(plan) == plan
  with pytest.raises(AssertionError): module.validate_plan({**plan, "argv": ["arbitrary"]})
  with pytest.raises(AssertionError): module.validate_plan({**plan, "cases": [*plan["cases"], "extra"]})


def test_selected_real_shell_binding_passes_original_schema_and_missing_version_fails():
  from agentcfg.pi_catalog import validate
  from agentcfg.schema import ConfigError
  binding = json.loads(Path(__file__).with_name("binding.json").read_text())
  validate("options", {"external_tools": {"shell": binding}})
  with pytest.raises(ConfigError):
    validate("options", {"external_tools": {"shell": {key: value for key, value in binding.items() if key != "version"}}})
