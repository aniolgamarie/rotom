"""官方 CLI 的受限配置准入；不把预检宣称为同进程原子配置证明。"""

import base64
import json
import os
from pathlib import Path
import stat
import sys

from .process import DependencyError
from .secrets import CredentialError
from .storage import Tree


SYSTEM_DIRECTORY = Path("/etc/codex")
SYSTEM_FILES = ("config.toml", "requirements.toml", "managed_config.toml")
PERSONAL_PLANS = frozenset(("free", "go", "plus", "pro", "prolite"))
POLICY_ID = "official-cli-restricted-v1"
REASONS = frozenset(("CODEX_SYSTEM_CONFIG_PRESENT", "CODEX_SYSTEM_CONFIG_UNVERIFIED",
  "CODEX_MANAGED_PREFERENCES_PRESENT", "CODEX_MANAGED_PREFERENCES_UNVERIFIED",
  "CODEX_ACCOUNT_CONFIG_UNVERIFIED", "CODEX_ORGANIZATION_ACCOUNT_UNSUPPORTED", "CODEX_CONFIG_PLATFORM_UNSUPPORTED",
  "CODEX_LOGIN_CONFIG_UNVERIFIED", "CODEX_CUSTOM_ENDPOINT_REQUIRES_API_KEY"))


def admit_codex_endpoint(admission, endpoint):
  if endpoint is None: return
  from .pi_delegate_policy import codex_api_base_url
  codex_api_base_url(endpoint)
  if admission.get("account_class") != "api-key": raise CodexAdmissionError("CODEX_CUSTOM_ENDPOINT_REQUIRES_API_KEY")


class CodexAdmissionError(DependencyError):
  def __init__(self, reason):
    if reason not in REASONS: reason = "CODEX_ACCOUNT_CONFIG_UNVERIFIED"
    self.error_code = reason
    super().__init__(reason)


def public_rejection(error):
  code = getattr(error, "error_code", None)
  return code if isinstance(code, str) and code in REASONS else None


def _system_configuration_absent():
  # /etc 在 macOS 上是系统符号链接；只解析父目录，不跟随 codex 目录本身。
  try:
    parent = SYSTEM_DIRECTORY.parent.resolve(strict=True)
    for directory in (parent, *parent.parents):
      info = directory.stat()
      if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
        raise ValueError()
    try:
      info = (parent / SYSTEM_DIRECTORY.name).lstat()
    except FileNotFoundError:
      return
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
      raise ValueError()
    descriptor = os.open(parent / SYSTEM_DIRECTORY.name, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
      opened = os.fstat(descriptor)
      if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino): raise ValueError()
      # 规则／技能等也可能作为系统来源被发现；非空目录一律不在受限支持范围。
      for name in set(SYSTEM_FILES) | set(os.listdir(descriptor)):
        try:
          os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
          continue
        # 包括空文件、坏链接和不可读文件；不解析、打印或改动管理员配置。
        raise CodexAdmissionError("CODEX_SYSTEM_CONFIG_PRESENT")
      latest = (parent / SYSTEM_DIRECTORY.name).lstat()
      if (latest.st_dev, latest.st_ino, latest.st_mtime_ns) != (opened.st_dev, opened.st_ino, opened.st_mtime_ns): raise ValueError()
    finally:
      os.close(descriptor)
  except CodexAdmissionError:
    raise
  except Exception:
    raise CodexAdmissionError("CODEX_SYSTEM_CONFIG_UNVERIFIED") from None


def _managed_preferences_present(framework=None):
  """与锁定 CLI 相同的 CFPreferencesCopyAppValue 域/键，只查看值是否存在。"""
  import ctypes
  if framework is None:
    framework = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
  create = framework.CFStringCreateWithCString
  create.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32)
  create.restype = ctypes.c_void_p
  copy = framework.CFPreferencesCopyAppValue
  copy.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
  copy.restype = ctypes.c_void_p
  release = framework.CFRelease
  release.argtypes = (ctypes.c_void_p,)
  release.restype = None
  domain = create(None, b"com.openai.codex", 0x08000100)
  if not domain: raise ValueError()
  try:
    for name in (b"config_toml_base64", b"requirements_toml_base64"):
      key = create(None, name, 0x08000100)
      if not key: raise ValueError()
      try:
        value = copy(key, domain)
        if value:
          release(value)
          return True
      finally:
        release(key)
    return False
  finally:
    release(domain)


def admit_system_configuration():
  if sys.platform not in ("linux", "darwin"):
    raise CodexAdmissionError("CODEX_CONFIG_PLATFORM_UNSUPPORTED")
  _system_configuration_absent()
  if sys.platform == "darwin":
    try:
      present = _managed_preferences_present()
      if type(present) is not bool: raise ValueError()
    except Exception:
      raise CodexAdmissionError("CODEX_MANAGED_PREFERENCES_UNVERIFIED") from None
    if present: raise CodexAdmissionError("CODEX_MANAGED_PREFERENCES_PRESENT")


def _unique_object(pairs):
  value = {}
  for key, item in pairs:
    if key in value: raise ValueError()
    value[key] = item
  return value


def _account_class(raw):
  # 只分类当前原生账号，不认证 JWT、不保留正文或账号标识；认证仍由 CLI 完成。
  value = json.loads(raw, object_pairs_hook=_unique_object)
  if (not isinstance(value, dict) or set(value) - {"auth_mode", "OPENAI_API_KEY", "tokens", "last_refresh",
      "agent_identity", "personal_access_token", "bedrock_api_key", "bedrock_access_keys"}
      or any(value.get(key) is not None for key in ("agent_identity", "personal_access_token", "bedrock_api_key", "bedrock_access_keys"))):
    raise ValueError()
  api_key = value.get("OPENAI_API_KEY")
  if value.get("auth_mode") in (None, "apikey") and value.get("tokens") is None and isinstance(api_key, str) and api_key and not any(char in api_key for char in "\r\n\0"):
    return "api-key"
  if value.get("auth_mode") not in (None, "chatgpt") or api_key is not None: raise ValueError()
  tokens = value.get("tokens")
  if (not isinstance(tokens, dict) or set(tokens) - {"id_token", "access_token", "refresh_token", "account_id"}
      or any(not isinstance(tokens.get(key), str) or not tokens[key] or len(tokens[key]) > 131072
        for key in ("id_token", "access_token", "refresh_token"))): raise ValueError()
  parts = tokens["id_token"].split(".")
  if len(parts) != 3 or not all(parts): raise ValueError()
  payload = base64.b64decode(parts[1] + "=" * (-len(parts[1]) % 4), altchars=b"-_", validate=True)
  claims = json.loads(payload, object_pairs_hook=_unique_object)["https://api.openai.com/auth"]
  if not isinstance(claims, dict) or not isinstance(claims.get("chatgpt_plan_type"), str): raise ValueError()
  plan = claims["chatgpt_plan_type"]
  if plan not in PERSONAL_PLANS:
    known = {"team", "self_serve_business_prolite", "self_serve_business_usage_based", "business", "ent26",
      "enterprise_cbp_automation", "enterprise_cbp_usage_based", "enterprise", "hc", "education", "edu", "edu_plus", "edu_pro"}
    raise CodexAdmissionError("CODEX_ORGANIZATION_ACCOUNT_UNSUPPORTED" if plan in known else "CODEX_ACCOUNT_CONFIG_UNVERIFIED")
  return "personal"


def admit_codex_execution(home):
  admit_system_configuration()
  try:
    with Tree(Path(home)) as tree:
      raw = tree.read("auth.json", max_bytes=1024 * 1024)
    if raw is None: raise CredentialError()
    if raw[1] != 0o600: raise ValueError()
    account = _account_class(raw[0])
  except (CredentialError, CodexAdmissionError):
    raise
  except Exception:
    raise CodexAdmissionError("CODEX_ACCOUNT_CONFIG_UNVERIFIED") from None
  return {"schema_version": 1, "policy": POLICY_ID, "system_configuration": "absent",
    "managed_preferences": "absent" if sys.platform == "darwin" else "not-applicable", "account_class": account,
    "atomic_config_binding": False}


def admit_codex_login(home):
  admit_system_configuration()
  # login 没有 exec 的 ignore-user-config 选项，只允许干净的实例配置槽。
  try:
    with Tree(Path(home)) as tree:
      with tree.parent("config.toml") as (fd, name):
        try: os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError: return
    raise ValueError()
  except Exception:
    raise CodexAdmissionError("CODEX_LOGIN_CONFIG_UNVERIFIED") from None
