#!/usr/bin/env python3
"""已进入平台沙箱后启动回环中继和固定媒体 CLI；不接收监督控制凭据。"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_web_relay import LoopbackRelay


def execute(value, *, relay_factory=LoopbackRelay, popen=subprocess.Popen, now=time.monotonic):
  if ((set(value) - {"github_authorization"}) != {"argv", "socket_path", "port", "token", "timeout_seconds"}
      or not isinstance(value["argv"], list) or not value["argv"] or not Path(value["argv"][0]).is_absolute()
      or any(not isinstance(arg, str) or "\0" in arg for arg in value["argv"])
      or not isinstance(value["token"], str) or not re.fullmatch(r"[a-f0-9]{64}", value["token"])
      or type(value["timeout_seconds"]) is not int or not 1 <= value["timeout_seconds"] <= 3600):
    raise ValueError("WEB_CLI_INPUT_INVALID")
  proxy = "http://agentcfg:" + value["token"] + "@127.0.0.1:" + str(value["port"])
  argv = [proxy if arg == "AGENTCFG_WEB_PROXY" else arg for arg in value["argv"]]
  # 环境从零构造，代理变量仅供该 CLI。上游代理凭据留在父进程。
  env = {"HOME": os.environ["HOME"], "TMPDIR": os.environ["TMPDIR"], "LANG": "C.UTF-8",
    "PATH": str(Path(argv[0]).parent) + ":/usr/bin:/bin", "http_proxy": proxy, "https_proxy": proxy,
    "HTTP_PROXY": proxy, "HTTPS_PROXY": proxy, "NO_PROXY": "", "no_proxy": "",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}
  authorization = value.get("github_authorization")
  if authorization is not None:
    if not isinstance(authorization, str) or len(authorization) > 16384 or any(ord(char) < 32 or ord(char) == 127 for char in authorization): raise ValueError("WEB_CLI_INPUT_INVALID")
    env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraHeader", GIT_CONFIG_VALUE_0="Authorization: " + authorization)
  relay = relay_factory(value["socket_path"], value["port"])
  child = None
  try:
    relay.start()
    child = popen(argv, env=env, stdin=subprocess.DEVNULL, close_fds=True)
    deadline = now() + value["timeout_seconds"]
    while child.poll() is None:
      if now() >= deadline: raise TimeoutError("WEB_CLI_TIMEOUT")
      relay.poll(0.1)
    return child.returncode
  finally:
    try: relay.close()
    finally:
      if child is not None and child.poll() is None:
        child.terminate()
        try: child.wait(timeout=2)
        except subprocess.TimeoutExpired:
          child.kill(); child.wait(timeout=2)


def main():
  if len(sys.argv) != 3 or sys.argv[1] != "--input": return 2
  descriptor = os.open(sys.argv[2], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
  with os.fdopen(descriptor, "rb") as stream:
    raw = stream.read(65537)
  if len(raw) > 65536: return 2
  return execute(json.loads(raw))


if __name__ == "__main__":
  try: sys.exit(main())
  except Exception:
    sys.stderr.write("Web CLI 未完成；请检查所选依赖、路线和监督状态。\n")
    sys.exit(5)
