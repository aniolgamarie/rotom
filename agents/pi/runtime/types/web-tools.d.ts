import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
export function bindWebTools(pi: ExtensionAPI): {
  registerTool: ExtensionAPI["registerTool"];
  registerCommand: ExtensionAPI["registerCommand"];
  registerShortcut: ExtensionAPI["registerShortcut"];
  reset(): Promise<void>;
  close(): Promise<void>;
};
