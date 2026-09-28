"""稳定的错误码，异常文本不携带私人正文。"""


class TermcfgError(Exception):
  def __init__(self, code: int, reason: str, next_command: str = "./termcfg doctor",
               *, component: str | None = None, target_id: str | None = None,
               stage: str | None = None):
    super().__init__(reason)
    self.code = code
    self.reason = reason
    self.next_command = next_command
    self.context = {key: value for key, value in (("component", component),
                    ("target_id", target_id), ("stage", stage)) if value is not None}
