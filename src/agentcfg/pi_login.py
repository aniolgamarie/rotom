"""用户显式 Codex 登录入口；账号仅落在所选实例，不产生模型验收结论。"""

import json
from pathlib import Path

from .model_delegate_backends import backend_environment
from .paths import relative_path
from .pi_supervisor import SpawnCommand, closed
from .process import DependencyError
from .schema import ConfigError
from .storage import Tree, ensure_private


def account_available(host, lease, *, login):
  from .activity import protected
  from .storage import Conflict
  for row in host.store.records():
    if row["lease_id"] == lease["lease_id"] or row["kind"] != "codex" or not row["spawn_committed"] or not protected(row): continue
    with Tree(host.root) as tree: raw = tree.read("activity/commands/" + row["lease_id"] + ".json")
    program = json.loads(raw[0]).get("program") if raw else None
    if login or program != "delegate-codex":
      raise Conflict("CODEX_ACCOUNT_BUSY")


def resolve_login(host, lease, payload):
  closed(payload, ())
  manifest = host.manifest()
  options = manifest["options"].get("model_delegate", {})
  if not options.get("enabled") or "codex" not in options.get("backends", []) or lease["kind"] != "codex" or lease["task_id"] is not None:
    raise ConfigError("delegate-login-not-selected")
  account_available(host, lease, login=True)
  with Tree(host.runtime_root) as tree:
    commands = json.loads(tree.read("runtime/commands.json")[0])
    definition = commands["programs"].get("codex-login")
    if not definition or tree.read(relative_path(definition["entrypoint"]).as_posix()) is None:
      raise DependencyError("所选Codex登录入口未安装")
  route = manifest["options"].get("network", {}).get("routes", {}).get(options.get("codex", {}).get("network_route"))
  if not route or route.get("credential_ref"):
    raise ConfigError("delegate-login-route-required")
  home = host.root / "activity/login-homes" / lease["lease_id"]
  ensure_private(home); ensure_private(home / "tmp")
  instance = Path(host.config["instance_root"])
  ensure_private(instance / "codex-home")
  from .pi_codex_admission import admit_codex_login
  admit_codex_login(instance / "codex-home")
  import os
  import stat
  from .storage import Conflict
  try:
    info = (instance / "codex-home/auth.json").lstat()
  except FileNotFoundError:
    info = None
  if info is not None and (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o077):
    raise Conflict("CODEX_AUTH_OWNERSHIP")
  executable = host.runtime_root / relative_path(definition["entrypoint"])
  env = backend_environment(home=home, instance=instance, route=route, executable=executable)
  # 原生设备登录的终端交互直接给用户，不捕获账号码到普通任务日志。
  return SpawnCommand((str(executable), "-c", 'cli_auth_credentials_store="file"', "login", "--device-auth"), home, env)
