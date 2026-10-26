"""人工文本仅当次交互展示；所有恢复后端均为 fake，不获得发送能力。"""
from dataclasses import replace

import pytest

from rotom import cli
from rotom.context import InputPolicy, InvocationContext
from test_rotom_resume_cli import setup


CANARY = "synthetic-private-approved-text"


def feed(streams, text):
  streams.stdin.seek(0)
  streams.stdin.truncate()
  streams.stdin.write(text)
  streams.stdin.seek(0)


def invoke(candidate=None, *, policy="--interactive"):
  args = ([policy] if policy else []) + ["resume", "dsh", "--machine", "synthetic", "--session", "example"]
  return cli.main(args, resume_candidate=candidate)


@pytest.mark.parametrize("policy", ["", "--no-input"])
def test_auto_and_noinput_do_not_read_manual_text_even_on_tty(setup, policy):
  _, candidate, calls, streams, _, _ = setup
  feed(streams, "3\n" + CANARY + "\nyes\n")
  assert invoke(candidate(), policy=policy) == 0
  assert len(calls) == 1 and streams.stdin.tell() == 0
  assert "文本预览" not in streams.stderr.getvalue()


def test_explicit_interactive_recovery_only_option_prepares_no_text(setup):
  _, candidate, calls, streams, _, _ = setup
  feed(streams, "1\n")
  assert invoke(candidate()) == 0 and len(calls) == 1
  assert streams.stdin.tell() == len("1\n") and "文本预览" not in streams.stderr.getvalue()


@pytest.mark.parametrize("choice,text", [("2", "继续"), ("3", "  " + CANARY + "  ")])
def test_text_preview_is_confirmed_before_backend_and_never_passed_or_persisted(setup, tmp_path, choice, text):
  target, candidate, calls, streams, backend, _ = setup
  feed(streams, choice + "\n" + (text + "\n" if choice == "3" else "") + "yes\n")
  before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
  original = backend.resume_session
  def selected(*args, **kwargs):
    output = streams.stderr.getvalue()
    assert "仅在此展示供手工复制，不发送" in output
    assert "请先在官方 TUI 核对会话 ID、原目录和历史" in output
    assert "writer" not in output and "发送权限" not in output
    assert "\n" + text + "\n" in output and "加载未确认" in output
    assert streams.stdin.tell() == len(choice + "\n" + (text + "\n" if choice == "3" else "") + "yes\n")
    return original(*args, **kwargs)
  backend.resume_session = selected
  assert invoke(candidate()) == 0 and calls == [target]
  assert text not in repr(calls) and text not in repr(vars(backend))
  assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
  assert "自行聚焦" in streams.stderr.getvalue()


@pytest.mark.parametrize("answer", ["", "\n", "\x1b\n", "2\nno\n", "3\nbody\n\n", "3\n"])
def test_cancel_or_missing_confirmation_happens_before_any_backend_call(setup, answer):
  _, candidate, calls, streams, _, _ = setup
  feed(streams, answer)
  assert invoke(candidate()) == 130 and calls == []
  assert "文本无效" not in streams.stderr.getvalue()


@pytest.mark.parametrize("stream", ["stdin", "stdout", "stderr"])
def test_explicit_interactive_requires_all_three_tty_streams(setup, monkeypatch, stream):
  _, candidate, calls, streams, _, loads = setup
  monkeypatch.setattr(getattr(streams, stream), "isatty", lambda: False)
  feed(streams, "2\nyes\n")
  assert invoke(candidate()) == 2 and calls == loads == [] and streams.stdin.tell() == 0


@pytest.mark.parametrize("text", ["prefix\t" + CANARY, "prefix\x00" + CANARY,
  "prefix\x1b" + CANARY, "prefix\x7f" + CANARY, "prefix\x85" + CANARY,
  "prefix\ud800" + CANARY, "x" * 4097])
def test_invalid_custom_body_has_fixed_error_and_no_preview_or_dispatch(setup, text):
  _, candidate, calls, streams, _, _ = setup
  feed(streams, "3\n" + text + "\nyes\n")
  assert invoke(candidate()) == 2 and calls == []
  output = streams.stderr.getvalue()
  assert CANARY not in output and "文本预览" not in output
  assert "文本无效" in output and "4096" in output and "16384" in output
  assert "可打印单行" in output and "未发送" in output


def test_maximum_utf8_text_is_kept_exactly_and_helper_returns_no_text(setup):
  from rotom.manual_continue import offer
  _, _, calls, streams, _, _ = setup
  text = "😀" * 4096
  feed(streams, "3\n" + text + "\nyes\n")
  context = InvocationContext(("resume",), input_policy=InputPolicy.INTERACTIVE, input_gateway=streams)
  assert offer(context, "requested synthetic target") is None
  assert "\n" + text + "\n" in streams.stderr.getvalue() and calls == []
  assert CANARY not in repr(context)


def test_daily_registered_route_previews_text_without_sending_or_persisting(setup, tmp_path, monkeypatch):
  from rotom import resume
  target, candidate, calls, streams, _, loads = setup
  monkeypatch.setattr(resume, "dsh_candidate", lambda: candidate())
  feed(streams, "3\n" + CANARY + "\nyes\n")
  assert invoke() == 0 and calls == [target] and len(loads) == 1
  text = streams.stderr.getvalue()
  assert CANARY in text and "请求恢复" in text and "加载未确认" in text
  assert CANARY not in repr(calls)
  assert not any(CANARY.encode() in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


def test_invalid_target_or_location_does_not_offer_text_menu(setup):
  target, candidate, calls, streams, _, _ = setup
  feed(streams, "2\nyes\n")
  assert cli.main(["--interactive", "resume", "dsh", "--session", "example", "--original"], resume_candidate=candidate()) == 5
  assert streams.stdin.tell() == 0 and calls == []
  assert invoke(candidate((replace(target, cwd=None, cwd_status="unknown"),))) == 5
  assert streams.stdin.tell() == 0 and calls == []


def test_repeating_invocations_requires_new_explicit_menu_selection(setup):
  _, candidate, calls, streams, _, _ = setup
  feed(streams, "2\nyes\n")
  assert invoke(candidate()) == 0 and len(calls) == 1
  assert invoke(candidate()) == 130 and len(calls) == 1


def test_text_menu_ctrl_c_is_cancellation_without_backend(setup, monkeypatch):
  _, candidate, calls, streams, _, _ = setup
  def interrupted():
    raise KeyboardInterrupt()
  monkeypatch.setattr(streams.stdin, "readline", interrupted)
  assert invoke(candidate()) == 130 and calls == []


def test_resume_help_describes_explicit_interactive_manual_only(capsys):
  assert cli.main(["resume", "--help"]) == 0
  text = capsys.readouterr().out
  assert "--interactive" in text and "仅显示" in text and "不发送" in text
  assert "4096" in text and "16384" in text and "可打印单行" in text


def test_backend_is_not_constructed_or_called_during_manual_ui(setup, monkeypatch):
  from rotom.resume import CandidateResume
  target, _, calls, streams, backend, _ = setup
  factories = []
  original = streams.stdin.readline
  def reading():
    assert factories == calls == []
    return original()
  monkeypatch.setattr(streams.stdin, "readline", reading)
  feed(streams, "3\n" + CANARY + "\nyes\n")
  def selected(row):
    factories.append(row)
    return backend
  candidate = CandidateResume(lambda scope: (target.scope, (target,)), selected)
  assert invoke(candidate) == 0 and factories == calls == [target]


def test_unknown_backend_result_after_display_remains_not_sent_without_replay(setup):
  _, candidate, calls, streams, backend, _ = setup
  feed(streams, "2\nyes\n")
  def lost(target, *, location, before_dispatch, after_dispatch):
    calls.append(target)
    before_dispatch("b" * 32)
    after_dispatch("b" * 32)
    raise ConnectionError("synthetic-private-lost-reply")
  backend.resume_session = lost
  assert invoke(candidate()) == 4 and len(calls) == 1
  text = streams.stderr.getvalue()
  assert "恢复结果未知" in text and "未发送继续" in text and "不自动重试" in text
  assert "synthetic-private-lost-reply" not in text


def test_manual_approval_cannot_replace_coordinator_target_recheck(setup, monkeypatch):
  from rotom.context import InputGateway
  target, candidate, calls, streams, _, _ = setup
  feed(streams, "2\nyes\n")
  original = InputGateway.confirm
  def changed(gateway, *args, **kwargs):
    result = original(gateway, *args, **kwargs)
    from pathlib import Path
    Path(target.cwd).rmdir()
    return result
  monkeypatch.setattr(InputGateway, "confirm", changed)
  assert invoke(candidate()) == 2 and calls == []


def test_target_control_characters_are_escaped_in_manual_display(setup):
  from rotom.manual_continue import offer
  _, _, _, streams, _, _ = setup
  feed(streams, "2\nyes\n")
  context = InvocationContext(("resume",), input_policy=InputPolicy.INTERACTIVE, input_gateway=streams)
  offer(context, "synthetic-id\x1b[31m\nsynthetic-cwd")
  output = streams.stderr.getvalue()
  assert "\x1b" not in output and "synthetic-id" in output
  assert "\\nsynthetic-cwd" in output
