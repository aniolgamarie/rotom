"""仅内存的调用目标与输入策略；不携带秘密值。"""
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping
import sys


class InputPolicy(str, Enum):
  LEGACY = "legacy"
  AUTO = "auto"
  INTERACTIVE = "interactive"
  NO_INPUT = "no_input"


@dataclass(frozen=True)
class Scope:
  machine: str | None = None
  local: str | None = None
  agent: str | None = None
  profile: str | None = None
  component: tuple[str, ...] = ()
  sources: Mapping[str, str] = field(default_factory=dict)

  def __post_init__(self):
    if self.machine is not None and self.local is not None:
      raise ValueError("scope selectors are mutually exclusive")
    object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))


class InputError(Exception):
  def __init__(self, exit_code=2):
    self.exit_code = exit_code
    super().__init__("input unavailable" if exit_code == 2 else "input cancelled")


def invocation_context(value):
  return value if isinstance(value, InvocationContext) else getattr(value, "invocation_context", None)


def require_input(value):
  context = invocation_context(value)
  if context is not None:
    context.input_gateway.require_input(context.input_policy)
  return context


@dataclass(frozen=True)
class InputGateway:
  """后续输入接缝；不打开 tty、不替换全局 input。"""
  stdin: object = field(default_factory=lambda: sys.stdin, repr=False)
  stdout: object = field(default_factory=lambda: sys.stdout, repr=False)
  stderr: object = field(default_factory=lambda: sys.stderr, repr=False)

  def allows_input(self, policy: InputPolicy) -> bool:
    if policy == InputPolicy.NO_INPUT:
      return False
    if policy == InputPolicy.LEGACY:
      return bool(self.stdin.isatty())
    return all(stream.isatty() for stream in (self.stdin, self.stdout, self.stderr))


  def require_input(self, policy):
    if not self.allows_input(policy):
      raise InputError(2)

  def text(self, label, *, policy=InputPolicy.AUTO, optional=False, default=None):
    self.require_input(policy)
    print(label + ": ", file=self.stderr, end="", flush=True)
    try:
      value = self.stdin.readline()
    except (EOFError, KeyboardInterrupt):
      raise InputError(130) from None
    except OSError:
      raise InputError(2) from None
    if value == "":
      raise InputError(130)
    value = value.rstrip("\r\n")
    if value == "\x1b":
      raise InputError(130)
    if not value:
      if default is not None:
        return default
      if not optional:
        raise InputError(130)
    if "\0" in value:
      raise InputError(2)
    return value

  def choose(self, rows, *, policy=InputPolicy.AUTO, label="选择", enhance=None):
    self.require_input(policy)
    rows = list(rows)
    if not rows or len({key for key, _ in rows}) != len(rows):
      raise InputError(2)
    if enhance is not None:
      try:
        selected = enhance()
      except Exception as error:
        if getattr(error, "code", None) != 5:
          raise
      else:
        if selected is None:
          raise InputError(130)
        if selected not in {key for key, _ in rows}:
          raise InputError(2)
        return selected
    for index, (_, description) in enumerate(rows, 1):
      safe = "".join(char if char.isprintable() else " " for char in str(description))
      print(f"{index}. {safe}", file=self.stderr)
    while True:
      answer = self.text(label + "（编号；空输入取消）", policy=policy)
      if answer.isascii() and answer.isdigit() and 1 <= int(answer) <= len(rows):
        return rows[int(answer) - 1][0]
      print("请输入列出的编号", file=self.stderr)

  def confirm(self, label, *, policy=InputPolicy.AUTO):
    if self.text(label + "（输入 yes 批准；其它输入取消）", policy=policy).strip().lower() != "yes":
      raise InputError(130)
    return True

  def hidden(self, label, *, policy=InputPolicy.AUTO):
    self.require_input(policy)
    try:
      import termios
    except ImportError:
      raise InputError(2) from None
    try:
      descriptor = self.stdin.fileno()
      original = termios.tcgetattr(descriptor)
    except (OSError, ValueError, termios.error):
      raise InputError(2) from None
    flags = list(original)
    flags[3] &= ~termios.ECHO
    try:
      try:
        termios.tcsetattr(descriptor, termios.TCSAFLUSH, flags)
      except (OSError, ValueError, termios.error):
        raise InputError(2) from None
      return self.text(label, policy=policy)
    finally:
      try:
        termios.tcsetattr(descriptor, termios.TCSAFLUSH, original)
      except (OSError, ValueError, termios.error):
        raise InputError(2) from None
      finally:
        print(file=self.stderr)


@dataclass(frozen=True)
class InvocationContext:
  command_path: tuple[str, ...]
  display_prefix: str = "rotom"
  explicit_fields: frozenset[str] = frozenset()
  input_policy: InputPolicy = InputPolicy.AUTO
  output_mode: str = "auto"
  scope: Scope = field(default_factory=Scope)
  input_gateway: InputGateway = field(default_factory=InputGateway)

  def __post_init__(self):
    from .cli import COMMANDS
    if self.command_path not in COMMANDS:
      raise ValueError("unregistered command path")
    object.__setattr__(self, "explicit_fields", frozenset(self.explicit_fields))
    object.__setattr__(self, "input_policy", InputPolicy(self.input_policy))


@dataclass(frozen=True)
class TypedInvocation:
  """校验后的 token；native_tail 独立不透明，不解析显示文本。"""
  context: InvocationContext
  tokens: tuple[str, ...]
  native_tail: tuple[str, ...] = field(default=(), repr=False)

  def __post_init__(self):
    for name in ("tokens", "native_tail"):
      value = tuple(getattr(self, name))
      if not all(isinstance(token, str) for token in value):
        raise ValueError("invocation tokens must be strings")
      object.__setattr__(self, name, value)

  def advice_tokens(self, command_path):
    """从已核实的范围生成展示 token；不解析显示文本或原生尾部。"""
    from .cli import COMMANDS
    path = tuple(command_path)
    if path not in COMMANDS:
      raise ValueError("unregistered advice path")
    scope = self.context.scope
    tokens = [self.context.display_prefix, path[0]]
    if scope.local is not None:
      tokens.extend(("--local", scope.local))
    elif scope.machine is not None:
      tokens.extend(("--machine", scope.machine))
    if path[0] == "agent" and scope.profile is not None:
      tokens.extend(("--profile", scope.profile))
    tokens.extend(path[1:])
    if path[0] == "term":
      for component in scope.component:
        tokens.extend(("--component", component))
    return tuple(tokens)
