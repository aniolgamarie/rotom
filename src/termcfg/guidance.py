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
  if not isinstance(values, (tuple, list)) or any(value not in ("zsh", "tmux", "herdr") for value in values):
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
  invocation: object = None

  def public(self):
    return {"machine": self.machine, "components": self.components or (),
            "diagnostic_home": self.home_requested}


def context_for(args):
  # 延迟导入避免 errors/config 的循环；仅使用注册的词法约束，不读机器文件。
  from .config import MACHINE_ID
  from rotom.context import invocation_context
  machine = getattr(args, "machine", None)
  if not isinstance(machine, str) or not MACHINE_ID.fullmatch(machine):
    machine = None
  values = getattr(args, "_guidance_components", getattr(args, "component", None))
  return Context(machine, _components(values), getattr(args, "_guidance_home", None),
                 bool(getattr(args, "home", None)), invocation_context(args))


def _render(command, arguments, components, fallback_components, context):
  prefix = (context.invocation.display_prefix, "term") if context.invocation is not None else ("./termcfg",)
  def help_for(name=None):
    if name is None:
      return shlex.join((*prefix, "--help"))
    if context.invocation is not None:
      from dataclasses import replace
      from rotom.context import TypedInvocation
      scope = replace(context.invocation.scope, machine=context.machine, local=None,
        component=context.components if name in _MULTI | _SINGLE and context.components else ())
      invocation = TypedInvocation(replace(context.invocation, scope=scope), ())
      return shlex.join((*invocation.advice_tokens(("term", name)), "--help"))
    return shlex.join((*prefix, name, "--help"))
  if command is None:
    return help_for()
  if "--help" in arguments:
    return help_for(command)
  if context.machine is None:
    return help_for()
  if context.components is None:
    return help_for(command)
  selected = components if components is not None else context.components or fallback_components
  home = context.home
  if context.home_requested and home is None:
    return help_for("plan" if command not in _DIAGNOSTIC else command)
  if context.home_requested and command not in _DIAGNOSTIC:
    # 不把诊断目标、计划 ID 或确认参数带回保存的 HOME；先重新检查保存目标。
    command = "status" if command in {"recover", "rollback", "migrate"} else "plan"
    arguments, home = (), None
  if command in _SINGLE and len(selected) != 1:
    # 单组件命令没有多选语法；保留全部范围，先做明确的只读诊断。
    command, arguments = "doctor", ()
  if context.invocation is not None:
    from dataclasses import replace
    from rotom.context import TypedInvocation
    scope = replace(context.invocation.scope, machine=context.machine, local=None,
      component=selected if command in _MULTI | _SINGLE else ())
    invocation = TypedInvocation(replace(context.invocation, scope=scope), ())
    words = list(invocation.advice_tokens(("term", command)))
    words.extend(arguments)
  else:
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
    for component in ("zsh", "tmux", "herdr"):
      item = values.get(component)
      if isinstance(item, dict) and isinstance(item.get("next_command"), Hint):
        result[field][component] = {**item, "next_command": item["next_command"].render(context)}
  return result
