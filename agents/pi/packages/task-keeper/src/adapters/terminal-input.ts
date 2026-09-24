/** Pi passes complete input sequences. Terminal capability responses are not user control input. */
export function isHumanTerminalInput(data: string): boolean {
  const withoutReplies = data
    .replace(/\x1b\][\s\S]*?(?:\x07|\x1b\\)/g, "")
    .replace(/\x1bP[\s\S]*?\x1b\\/g, "")
    .replace(/\x1b\[\?[\d;:]*[cuy]/g, "")
    .replace(/\x1b\[>[\d;:]*[cm]/g, "")
    .replace(/\x1b\[\d+;\d+R/g, "")
    .replace(/\x1b\[(?:4|6|8);\d+;\d+t/g, "")
    .replace(/\x1b\[[IO]/g, "");
  return withoutReplies.length > 0;
}
