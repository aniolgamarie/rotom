#!/usr/bin/env python3
"""显式客户端验收；只保存固定样本的结果，不记录任意输入或读取剪贴板。"""
import base64
import json
import os
from pathlib import Path
import re
import select
import stat
import termios
import time
import tty
import uuid

IME = "中文输入验收"
PASTE = "第一行：Herdr\n第二行：Ghostty"
COPY = "Herdr 中文复制验收\n第二行"


def paste_text(raw):
  if raw.startswith(b"\x1b[200~"):
    if not raw.endswith(b"\x1b[201~"):
      return None
    raw = raw[6:-6]
  try:
    return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
  except UnicodeError:
    return None


def shift_encoding(raw):
  if re.fullmatch(rb"\x1b\[13;2(?::1)?u", raw):
    return "csi-u"
  return {b"\x1b[27;2;13~": "modify-other-keys", b"\r": "cr", b"\n": "lf"}.get(raw, "unknown")


def prefix_encoding(raw):
  if raw == b"\x18":
    return "legacy"
  if re.fullmatch(rb"\x1b\[120;5(?::1)?u", raw):
    return "csi-u"
  return "unknown"


def clipboard_sequence():
  return b"\x1b]52;c;" + base64.b64encode(COPY.encode()) + b"\x07"


def private_json(path):
  info = path.lstat()
  if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
      or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
    raise ValueError("private_fixture_required")
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  try:
    return json.loads(os.read(fd, 8192))
  finally:
    os.close(fd)


def main():
  if not os.isatty(0):
    return 5
  root = Path.cwd()
  config = private_json(root / ".herdr-client-accept.json")
  if set(config) != {"run_id"} or not re.fullmatch(r"[a-f0-9]{32}", config["run_id"]):
    return 2
  output = root / ".herdr-client-evidence"
  info = output.lstat()
  if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
      or stat.S_IMODE(info.st_mode) != 0o700 or output.resolve() != output):
    return 4
  state = {"schema_version": 1, "run_id": config["run_id"], "pid": os.getpid(),
    "phase": "waiting", "sequence": 0, "checks": {}, "human_checks": {},
    "shift_enter_encoding": None, "ordinary_enter_encoding": None, "prefix_encoding": None}
  saved = termios.tcgetattr(0)
  def say(message):
    os.write(1, (message.replace("\n", "\r\n") + "\r\n").encode())
  def save(phase=None):
    if phase:
      state["phase"] = phase
    state["sequence"] += 1
    state["heartbeat_ns"] = time.monotonic_ns()
    state["size"] = list(os.get_terminal_size(0))
    temporary = output / (".state-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
      json.dump(state, stream, ensure_ascii=False)
    temporary.replace(output / "state.json")
  def read():
    while True:
      ready, _, _ = select.select([0], [], [], 1)
      save()
      if ready:
        data = os.read(0, 4096)
        if not data:
          raise OSError("fixture_stdin_closed")
        return data
  def key(allowed=None):
    while True:
      data = read()
      if data.startswith(b"\x1b"):
        while select.select([0], [], [], .1)[0] and len(data) < 128:
          data += os.read(0, 128)
      if allowed is None or data in allowed:
        return data
  def sample(expected):
    raw = b""
    while True:
      raw += read()
      text = paste_text(raw)
      if text == expected and (raw.endswith((b"\r", b"\n", b"\x1b[201~")) or "\n" in expected):
        return raw
      if len(raw) > 4096 or (text is not None and not expected.startswith(text) and raw.endswith((b"\r", b"\n", b"\x1b[201~"))):
        raw = b""
        say("与固定样本不符，请重新输入；未保存输入正文。")
  try:
    os.umask(0o077)
    tty.setraw(0)
    os.write(1, b"\x1b[?2004h\x1b[>1u")
    save()
    say("Herdr / macOS Ghostty 独立验收。只输入下面的固定样本。连接后按 Enter 开始。")
    key({b"\r", b"\n"})
    save("ime")
    say("1/8 请用中文输入法输入：中文输入验收，然后按 Enter。")
    raw = sample(IME)
    state["ordinary_enter_encoding"] = "cr" if raw.endswith(b"\r") else "lf"
    state["checks"]["ime"] = True
    save("paste")
    say("2/8 请一次粘贴两行（末尾可有换行）：\n" + PASTE)
    sample(PASTE)
    state["checks"]["paste"] = True
    save("prefix")
    say("3/8 请连续按两次 Ctrl+x，把一个字面 Ctrl+x 送给程序。")
    while True:
      encoding = prefix_encoding(key())
      if encoding != "unknown":
        break
    state["prefix_encoding"] = encoding
    state["checks"]["prefix"] = True
    save("shift_enter")
    say("4/8 请按一次 Shift+Enter。")
    encoding = shift_encoding(key())
    state["shift_enter_encoding"] = encoding
    state["checks"]["shift_enter"] = encoding not in {"unknown", state["ordinary_enter_encoding"]}
    save("clipboard")
    say("5/8 按 Enter 后仅写入以下合成剪贴板文本：\n" + COPY)
    key({b"\r", b"\n"})
    os.write(1, clipboard_sequence())
    say("请在 macOS 空白文本框粘贴核对两行。完全相同按 y，否则按 n；不要粘回本终端。")
    state["human_checks"]["clipboard"] = key({b"y", b"n"}) == b"y"
    save("render")
    say("6/8 接下来自动分屏/缩放20轮。可拖动一次 Ghostty 窗口；结束后无残留错位按 y，有问题按 n。")
    while True:
      receipt = output / "render.json"
      if receipt.exists():
        value = private_json(receipt)
        if value.get("run_id") == config["run_id"] and value.get("rounds") == 20:
          break
      select.select([], [], [], .2)
      save()
    say("20轮已结束，请按 y 或 n 确认实际画面。")
    state["human_checks"]["render"] = key({b"y", b"n"}) == b"y"
    save("detach")
    say("7/8 请按 Ctrl+x d detach，回到 SSH shell 后重新执行 attach 命令。回来后按 r。")
    key({b"r"})
    state["human_checks"]["detach"] = True
    save("ssh_reconnect")
    say("8/8 请关闭当前 SSH 标签页，重新 SSH 到本机，执行相同 attach 命令。回来后按 r。")
    key({b"r"})
    state["human_checks"]["ssh_reconnect"] = True
    save("done")
    say("操作完成，结果已私有保存。请按 Ctrl+x d 返回；测试会话将由验收控制端清理。")
    while True:
      time.sleep(1)
      save()
  finally:
    os.write(1, b"\x1b[<u\x1b[?2004l")
    termios.tcsetattr(0, termios.TCSANOW, saved)


if __name__ == "__main__":
  raise SystemExit(main())
