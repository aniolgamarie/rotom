"""配置准入只读取临时配置／虚构令牌；不读取实际 /etc、账号或调用 macOS API。"""

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agentcfg import pi_codex_admission as admission
from agentcfg.secrets import CredentialError
from agentcfg.storage import Tree


def auth_document(plan="plus"):
  payload = {"https://api.openai.com/auth": {"chatgpt_plan_type": plan}, "email": "synthetic-private-email"}
  token = "header." + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=") + ".signature"
  return {"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "tokens": {"id_token": token,
    "access_token": "synthetic-private-access", "refresh_token": "synthetic-private-refresh", "account_id": "synthetic-account"}}


@pytest.fixture
def configured(tmp_path, monkeypatch):
  parent = tmp_path / "system"; parent.mkdir(mode=0o700)
  monkeypatch.setattr(admission, "SYSTEM_DIRECTORY", parent / "codex")
  monkeypatch.setattr(admission.sys, "platform", "linux")
  home = tmp_path / "codex-home"
  with Tree(home, create=True) as tree: tree.write_state("auth.json", json.dumps(auth_document()).encode())
  return home, parent / "codex"


def test_personal_account_has_only_nonsecret_nonatomic_admission(configured):
  home, _ = configured
  before = (home / "auth.json").read_bytes()
  proof = admission.admit_codex_execution(home)
  assert proof["account_class"] == "personal" and proof["atomic_config_binding"] is False
  assert "synthetic" not in json.dumps(proof)
  assert (home / "auth.json").read_bytes() == before


@pytest.mark.parametrize("name", [*admission.SYSTEM_FILES, "rules", "skills", "future-source"])
def test_system_sources_reject_before_reading_instance_auth(configured, monkeypatch, name):
  home, directory = configured; directory.mkdir(mode=0o700)
  (directory / name).symlink_to(directory / "missing-private-target")
  monkeypatch.setattr(admission, "Tree", lambda *_args: pytest.fail("auth must not be read"))
  with pytest.raises(admission.CodexAdmissionError, match="^CODEX_SYSTEM_CONFIG_PRESENT$"):
    admission.admit_codex_execution(home)


@pytest.mark.parametrize("kind", ["symlink", "world-writable", "not-directory", "unreadable"])
def test_unknown_system_directory_fails_closed(configured, monkeypatch, kind):
  home, directory = configured
  if kind == "symlink": directory.symlink_to(home, target_is_directory=True)
  elif kind == "not-directory": directory.write_text("synthetic private body")
  else:
    directory.mkdir(mode=0o700)
    if kind == "world-writable": directory.chmod(0o777)
    else: monkeypatch.setattr(admission.os, "open", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("private path")))
  with pytest.raises(admission.CodexAdmissionError, match="^CODEX_SYSTEM_CONFIG_UNVERIFIED$"):
    admission.admit_codex_execution(home)


@pytest.mark.parametrize("plan", ["business", "enterprise", "edu", "team", "self_serve_business_prolite", "ent26", "hc"])
def test_organization_plans_remain_explicitly_unsupported(configured, plan):
  home, _ = configured
  with Tree(home) as tree: tree.write_state("auth.json", json.dumps(auth_document(plan)).encode())
  with pytest.raises(admission.CodexAdmissionError, match="^CODEX_ORGANIZATION_ACCOUNT_UNSUPPORTED$"):
    admission.admit_codex_execution(home)


@pytest.mark.parametrize("change", ["unknown-plan", "missing-plan", "mode", "ambiguous-key", "unknown-field", "duplicate", "bad-jwt", "permissions", "hardlink"])
def test_unknown_or_unsafe_auth_never_becomes_personal_support(configured, change):
  home, _ = configured; value = auth_document()
  if change == "unknown-plan": value = auth_document("future-private-plan")
  elif change == "missing-plan": value = auth_document(None)
  elif change == "mode": value["auth_mode"] = "personalAccessToken"
  elif change == "ambiguous-key": value["OPENAI_API_KEY"] = "synthetic-private-key"
  elif change == "unknown-field": value["future"] = "synthetic-secret"
  elif change == "bad-jwt": value["tokens"]["id_token"] = "private invalid token"
  raw = json.dumps(value).encode() if change != "duplicate" else b'{"tokens":null,"tokens":{},"private":"synthetic-secret"}'
  with Tree(home) as tree: tree.write_state("auth.json", raw)
  if change == "permissions": (home / "auth.json").chmod(0o644)
  if change == "hardlink": os.link(home / "auth.json", home / "alias")
  with pytest.raises(admission.CodexAdmissionError, match="^CODEX_ACCOUNT_CONFIG_UNVERIFIED$"):
    admission.admit_codex_execution(home)


def test_missing_login_keeps_credential_exit_class(configured):
  home, _ = configured; (home / "auth.json").unlink()
  with pytest.raises(CredentialError): admission.admit_codex_execution(home)


def test_explicit_api_key_account_has_no_cloud_plan_and_never_exports_key(configured):
  home, _ = configured
  with Tree(home) as tree: tree.write_state("auth.json", b'{"auth_mode":"apikey","OPENAI_API_KEY":"synthetic-private-api-key"}')
  proof = admission.admit_codex_execution(home)
  assert proof["account_class"] == "api-key"
  assert "synthetic" not in json.dumps(proof)


@pytest.mark.parametrize("result", [True, False, "unknown", PermissionError("private MDM contents")])
def test_macos_uses_preferences_probe_and_rejects_unverified_sources(configured, monkeypatch, result):
  home, _ = configured
  monkeypatch.setattr(admission.sys, "platform", "darwin")
  def probe():
    if isinstance(result, Exception): raise result
    return result
  monkeypatch.setattr(admission, "_managed_preferences_present", probe)
  if result is False:
    assert admission.admit_codex_execution(home)["managed_preferences"] == "absent"
  else:
    with pytest.raises(admission.CodexAdmissionError, match="^CODEX_MANAGED_PREFERENCES_" + ("PRESENT" if result is True else "UNVERIFIED") + "$"):
      admission.admit_codex_execution(home)


@pytest.mark.parametrize("present", [None, b"config_toml_base64", b"requirements_toml_base64"])
def test_core_foundation_queries_exact_cli_domain_and_releases_without_decoding(present):
  allocated, freed, queries = {}, [], []
  def create(_allocator, value, encoding):
    assert encoding == 0x08000100
    pointer = len(allocated) + 1; allocated[pointer] = value; return pointer
  def copy(key, domain):
    assert allocated[domain] == b"com.openai.codex"
    queries.append(allocated[key])
    return 99 if allocated[key] == present else None
  framework = SimpleNamespace(CFStringCreateWithCString=Mock(side_effect=create),
    CFPreferencesCopyAppValue=Mock(side_effect=copy), CFRelease=Mock(side_effect=freed.append))
  assert admission._managed_preferences_present(framework) is (present is not None)
  assert set(allocated).issubset(freed)
  assert (99 in freed) is (present is not None)
  assert queries == ([b"config_toml_base64"] if present == b"config_toml_base64" else [b"config_toml_base64", b"requirements_toml_base64"])


def test_only_allowlisted_reasons_survive_supervisor_and_cli_error_channels(tmp_path):
  from agentcfg.pi_supervisor import SupervisorService
  from agentcfg.model_delegate_cli import DelegateFailure
  service = object.__new__(SupervisorService)
  service.authenticate = lambda *args: None
  for error, expected in ((admission.CodexAdmissionError("CODEX_SYSTEM_CONFIG_PRESENT"), "CODEX_SYSTEM_CONFIG_PRESENT"),
      (ValueError("synthetic-private-token"), "PI_CONTROL_REJECTED")):
    def fail(*args): raise error
    service.handle = fail
    reply = service.reply("synthetic", os.geteuid(), {})
    assert reply["error"] == expected and "private" not in json.dumps(reply)
    failure = DelegateFailure(reply["exit_code"], reply["error"])
    assert admission.public_rejection(failure) == (expected if expected in admission.REASONS else None)
  assert str(DelegateFailure(5, {"private": "synthetic"})) == "DELEGATE_CONTROL_REJECTED"


def test_login_does_not_need_auth_but_rejects_instance_config_including_broken_links(configured):
  home, _ = configured; (home / "auth.json").unlink()
  admission.admit_codex_login(home)
  config = home / "config.toml"
  config.symlink_to(home / "missing")
  with pytest.raises(admission.CodexAdmissionError, match="CODEX_LOGIN_CONFIG_UNVERIFIED"):
    admission.admit_codex_login(home)
  config.unlink(); config.write_text('credential = "synthetic-private"')
  with pytest.raises(admission.CodexAdmissionError, match="CODEX_LOGIN_CONFIG_UNVERIFIED"):
    admission.admit_codex_login(home)


def test_control_channel_preserves_only_the_zero_write_backpressure_signal():
  from agentcfg.pi_supervisor import SupervisorService
  from agentcfg.storage import Conflict
  service = object.__new__(SupervisorService); service.authenticate = lambda *args: None
  def backpressure(*args): raise Conflict("ORDINARY_STDIN_BACKPRESSURE")
  service.handle = backpressure
  assert service.reply("fixture", os.geteuid(), {})["error"] == "ORDINARY_STDIN_BACKPRESSURE"
