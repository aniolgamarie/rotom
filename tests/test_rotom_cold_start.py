"""冷启动边界：构造命令语法不加载终端执行器或模板引擎。"""

import builtins
import importlib.util
import sys

from rotom import cli


def test_parser_does_not_import_terminal_execution(monkeypatch):
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    if name in ("termcfg.cli", "termcfg.transaction", "termcfg.preview", "termcfg.packages"):
      raise AssertionError("parser imported terminal execution")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  parser = cli.build_parser()
  args = parser.parse_args(["term", "apply", "--machine", "fixture", "--plan-id", "PLAN_ID"])
  assert args.command == "apply" and args.machine == "fixture" and args.plan_id == "PLAN_ID"


def test_legacy_and_facade_share_terminal_parser():
  from termcfg import cli as terminal
  from termcfg import cli_parser
  assert terminal.build_parser is cli_parser.build_parser
  assert terminal.Parser is cli_parser.Parser


def test_loading_render_helpers_does_not_load_template_engine(monkeypatch):
  from agentcfg import render
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    if name == "jinja2" or name.startswith("jinja2."):
      raise AssertionError("read-only helpers imported template engine")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  spec = importlib.util.spec_from_file_location("agentcfg._render_cold_test", render.__file__)
  module = importlib.util.module_from_spec(spec)
  monkeypatch.setitem(sys.modules, spec.name, module)
  spec.loader.exec_module(module)
  assert module.serialize_structured({"value": "synthetic"}, format="json") == b'{"value":"synthetic"}\n'
