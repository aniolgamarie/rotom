import { pluginModelMethod, selectedPluginModel } from "@agentcfg/pi-runtime/plugin-model";
import { pluginSettings } from "@agentcfg/pi-runtime/plugin-settings";
const complete = pluginModelMethod("pi-mcp", "complete");
type SamplingSettings = { enabled: boolean; model?: string; max_tokens?: number; auto_approve?: boolean };
function samplingSettings(): SamplingSettings | undefined {
  return (pluginSettings("pi-mcp", "mcp") as { sampling?: SamplingSettings }).sampling;
}
import type { Api, AssistantMessage, Message, Model, ProviderHeaders, TextContent } from "@earendil-works/pi-ai";
function truncateAtWord(text: string, limit: number): string { return text.length <= limit ? text : text.slice(0, limit) + "…"; }
import { throwIfAborted } from "./abort.ts";
import type { ExtensionUIContext, ModelRegistry } from "@earendil-works/pi-coding-agent";
import type { Client } from "@modelcontextprotocol/client";
import type {
  CreateMessageRequest,
  CreateMessageResult,
  ModelPreferences,
  SamplingMessage,
  SamplingMessageContentBlock,
} from "@modelcontextprotocol/client";

export type SamplingUIContext = Pick<ExtensionUIContext, "confirm">;
export type SamplingModelRegistry = Pick<ModelRegistry, "getAvailable" | "getApiKeyAndHeaders">;

export interface SamplingHandlerOptions {
  serverName: string;
  autoApprove: boolean;
  ui?: SamplingUIContext;
  modelRegistry: SamplingModelRegistry;
  getCurrentModel: () => Model<Api> | undefined;
  getSignal: () => AbortSignal | undefined;
}

export type ServerSamplingConfig = Omit<SamplingHandlerOptions, "serverName">;

export function registerSamplingHandler(client: Client, options: SamplingHandlerOptions): void {
  client.setRequestHandler("sampling/createMessage", request => {
    return handleSamplingRequest(options, request);
  });
}

export async function handleSamplingRequest(
  options: SamplingHandlerOptions,
  request: CreateMessageRequest,
): Promise<CreateMessageResult> {
  const params = request.params;
  const signal = options.getSignal();
  throwIfAborted(signal);

  if ("task" in params && params.task) {
    throw new Error("MCP sampling tasks are not supported");
  }
  if (params.includeContext && params.includeContext !== "none") {
    throw new Error("MCP sampling context inclusion is not supported");
  }
  if (params.tools?.length) {
    throw new Error("MCP sampling tool use is not supported");
  }
  if (params.toolChoice) {
    throw new Error("MCP sampling tool choice is not supported");
  }
  if (params.stopSequences?.length) {
    throw new Error("MCP sampling stop sequences are not supported");
  }

  const messages = params.messages.map(convertSamplingMessage);
  const settings = samplingSettings();
  if (settings?.enabled !== true) throw new Error("MCP_SAMPLING_NOT_SELECTED");
  const maxTokens = settings.max_tokens ?? 4096;
  if (!Number.isSafeInteger(params.maxTokens) || params.maxTokens < 1 || params.maxTokens > maxTokens) throw new Error("MCP_SAMPLING_TOKEN_LIMIT");
  if (messages.length > 128 || Buffer.byteLength(JSON.stringify(params)) > 1024 * 1024) throw new Error("MCP_SAMPLING_INPUT_LIMIT");
  const { model } = await resolveSamplingModel(options, params.modelPreferences);
  throwIfAborted(signal);
  await confirmSampling(
    options,
    "Approve MCP sampling request",
    formatRequestApproval(options.serverName, `${model.provider}/${model.id}`, params.systemPrompt, messages),
  );
  throwIfAborted(signal);

  const result = await complete(
    model,
    {
      ...(params.systemPrompt !== undefined ? { systemPrompt: params.systemPrompt } : {}),
      messages,
    },
    {
      maxTokens: params.maxTokens,
      ...(params.temperature !== undefined ? { temperature: params.temperature } : {}),
      ...(params.metadata !== undefined ? { metadata: params.metadata as Record<string, unknown> } : {}),
      ...(signal ? { signal } : {}),
    },
  );

  const converted = convertAssistantResult(result);
  throwIfAborted(signal);
  await confirmSampling(
    options,
    "Return MCP sampling response",
    formatResponseApproval(options.serverName, converted),
  );
  throwIfAborted(signal);
  selectedPluginModel("pi-mcp", settings.model, options.getCurrentModel());
  return converted;
}

function formatRequestApproval(
  serverName: string,
  modelName: string,
  systemPrompt: string | undefined,
  messages: Message[],
): string {
  const lines = [`${serverName} wants to sample ${messages.length} message${messages.length === 1 ? "" : "s"} with ${modelName}.`];
  if (systemPrompt) {
    lines.push(`System: ${truncateAtWord(systemPrompt, 400)}`);
  }
  for (const [index, message] of messages.entries()) {
    lines.push(`${index + 1}. ${message.role}: ${truncateAtWord(messageText(message), 400)}`);
  }
  return lines.join("\n\n");
}

function formatResponseApproval(serverName: string, response: CreateMessageResult): string {
  const text = response.content.type === "text" ? response.content.text : `[${response.content.type} content]`;
  return `${serverName} will receive this response from ${response.model}:\n\n${truncateAtWord(text, 1000)}`;
}

function messageText(message: Message): string {
  if (typeof message.content === "string") return message.content;
  return message.content.map((block) => {
    if (block.type === "text") return block.text;
    if (block.type === "image") return `[image: ${block.mimeType}]`;
    if (block.type === "thinking") return "[thinking]";
    if (block.type === "toolCall") return `[tool call: ${block.name}]`;
    return "[content]";
  }).join("\n");
}

async function resolveSamplingModel(
  options: SamplingHandlerOptions,
  modelPreferences: ModelPreferences | undefined,
): Promise<{
  model: Model<Api>;
  apiKey?: string;
  headers?: ProviderHeaders;
}> {
  // 服务端 hints 不能扩大或替换实例明确选择的模型，更不能按可用账号回退。
  void modelPreferences;
  const settings = samplingSettings();
  const model = selectedPluginModel("pi-mcp", settings?.model, options.getCurrentModel());
  return { model };
}

async function confirmSampling(options: SamplingHandlerOptions, title: string, message: string): Promise<void> {
  if (options.autoApprove && samplingSettings()?.auto_approve === true) return;
  if (!options.ui) {
    throw new Error("MCP sampling requires interactive approval. Set settings.samplingAutoApprove to true to allow it without UI.");
  }
  const approved = await options.ui.confirm(title, message);
  if (!approved) {
    throw new Error("MCP sampling request was declined");
  }
}

function convertSamplingMessage(message: SamplingMessage): Message {
  const blocks = Array.isArray(message.content) ? message.content : [message.content];
  if (message.role === "user") {
    return {
      role: "user",
      content: blocks.map(convertUserContent),
      timestamp: Date.now(),
    };
  }

  return {
    role: "assistant",
    content: blocks.map(convertAssistantContent),
    api: "mcp-sampling",
    provider: "mcp",
    model: "sampling-request",
    usage: zeroUsage(),
    stopReason: "stop",
    timestamp: Date.now(),
  };
}

function convertUserContent(block: SamplingMessageContentBlock): TextContent {
  if (block.type === "text") {
    return { type: "text", text: block.text };
  }
  throw new Error(`MCP sampling ${block.type} content is not supported`);
}

function convertAssistantContent(block: SamplingMessageContentBlock): TextContent {
  if (block.type === "text") {
    return { type: "text", text: block.text };
  }
  throw new Error(`MCP sampling assistant ${block.type} content is not supported`);
}

function convertAssistantResult(message: AssistantMessage): CreateMessageResult {
  if (message.stopReason === "error") {
    throw new Error("MCP_SAMPLING_MODEL_FAILED");
  }
  if (message.stopReason === "aborted") {
    throw new Error("MCP_SAMPLING_MODEL_ABORTED");
  }

  const text = message.content
    .map((block) => {
      if (block.type === "text") return block.text;
      if (block.type === "thinking") return undefined;
      throw new Error(`MCP sampling result ${block.type} content is not supported`);
    })
    .filter((value): value is string => value !== undefined)
    .join("\n\n")
    .trim();

  if (!text) {
    throw new Error("MCP sampling result did not contain text content");
  }

  return {
    role: "assistant",
    content: { type: "text", text },
    model: `${message.provider}/${message.model}`,
    stopReason: mapStopReason(message.stopReason),
  };
}

function mapStopReason(reason: AssistantMessage["stopReason"]): CreateMessageResult["stopReason"] {
  if (reason === "stop") return "endTurn";
  if (reason === "length") return "maxTokens";
  if (reason === "toolUse") return "toolUse";
  return reason;
}

function zeroUsage(): AssistantMessage["usage"] {
  return {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: 0,
    cost: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      total: 0,
    },
  };
}
