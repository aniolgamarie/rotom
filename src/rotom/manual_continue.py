"""只在显式交互中展示当次人工文本；不发送、不持久化或签发继续许可。"""
from agentcfg.presentation import _text
from .context import InputError, InputPolicy


_TEXT_ERROR = "文本无效：仅接受可打印单行，最多4096字符/16384 UTF-8字节；未发送。"


def offer(context, requested):
  """返回 None；正文仅局部使用，不能成为恢复参数、回执或上下文字段。"""
  if context.input_policy != InputPolicy.INTERACTIVE:
    return None
  gateway, policy = context.input_gateway, context.input_policy
  choice = gateway.choose((("resume", "仅恢复（不准备文本）"),
    ("sample", "展示固定示例：继续"), ("custom", "自定义单行文本（仅手工复制）")),
    policy=policy, label="人工继续选项")
  if choice == "resume":
    return None
  print("当前请求目标：" + _text(requested), file=gateway.stderr)
  print("加载未确认，请先在官方 TUI 核对会话 ID、原目录和历史；此处仅展示文本，不代表已恢复，也不会自动发送。", file=gateway.stderr)
  try:
    text = "继续" if choice == "sample" else gateway.text("仅当次展示的自定义单行文本", policy=policy)
    if (type(text) is not str or not text or len(text) > 4096
        or not text.isprintable() or len(text.encode("utf-8", errors="strict")) > 16384):
      raise InputError(2)
  except (InputError, UnicodeError) as error:
    if isinstance(error, InputError) and error.exit_code == 130:
      raise
    print(_TEXT_ERROR, file=gateway.stderr)
    raise InputError(2) from None
  # 校验后才展示正文，保留首尾空格；不复制到任何请求或持久对象。
  print("文本预览（保留首尾空格）：", file=gateway.stderr)
  print(text, file=gateway.stderr, flush=True)
  gateway.confirm("仅在此展示供手工复制，不发送", policy=policy)
  print("请自行核对官方 TUI 的会话 ID、原目录和历史，再自行聚焦输入框、手工复制或输入。"
    "Rotom 未操作剪贴板、聚焦或发送；未发送继续。", file=gateway.stderr)
  return None
