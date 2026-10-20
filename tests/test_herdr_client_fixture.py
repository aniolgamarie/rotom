"""真实客户端样本解码；默认不启动终端或读取剪贴板。"""

import importlib.util
from pathlib import Path

import pytest


def fixture():
  path = Path(__file__).parent / "fixtures/herdr-client/v1/recorder.py"
  spec = importlib.util.spec_from_file_location("client_fixture", path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_paste_preserves_unicode_and_normalises_terminal_newlines():
  value = "第一行：Herdr\r\n第二行：Ghostty\r".encode()
  assert fixture().paste_text(b"\x1b[200~" + value + b"\x1b[201~") == "第一行：Herdr\n第二行：Ghostty"


def test_incomplete_bracketed_paste_is_not_accepted():
  assert fixture().paste_text(b"\x1b[200~unfinished") is None


@pytest.mark.parametrize("value,expected", [(b"\x1b[13;2u", "csi-u"),
  (b"\x1b[13;2:1u", "csi-u"), (b"\x1b[27;2;13~", "modify-other-keys"),
  (b"\r", "cr"), (b"\n", "lf"), (b"synthetic-secret", "unknown")])
def test_shift_enter_records_only_known_encoding_categories(value, expected):
  assert fixture().shift_encoding(value) == expected


def test_clipboard_sequence_is_write_only_fixed_sample():
  sequence = fixture().clipboard_sequence()
  assert sequence.startswith(b"\x1b]52;c;") and sequence.endswith(b"\x07")
  assert b"?" not in sequence


@pytest.mark.parametrize("value,expected", [(b"\x18", "legacy"),
  (b"\x1b[120;5u", "csi-u"), (b"\x1b[120;5:1u", "csi-u"),
  (b"\x1b[120;5:3u", "unknown"), (b"\x1b[120;6u", "unknown"),
  (b"x", "unknown"), (b"synthetic-secret", "unknown")])
def test_literal_prefix_accepts_legacy_and_negotiated_key_press(value, expected):
  assert fixture().prefix_encoding(value) == expected
