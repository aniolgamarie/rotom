"""运行时秘密能力；不提供映射、默认序列化或编译输入接口。"""

from .adapter import SecretRef
from .paths import PathError, safe_id
import hashlib


def credential_id(reference):
  return "credential-" + hashlib.sha256(reference.encode()).hexdigest()[:16]


class CredentialError(Exception):
  """固定凭据错误；不保存引用名、值或底层异常。"""

  exit_code = 3

  def __init__(self, reference=None):
    suffix = ("；定位 " + credential_id(reference) + "，执行 doctor 后在私人 locations.json 中查找对应 secret 引用") if reference else ""
    super().__init__("凭据无效或所需凭据缺失" + suffix)


def _valid_values(values: object) -> bool:
  if not isinstance(values, dict):
    return False
  try:
    for name, value in values.items():
      safe_id(name)
      if not isinstance(value, str):
        return False
  except PathError:
    return False
  return True


class SecretStore:
  """仅 resolve 可返回秘密；不是防止同进程主动反射的安全沙箱。"""

  __slots__ = ("__values",)

  def __init__(self, values: dict[str, str]):
    if not _valid_values(values):
      raise CredentialError()
    self.__values = dict(values)

  def __repr__(self) -> str:
    return "SecretStore()"

  def __reduce_ex__(self, protocol):
    raise TypeError("秘密存储不得序列化")

  def resolve(self, reference: SecretRef, *, required: bool = True) -> str | None:
    if not isinstance(reference, SecretRef) or type(required) is not bool:
      raise CredentialError()
    value = self.__values.get(reference.reference[len("secret:"):])
    if not value:
      if required:
        raise CredentialError(reference.reference)
      return None
    return value
