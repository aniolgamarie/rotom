"""私人普通值的窄类型校验；不实现通用插值或环境读取。"""

import unicodedata
from urllib.parse import parse_qsl, urlsplit

from .schema import ConfigError


_CREDENTIAL_NAMES = frozenset({
  "API_KEY", "APIKEY", "ACCESS_TOKEN", "REFRESH_TOKEN", "TOKEN", "PASSWORD",
  "PASSWD", "SECRET", "CLIENT_SECRET", "AUTHORIZATION", "CREDENTIAL", "CREDENTIAL_REF",
})


def _credential_name(name: str) -> bool:
  normalized = name.upper().replace("-", "_")
  return normalized in _CREDENTIAL_NAMES or any(
    normalized.endswith("_" + suffix) for suffix in _CREDENTIAL_NAMES)


def validate_local_url(value) -> str:
  """返回严格 HTTP(S) 绝对 URL；任何错误只暴露固定位置。"""
  valid = (type(value) is str and bool(value) and "\\" not in value
           and not any(character.isspace() or unicodedata.category(character) == "Cc"
                       for character in value))
  try:
    parsed = urlsplit(value) if valid else None
    valid = bool(valid and parsed.scheme in ("http", "https") and parsed.netloc
                 and parsed.hostname and parsed.username is None and parsed.password is None
                 and not parsed.fragment
                 and not any(_credential_name(key) for key, _ in parse_qsl(
                   parsed.query, keep_blank_values=True)))
    port = parsed.port if valid else None
    if port is not None and not 1 <= port <= 65535:
      valid = False
  except (TypeError, ValueError):
    valid = False
  if not valid:
    raise ConfigError("url", ("providers", "<key>", "base_url"))
  return value
