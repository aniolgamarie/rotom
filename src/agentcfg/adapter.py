"""声明式 adapter 契约；不注册工具，不执行 IO、秘密解析或部署。

Config、原生 allowlist 投影、捕获提案和渲染字节必须由调用方/adapter 保证非秘密。
这些类型不能识别伪装成普通字符串的密钥，也不替代后续 schema 和安全读取边界。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re
from typing import Generic, TypeVar

from .paths import relative_path, safe_id


class ContractError(Exception):
  """契约错误仅携带固定说明或公开字段位置，不携带私有输入值。"""


def _text(value: str) -> bool:
  return isinstance(value, str) and bool(value) and "\0" not in value


@dataclass(frozen=True)
class AdapterDeclaration:
  adapter_id: str
  schema_version: int
  adapter_version: str

  def __post_init__(self):
    safe_id(self.adapter_id)
    if type(self.schema_version) is not int or self.schema_version < 1:
      raise ContractError("adapter schema_version 必须为正整数")
    if not _text(self.adapter_version):
      raise ContractError("adapter_version 必须非空")


class Ownership(Enum):
  FILE = "file"
  FIELDS = "fields"
  INITIALIZE = "initialize"
  RUNTIME = "runtime"
  PACKAGE = "package"


@dataclass(frozen=True)
class ManagedTarget:
  """实例相对目标；声明并非既有文件的所有权证明。

  selector 为单个原生字段的 opaque 标识，由 adapter 解释；公共层不解析原生语法。
  INITIALIZE 可描述整文件或单字段，不能当作持续受管默认值。
  serialization 仅命名 adapter 的编码方式，不是通用 codec 注册表。
  """

  path: str = field(repr=False)
  ownership: Ownership
  serialization: str
  selector: str | None = field(default=None, repr=False)
  reference_tokens: tuple[str, ...] = field(default=(), repr=False)

  def __post_init__(self):
    relative_path(self.path)
    if not isinstance(self.ownership, Ownership) or not _text(self.serialization):
      raise ContractError("目标需要明确的所有权与序列化方式")
    if self.selector is not None and not _text(self.selector):
      raise ContractError("字段 selector 必须为非空标识")
    if self.ownership is Ownership.FIELDS and self.selector is None:
      raise ContractError("字段受管目标必须提供 selector")
    if self.ownership not in (Ownership.FIELDS, Ownership.INITIALIZE) and self.selector is not None:
      raise ContractError("此所有权类别不支持字段 selector")
    if not isinstance(self.reference_tokens, tuple):
      raise ContractError("凭据引用声明必须是 tuple")
    if self.reference_tokens:
      if (self.selector is None or not isinstance(self.reference_tokens, tuple)
          or any(not isinstance(token, str) or not re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", token)
                 for token in self.reference_tokens)
          or len(set(self.reference_tokens)) != len(self.reference_tokens)):
        raise ContractError("凭据引用必须声明为字段的唯一环境变量引用")


@dataclass(frozen=True)
class Artifact:
  """非秘密确定性意图；有 selector 时 content 只编码该字段期望值。

  禁止将保留的当前共享文件整体混入 content；最终完整文件由后续安全合成层生成。
  此处不实现缺失状态/删除/三方合并，也不把意图直接写入共享文件。
  """

  target: ManagedTarget
  content: bytes = field(repr=False)
  mode: int = 0o600

  def __post_init__(self):
    if not isinstance(self.target, ManagedTarget):
      raise ContractError("产物必须引用声明式目标")
    if self.target.ownership in (Ownership.RUNTIME, Ownership.PACKAGE):
      raise ContractError("运行时与包管理器拥有的目标不得生成受管内容")
    if not isinstance(self.content, bytes):
      raise ContractError("产物内容必须为非秘密字节")
    if type(self.mode) is not int or self.mode not in (0o600, 0o700):
      raise ContractError("产物权限必须为 0600 或带执行位的 0700")


@dataclass(frozen=True)
class DependencyPlan:
  """adapter 原生依赖需求；不是已解析锁或安装成功证据。"""

  requirements: tuple[str, ...] = field(repr=False)

  def __post_init__(self):
    if not isinstance(self.requirements, tuple) or not all(_text(item) for item in self.requirements):
      raise ContractError("依赖需求必须为非空字符串组成的 tuple")


@dataclass(frozen=True)
class SecretRef:
  """只承载 secret:<name> 引用，不存储或解析秘密值。"""

  reference: str = field(repr=False)

  def __post_init__(self):
    if not isinstance(self.reference, str) or not self.reference.startswith("secret:"):
      raise ContractError("凭据必须使用显式 secret 引用")
    safe_id(self.reference[len("secret:"):])


@dataclass(frozen=True)
class EnvironmentBinding:
  name: str
  value: str | SecretRef = field(repr=False)
  required: bool = True

  def __post_init__(self):
    if not isinstance(self.name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.name):
      raise ContractError("环境目标必须为明确的合法变量名")
    if not isinstance(self.value, (str, SecretRef)):
      raise ContractError("环境值必须为非秘密字面字符串或 SecretRef")
    if isinstance(self.value, str) and ("\0" in self.value or self.value.startswith("secret:")):
      raise ContractError("环境字面值不得包含空字节或冒充 SecretRef")
    if type(self.required) is not bool:
      raise ContractError("环境引用 required 必须为布尔值")
    if isinstance(self.value, str) and not self.required:
      raise ContractError("只有秘密引用可声明延迟凭据需求")


@dataclass(frozen=True)
class LaunchSpec:
  """只描述启动需求；cwd 由调用方解析，env 不代表完整子进程环境。

  required=False 仅适用于有上游证据的延迟认证；此处不检查凭据或启动进程。
  lock_identity 由后续锁/部署层提供和验证，不因本对象存在而代表运行包可用。
  """

  argv: tuple[str, ...] = field(repr=False)
  cwd: Path = field(repr=False)
  lock_identity: str = field(repr=False)
  environment: tuple[EnvironmentBinding, ...] = ()
  runtime_identity: str | None = field(default=None, repr=False)

  def __post_init__(self):
    if (not isinstance(self.argv, tuple) or not self.argv or not _text(self.argv[0])
        or not all(isinstance(arg, str) and "\0" not in arg for arg in self.argv)):
      raise ContractError("启动 argv 必须为非空字面字符串 tuple，不含空字节")
    if not isinstance(self.cwd, Path) or not self.cwd.is_absolute() or "\0" in str(self.cwd):
      raise ContractError("启动 cwd 必须由调用方明确解析为绝对路径")
    if not _text(self.lock_identity):
      raise ContractError("启动契约必须声明所需锁身份")
    if self.runtime_identity is not None and not _text(self.runtime_identity):
      raise ContractError("运行包身份必须是明确的非空标识")
    if (not isinstance(self.environment, tuple)
        or not all(isinstance(binding, EnvironmentBinding) for binding in self.environment)):
      raise ContractError("环境映射必须为 EnvironmentBinding tuple")
    names = [binding.name for binding in self.environment]
    if len(set(names)) != len(names):
      raise ContractError("普通值与秘密引用不得重复占用环境目标")


Config = TypeVar("Config")
NativeProjection = TypeVar("NativeProjection")
CaptureProposal = TypeVar("CaptureProposal")


class Adapter(ABC, Generic[Config, NativeProjection, CaptureProposal]):
  """七个无副作用钩子；能力/原生字段校验归 adapter，保护与执行归公共核心。

  泛型是各 adapter 已验证的非秘密数据，不是任意 extras schema。
  capture/doctor 仅接收预过滤的 allowlist 投影，不接收 OAuth 或完整原生文件。
  """

  @property
  @abstractmethod
  def declaration(self) -> AdapterDeclaration:
    """数据版本和原生映射版本分别声明。"""

  @abstractmethod
  def validate(self, config: Config) -> None:
    """不支持的能力/字段必须抛出脱敏错误，不静默丢弃。"""

  @abstractmethod
  def render(self, config: Config) -> tuple[Artifact, ...]:
    """生成非秘密确定性意图，不读当前运行文件。"""

  @abstractmethod
  def dependency_plan(self, config: Config) -> DependencyPlan:
    """仅描述需求，不解析、下载或安装依赖。"""

  @abstractmethod
  def managed_targets(self, config: Config) -> tuple[ManagedTarget, ...]:
    """声明五类所有权边界，不接管目标。"""

  @abstractmethod
  def launch_spec(self, config: Config, *, cwd: Path, runtime_root: Path,
                  instance_root: Path, lock_identity: str) -> LaunchSpec:
    """描述 argv、环境需求与锁身份，不启动进程。"""

  @abstractmethod
  def capture(self, projection: NativeProjection) -> CaptureProposal:
    """转换允许捕获的非秘密投影，不写机器文件或提案文件。"""

  @abstractmethod
  def doctor(self, projection: NativeProjection) -> tuple[str, ...]:
    """返回公开诊断代码；离线且不读取认证文件。"""

  def project_write_guard(self, workspace, project):
    from contextlib import nullcontext
    return nullcontext()

  def diagnostic_exit_code(self, capabilities):
    return 0

  def capability_diagnostics(self, projection):
    return None

  def dependency_backend(self):
    raise NotImplementedError("adapter must provide dependency_backend")

  @property
  def shared_files(self) -> tuple[str, ...]:
    return ()

  def launch_preflight(self, lock) -> list[dict]:
    return []

  def launch_preflight_for(self, config, lock) -> list[dict]:
    return self.launch_preflight(lock)

  def validate_arguments(self, arguments) -> None:
    return None

  def prepare_runtime(self, workspace, root) -> None:
    return None

  def capture_projection(self, tree):
    raise NotImplementedError("adapter must provide capture_projection")

  def capture_configuration(self, projection, data):
    return self.capture(projection)
