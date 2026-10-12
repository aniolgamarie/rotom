"""默认inert封闭计划；不导入Host/SDK、不执行guest。"""
import importlib.util
import json
from pathlib import Path


def test_plan_has_fixed_authority_cases_and_no_external_argv():
  root = Path(__file__).resolve().parents[4]
  spec = importlib.util.spec_from_file_location("own_authority_probe", root / "scripts/pi-probe-base-authority.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  plan = json.loads(Path(__file__).with_name("plan.json").read_text())
  assert module.validate_plan(plan) == plan
  import pytest
  with pytest.raises(AssertionError):
    module.validate_plan({**plan, "argv": ["arbitrary"]})
  with pytest.raises(AssertionError):
    module.validate_plan({**plan, "cases": [*plan["cases"], "shell"]})
