"""下一步只是带上下文的建议，不执行命令或扩大诊断权限。"""

from argparse import Namespace
from copy import deepcopy
import json
import shlex

import pytest

from termcfg.cli import build_parser
from termcfg.guidance import context_for, hint, resolve_hints


def context(**changes):
  values = {"machine": "workstation", "component": ["zsh", "tmux"]}
  values.update(changes)
  return context_for(Namespace(**values))


def parsed(command):
  words = shlex.split(command)
  assert words.pop(0) == "./termcfg"
  return build_parser().parse_args(words)


@pytest.mark.parametrize("command", ["plan", "doctor", "status", "apply"])
def test_named_machine_and_multiple_components(command):
  result = parsed(hint(command).render(context()))
  assert result.machine == "workstation"
  assert result.component == ["zsh", "tmux"]


@pytest.mark.parametrize("command, words", [("recover", ()), ("migrate", ("--drop-mihomo",))])
def test_machine_wide_suggestions_do_not_invent_component_flags(command, words):
  result = parsed(hint(command, *words).render(context()))
  assert result.machine == "workstation"
  assert not hasattr(result, "component")


def test_per_component_suggestion_does_not_expand_to_other_components():
  result = parsed(hint("sync", components=("zsh",)).render(context()))
  assert result.machine == "workstation"
  assert result.component == "zsh"


def test_single_component_destination_never_silently_drops_selection():
  result = parsed(hint("sync").render(context()))
  assert result.command == "doctor"
  assert result.component == ["zsh", "tmux"]


def test_initializer_fallback_yields_to_explicit_selection():
  action = hint("init-local", fallback_components=("zsh",))
  assert str(action) == "./termcfg init-local --component zsh"
  result = parsed(action.render(context(component=["tmux"])))
  assert result.component == ["tmux"]


@pytest.mark.parametrize("command", ["plan", "doctor", "status"])
def test_verified_diagnostic_home_is_quoted_and_retained(command):
  home = "/path/to/中文 home/$(literal)"
  value = context(home=home, _guidance_home=home)
  result = parsed(hint(command).render(value))
  assert result.home == home
  assert result.machine == "workstation"


@pytest.mark.parametrize("command, expected", [("apply", "plan"), ("recover", "status"), ("migrate", "status")])
def test_diagnostic_home_does_not_authorize_writes_or_transfer_plan_id(command, expected):
  value = context(home="/path/to/preview", _guidance_home="/path/to/preview")
  result = parsed(hint(command, "--plan-id", "a" * 64).render(value))
  assert result.command == expected
  assert result.home is None
  assert not hasattr(result, "plan_id")
  assert result.machine == "workstation"


def test_invalid_home_is_not_echoed_or_turned_into_a_default_target():
  rendered = hint("apply").render(context(home="PRIVATE-CANARY"))
  assert "PRIVATE-CANARY" not in rendered
  assert rendered == "./termcfg plan --help"


def test_invalid_machine_is_not_echoed_or_guessed():
  rendered = hint("init-local").render(context(machine="PRIVATE-CANARY/invalid"))
  assert rendered == "./termcfg --help"
  assert "PRIVATE-CANARY" not in rendered


def test_duplicate_or_invalid_components_lead_to_help():
  for selection in (["zsh", "zsh"], ["PRIVATE-CANARY"]):
    assert hint("doctor").render(context(component=selection)) == "./termcfg doctor --help"


def test_hint_remains_a_json_string_without_rewriting_arbitrary_strings():
  action = hint("plan")
  payload = {"next_command": action, "ready": False, "reason": "target_drift",
    "components": {"zsh": {"next_command": hint("plan", components=("zsh",))}},
    "environment": {"tmux": {"next_command": hint("doctor", components=("tmux",))}},
    "unknown": {"next_command": "./termcfg PRIVATE-CANARY"}}
  before = deepcopy(payload)
  result = resolve_hints(payload, context())
  assert payload == before
  assert json.loads(json.dumps(action)) == "./termcfg plan"
  assert result["unknown"] is payload["unknown"]
  assert result["unknown"]["next_command"] == "./termcfg PRIVATE-CANARY"
  assert result["reason"] == payload["reason"]
  assert set(result) == set(payload)
  assert parsed(result["next_command"]).component == ["zsh", "tmux"]
  assert parsed(result["components"]["zsh"]["next_command"]).component == ["zsh"]
  assert parsed(result["environment"]["tmux"]["next_command"]).component == ["tmux"]


def test_plain_next_command_is_not_parsed_or_rewritten():
  payload = {"next_command": "./termcfg doctor; PRIVATE-CANARY"}
  assert resolve_hints(payload, context()) == payload


def test_known_tokens_are_shell_quoted_without_execution(monkeypatch):
  import subprocess
  monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch a process"))
  action = hint("lock", "--plugin", "literal $(value)", "--version", "a" * 40, components=("zsh",))
  result = parsed(action.render(context()))
  assert result.plugin == "literal $(value)"


def test_context_has_only_safe_display_metadata():
  value = context(home="PRIVATE-CANARY", component="tmux")
  assert value.public() == {"machine": "workstation", "components": ("tmux",), "diagnostic_home": True}
  assert "PRIVATE-CANARY" not in repr(value.public())
