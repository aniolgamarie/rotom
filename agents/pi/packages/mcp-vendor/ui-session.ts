import { mcpAppSettings } from "@agentcfg/pi-runtime/mcp-listener";
import { terminalHyperlink } from "@agentcfg/pi-runtime/service-bindings";
import { randomUUID } from "node:crypto";
import { UrlElicitationRequiredError, type CallToolResult } from "@modelcontextprotocol/client";
import type { McpExtensionState } from "./state.ts";
import {
  createUiModelContextUpdate,
  extractUiPromptText,
  UI_STREAM_HOST_CONTEXT_KEY,
  UI_STREAM_REQUEST_META_KEY,
  UI_STREAM_STRUCTURED_CONTENT_KEY,
  type UiHostContext,
  type UiMessageParams,
  type UiModelContextParams,
  type UiStreamMode,
} from "./types.ts";
import { logger } from "./logger.ts";
import { startUiServer } from "./ui-server.ts";
import type { UiServerHandle } from "./types.ts";
import type { SessionRecoveryDeps } from "./session-recovery.ts";
import { combineAbortSignals, isAbortError } from "./runtime-owner.ts";
import { abortable, throwIfAborted } from "./abort.ts";
import { InputRequiredNeedsUiError } from "./errors.ts";


export interface UiSessionRequest {
  serverName: string;
  toolName: string;
  toolArgs: Record<string, unknown>;
  uiResourceUri: string;
  streamMode?: UiStreamMode;
  signal?: AbortSignal;
  onNeedsAuth?: SessionRecoveryDeps["onNeedsAuth"];
}

export type UiSessionViewer = "browser" | "glimpse" | "suppressed";

export interface UiSessionRuntime {
  serverName: string;
  toolName: string;
  reused: boolean;
  streamId?: string;
  streamToken?: string;
  streamMode?: UiStreamMode;
  requestMeta?: Record<string, unknown>;
  url: string;
  viewer: UiSessionViewer;
  windowOpen: boolean;
  isActive: () => boolean;
  sendToolResult: (result: CallToolResult) => void;
  sendResultPatch: (result: CallToolResult) => void;
  sendToolCancelled: (reason: string) => void;
  close: (reason?: string) => void;
}

export interface UiSessionResultSummary {
  message: string;
  uiOpen: boolean;
  uiViewer?: UiSessionViewer;
  uiUrl?: string;
}

export function summarizeUiSessionResult(uiSession: UiSessionRuntime | null): UiSessionResultSummary {
  if (!uiSession) {
    return {
      message: "Interactive UI was unavailable; returning the tool result inline.",
      uiOpen: false,
    };
  }

  if (!uiSession.windowOpen) {
    const action = uiSession.reused ? "Updated the suppressed MCP UI session." : "MCP UI window was suppressed.";
    return {
      message: `${action} Open manually: ${uiSession.url}`,
      uiOpen: false,
      uiViewer: uiSession.viewer,
      uiUrl: uiSession.url,
    };
  }

  return {
    message: uiSession.reused
      ? "Updated the open UI."
      : "Interactive UI is open. I'll respond to your prompts and intents as you interact with it.",
    uiOpen: true,
    uiViewer: uiSession.viewer,
    uiUrl: uiSession.url,
  };
}

const MAX_COMPLETED_SESSIONS = 10;

function withStreamEnvelope(
  result: CallToolResult,
  streamId: string | undefined,
  sequence: number,
): CallToolResult {
  if (!streamId) {
    return result;
  }

  const structuredContent: Record<string, unknown> = result.structuredContent
    && typeof result.structuredContent === "object"
    && !Array.isArray(result.structuredContent)
    ? { ...(result.structuredContent as Record<string, unknown>) }
    : {};

  const rawEnvelope = structuredContent[UI_STREAM_STRUCTURED_CONTENT_KEY];
  const envelope = rawEnvelope && typeof rawEnvelope === "object" && !Array.isArray(rawEnvelope)
    ? { ...rawEnvelope as Record<string, unknown> }
    : {
        frameType: "final",
        phase: "settled",
        status: result.isError ? "error" : "ok",
      };

  structuredContent[UI_STREAM_STRUCTURED_CONTENT_KEY] = {
    ...envelope,
    streamId,
    sequence,
  };

  return {
    ...result,
    structuredContent,
  };
}

export async function maybeStartUiSession(
  state: McpExtensionState,
  request: UiSessionRequest,
): Promise<UiSessionRuntime | null> {
  const log = logger.child({
    component: "UiSession",
    server: request.serverName,
    tool: request.toolName,
  });
  const runtimeSignal = combineAbortSignals(state.owner?.signal, request.signal) ?? new AbortController().signal;

  try {
    mcpAppSettings(request.serverName);
    throwIfAborted(runtimeSignal);
    if (
      state.uiServer &&
      state.uiServer.serverName === request.serverName &&
      state.uiServer.toolName === request.toolName
    ) {
      const existingHandle = state.uiServer;
      const streamMode = request.streamMode;
      const streamId = streamMode ? randomUUID() : undefined;
      const streamToken = streamMode ? randomUUID() : undefined;
      let active = true;
      let nextStreamSequence = 0;

      const cleanupStreamListener = () => {
        if (streamToken) {
          state.manager.removeUiStreamListener(streamToken);
        }
      };

      existingHandle.sendToolInput(request.toolArgs);

      if (streamToken) {
        state.manager.registerUiStreamListener(streamToken, (serverName, notification) => {
          if (!active || state.uiServer !== existingHandle) return;
          if (serverName !== request.serverName) return;
          nextStreamSequence += 1;
          existingHandle.sendResultPatch(
            withStreamEnvelope(notification.result as CallToolResult, streamId, nextStreamSequence),
          );
        });
      }

      return {
        serverName: request.serverName,
        toolName: request.toolName,
        reused: true,
        ...(streamId !== undefined ? { streamId } : {}),
        ...(streamToken !== undefined ? { streamToken } : {}),
        ...(streamMode !== undefined ? { streamMode } : {}),
        ...(streamToken ? { requestMeta: { [UI_STREAM_REQUEST_META_KEY]: streamToken } } : {}),
        url: existingHandle.url,
        viewer: existingHandle.viewer ?? "browser",
        windowOpen: existingHandle.windowOpen ?? true,
        isActive: () => active && state.uiServer === existingHandle,
        sendToolResult: (result: CallToolResult) => {
          if (!active || state.uiServer !== existingHandle) return;
          nextStreamSequence += 1;
          existingHandle.sendToolResult(withStreamEnvelope(result, streamId, nextStreamSequence));
        },
        sendResultPatch: (result: CallToolResult) => {
          if (!active || state.uiServer !== existingHandle) return;
          nextStreamSequence += 1;
          existingHandle.sendResultPatch(withStreamEnvelope(result, streamId, nextStreamSequence));
        },
        sendToolCancelled: (reason: string) => {
          if (!active || state.uiServer !== existingHandle) return;
          nextStreamSequence += 1;
          existingHandle.sendToolResult(
            withStreamEnvelope(
              {
                isError: true,
                content: [{ type: "text", text: reason }],
              },
              streamId,
              nextStreamSequence,
            ),
          );
        },
        close: () => {
          active = false;
          cleanupStreamListener();
        },
      };
    }

    const resource = await state.uiResourceHandler.readUiResource(request.serverName, request.uiResourceUri, {
      config: state.config,
      signal: runtimeSignal,
      onNeedsAuth: request.onNeedsAuth,
    });
    throwIfAborted(runtimeSignal);

    if (state.uiServer) {
      await state.uiServer.close("replaced");
      state.uiServer = null;
    }

    const streamMode = request.streamMode;
    const streamId = streamMode ? randomUUID() : undefined;
    const streamToken = streamMode ? randomUUID() : undefined;
    const hostContext: UiHostContext | undefined = streamMode && streamId
      ? {
          [UI_STREAM_HOST_CONTEXT_KEY]: {
            mode: streamMode,
            streamId,
            intermediateResultPatches: streamMode === "stream-first",
            partialInput: false,
          },
        }
      : undefined;

    let active = true;
    let nextStreamSequence = 0;
    let handle: UiServerHandle;
    const resourceListenerToken = randomUUID();

    const cleanupListeners = () => {
      if (streamToken) {
        state.manager.removeUiStreamListener(streamToken);
      }
      state.manager.removeResourceUpdatedListener?.(resourceListenerToken);
    };

    handle = await startUiServer({
      startupSignal: runtimeSignal,
      serverName: request.serverName,
      toolName: request.toolName,
      toolArgs: streamMode === "stream-first" ? {} : request.toolArgs,
      resource,
      manager: state.manager,
      config: state.config,
      state,
      ...(request.onNeedsAuth ? { onNeedsAuth: request.onNeedsAuth } : {}),
      consentManager: state.consentManager,
      ...(hostContext !== undefined ? { hostContext } : {}),

      onMessage: async (params: UiMessageParams, signal: AbortSignal) => {
        if (extractUiPromptText(params) || params.type === "intent" || params.intent) {
          const description = JSON.stringify(params);
          if (description.length > 65536) throw new Error("MCP_APP_MESSAGE_LIMIT");
          if (!state.ui?.confirm) throw new Error("MCP_APP_MESSAGE_APPROVAL_REQUIRED");
          if (!await abortable(state.ui.confirm("Allow MCP App to request an agent turn?", description), signal)) return;
          mcpAppSettings(request.serverName);
          throwIfAborted(signal);
        }
        const prompt = extractUiPromptText(params);
        if (prompt) {
          if (state.sendMessage) {
            state.sendMessage(
              {
                customType: "mcp-ui-prompt",
                content: [{ type: "text", text: `User sent prompt from ${request.serverName} UI: "${prompt}"` }],
                display: `💬 UI Prompt: ${prompt}`,
                details: { server: request.serverName, tool: request.toolName, prompt },
              },
              { triggerTurn: true },
            );
            log.debug("Triggered agent turn for UI prompt", { prompt: prompt.slice(0, 50) });
          }
        } else if (params.type === "intent" || params.intent) {
          const intent = params.intent ?? "";
          const intentParams = params.params;
          if (intent && state.sendMessage) {
            const paramsStr = intentParams ? ` ${JSON.stringify(intentParams)}` : "";
            state.sendMessage(
              {
                customType: "mcp-ui-intent",
                content: [{ type: "text", text: `User triggered intent from ${request.serverName} UI: ${intent}${paramsStr}` }],
                display: `🎯 UI Intent: ${intent}`,
                details: { server: request.serverName, tool: request.toolName, intent, params: intentParams },
              },
              { triggerTurn: true },
            );
            log.debug("Triggered agent turn for UI intent", { intent });
          }
        } else if (params.type === "notify" || params.message) {
          const text = params.message ?? "";
          if (text && state.ui) {
            state.ui.notify(`[${request.serverName}] ${text}`, "info");
          }
        }
      },

      onContextUpdate: (params: UiModelContextParams) => {
        const update = createUiModelContextUpdate(params);
        log.debug("Model context update from UI", {
          hasContent: !!params.content,
          hasStructured: !!params.structuredContent,
          hasUpdate: !!update,
        });
        if (update && state.sendMessage) {
          state.sendMessage(
            {
              customType: "mcp-ui-context",
              content: [{ type: "text", text: `User submitted model context from ${request.serverName} UI:\n${update.summary}` }],
              display: "UI Context submitted",
              details: { server: request.serverName, tool: request.toolName, context: update },
            },
            { triggerTurn: true },
          );
        }
      },

      onComplete: (reason: string) => {
        active = false;
        cleanupListeners();

        if (state.uiServer === handle) {
          const messages = handle.getSessionMessages();
          const stream = handle.getStreamSummary();
          const hasContent =
            messages.prompts.length > 0 ||
            messages.intents.length > 0 ||
            messages.notifications.length > 0 ||
            messages.contexts.length > 0 ||
            !!stream;

          if (hasContent) {
            state.completedUiSessions.push({
              serverName: handle.serverName,
              toolName: handle.toolName,
              completedAt: new Date(),
              reason,
              messages,
              ...(stream !== undefined ? { stream } : {}),
            });

            while (state.completedUiSessions.length > MAX_COMPLETED_SESSIONS) {
              state.completedUiSessions.shift();
            }

            log.debug("Session completed", {
              reason,
              prompts: messages.prompts.length,
              intents: messages.intents.length,
              notifications: messages.notifications.length,
              contexts: messages.contexts.length,
              streamFrames: stream?.frames ?? 0,
            });
          }

          state.uiServer = null;
        }
      },
    });

    if (state.owner?.isActive() === false || runtimeSignal.aborted) {
      await handle.close("runtime_owner_stopped");
      throwIfAborted(runtimeSignal);
      throw new Error("MCP UI session became stale before registration");
    }

    if (streamToken) {
      state.manager.registerUiStreamListener(streamToken, (serverName, notification) => {
        if (!active || state.uiServer !== handle) return;
        if (serverName !== request.serverName) return;
        nextStreamSequence += 1;
        handle.sendResultPatch(withStreamEnvelope(notification.result as CallToolResult, streamId, nextStreamSequence));
      });
    }

    state.manager.registerResourceUpdatedListener?.(
      resourceListenerToken,
      request.serverName,
      request.uiResourceUri,
      (_serverName, uri) => {
        if (!active || state.uiServer !== handle) return;
        handle.sendResourceUpdated(uri);
      },
    );

    state.uiServer = handle;

    const viewer: UiSessionViewer = "browser";
    const windowOpen = false;
    process.stdout.write(terminalHyperlink(handle.url));
    state.ui?.notify(`Open the displayed MCP App link in your browser. For a remote host, forward both loopback ports ${handle.port} and ${handle.proxyPort}.`, "info");

    throwIfAborted(runtimeSignal);
    handle.viewer = viewer;
    handle.windowOpen = windowOpen;

    return {
      serverName: request.serverName,
      toolName: request.toolName,
      reused: false,
      ...(streamId !== undefined ? { streamId } : {}),
      ...(streamToken !== undefined ? { streamToken } : {}),
      ...(streamMode !== undefined ? { streamMode } : {}),
      ...(streamToken ? { requestMeta: { [UI_STREAM_REQUEST_META_KEY]: streamToken } } : {}),
      url: handle.url,
      viewer,
      windowOpen,
      isActive: () => active && state.uiServer === handle,
      sendToolResult: (result: CallToolResult) => {
        if (!active || state.uiServer !== handle) return;
        nextStreamSequence += 1;
        handle.sendToolResult(withStreamEnvelope(result, streamId, nextStreamSequence));
      },
      sendResultPatch: (result: CallToolResult) => {
        if (!active || state.uiServer !== handle) return;
        nextStreamSequence += 1;
        handle.sendResultPatch(withStreamEnvelope(result, streamId, nextStreamSequence));
      },
      sendToolCancelled: (reason: string) => {
        if (!active || state.uiServer !== handle) return;
        handle.sendToolCancelled(reason);
      },
      close: async (reason?: string) => {
        active = false;
        cleanupListeners();
        await handle.close(reason);
      },
    };
  } catch (error) {
    if (error instanceof UrlElicitationRequiredError || error instanceof InputRequiredNeedsUiError || isAbortError(error, runtimeSignal)) throw error;
    const message = error instanceof Error ? error.message : String(error);
    log.error("Failed to start UI session", error instanceof Error ? error : undefined);
    state.ui?.notify(
      `MCP UI unavailable for ${request.toolName} (${request.serverName}): ${message}`,
      "warning",
    );
    return null;
  }
}
