"""用显式 argv 构造建议；展示上下文不参与执行或权限判断。"""

from dataclasses import dataclass
import shlex


_MULTI = frozenset(("init-local", "plan", "doctor", "status", "apply"))
_SINGLE = frozenset(("lock", "sync", "rollback"))
_DIAGNOSTIC = frozenset(("plan", "doctor", "status"))
_COMMANDS = _MULTI | _SINGLE | {"components", "recover", "migrate"}


def _components(values):
  if isinstance(values, str):
    values = (values,)
  if values is None:
    return ()
  if not isinstance(values, (tuple, list)) or any(value not in ("zsh", "tmux") for value in values):
    return None
  if len(set(values)) != len(values):
    return None
  return tuple(values)


@dataclass(frozen=True)
class Context:
  machine: str | None = "default"
  components: tuple[str, ...] | None = ()
  home: str | None = None
  home_requested: bool = False

  def public(self):
    return {"machine": self.machine, "components": self.components or (),
            "diagnostic_home": self.home_requested}


def context_for(args):
  # 延迟导入避免 errors/config 的循环；仅使用注册的词法约束，不读机器文件。
  from .config import MACHINE_ID
  machine = getattr(args, "machine", None)
  if not isinstance(machine, str) or not MACHINE_ID.fullmatch(machine):
    machine = None
  values = getattr(args, "_guidance_components", getattr(args, "component", None))
  return Context(machine, _components(values), getattr(args, "_guidance_home", None),
                 bool(getattr(args, "home", None)))


def _render(command, arguments, components, fallback_components, context):
  if command is None:
    return "./termcfg --help"
  if "--help" in arguments:
    return shlex.join(("./termcfg", command, "--help"))
  if context.machine is None:
    return "./termcfg --help"
  if context.components is None:
    return shlex.join(("./termcfg", command, "--help"))
  selected = components if components is not None else context.components or fallback_components
  home = context.home
  if context.home_requested and home is None:
    return shlex.join(("./termcfg", "plan" if command not in _DIAGNOSTIC else command, "--help"))
  if context.home_requested and command not in _DIAGNOSTIC:
    # 不把诊断目标、计划 ID 或确认参数带回保存的 HOME；先重新检查保存目标。
    command = "status" if command in {"recover", "rollback", "migrate"} else "plan"
    arguments, home = (), None
  if command in _SINGLE and len(selected) != 1:
    # 单组件命令没有多选语法；保留全部范围，先做明确的只读诊断。
    command, arguments = "doctor", ()
  words = ["./termcfg"]
  if context.machine != "default":
    words.extend(("--machine", context.machine))
  words.append(command)
  words.extend(arguments)
  if command in _MULTI | _SINGLE:
    for component in selected:
      words.extend(("--component", component))
  if home is not None and command in _DIAGNOSTIC:
    words.extend(("--home", home))
  return shlex.join(words)


class Hint(str):
  """保留原有字符串/JSON接口，同时保留构造令牌；绝不反向解析任意字符串。"""

  def __new__(cls, command, *arguments, components=None, fallback_components=()):
    if command is not None and command not in _COMMANDS:
      raise ValueError("未登记的建议命令")
    if any(not isinstance(word, str) for word in arguments):
      raise TypeError("建议参数必须为字符串令牌")
    if components is not None and _components(components) is None:
      raise ValueError("未登记的建议组件")
    if _components(fallback_components) is None:
      raise ValueError("未登记的后备组件")
    components = _components(components) if components is not None else None
    fallback_components = _components(fallback_components)
    value = _render(command, arguments, components, fallback_components, Context())
    obj = super().__new__(cls, value)
    obj.command, obj.arguments = command, tuple(arguments)
    obj.components, obj.fallback_components = components, fallback_components
    return obj

  def render(self, context):
    return _render(self.command, self.arguments, self.components, self.fallback_components, context)

  def __getnewargs_ex__(self):
    return (self.command, *self.arguments), {"components": self.components,
                                          "fallback_components": self.fallback_components}


hint = Hint


def resolve_hints(payload, context):
  """只处理当前契约中的提示槽；不扫描未知嵌套数据、不改原结果。"""
  result = dict(payload)
  if isinstance(result.get("next_command"), Hint):
    result["next_command"] = result["next_command"].render(context)
  for field in ("components", "environment"):
    values = result.get(field)
    if not isinstance(values, dict):
      continue
    result[field] = dict(values)
    for component in ("zsh", "tmux"):
      item = values.get(component)
      if isinstance(item, dict) and isinstance(item.get("next_command"), Hint):
        result[field][component] = {**item, "next_command": item["next_command"].render(context)}
  return result
