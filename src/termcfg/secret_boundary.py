"""旧目标非秘密准入：仅接受可辨识的公开配置类别。"""

import hashlib
import re
from pathlib import Path

from .errors import TermcfgError


_SENSITIVE = re.compile(rb"(?i)(token|secret|password|api[_-]?key|subscription|sub[_-]?url|bearer|authorization|webhook|private[_-]?key|proxy-authorization)")
_SIMPLE_ZSH = re.compile(rb"^\s*(?:#.*|(?:export\s+)?(?:LANG|LC_[A-Z_]+)=[A-Za-z0-9_.@-]{1,64}|(?:export\s+)?(?:EDITOR|VISUAL|PAGER)=[A-Za-z0-9_./-]{1,64}|\s*)$")


def admit_existing(target_id: str, data: bytes, *, known_public_contents: set[bytes], trusted_digest: str | None = None) -> str:
  if data in known_public_contents:
    return hashlib.sha256(data).hexdigest()
  if len(data) > 1024 * 1024 or b"\0" in data or _SENSITIVE.search(data):
    raise TermcfgError(4, "possible_private_content", "先把私人值迁到 0600 私人文件，再运行 ./termcfg plan")
  if trusted_digest is not None:
    candidate = hashlib.sha256(data).hexdigest()
    if candidate == trusted_digest:
      return candidate
  if target_id == "zshenv" and all(_SIMPLE_ZSH.fullmatch(line) for line in data.splitlines()):
    return hashlib.sha256(data).hexdigest()
  raise TermcfgError(4, "unclassified_existing_content", "先审阅并迁走私人值，再运行 ./termcfg plan")
