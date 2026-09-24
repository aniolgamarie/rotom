import { agentcfgRuntime } from "./agentcfg";
import type { ExtensionCommandContext, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { DEFAULT_EXTENSION_CONFIG, type PermissionSystemExtensionConfig } from "./extension-config";
import type { ResolvedPolicyPaths } from "./policy-loader";
import type { DebugReviewLogger } from "./session-logger";
import { syncPermissionSystemStatus } from "./status";

/** Read-only view of the current config — for consumers that only read. */
export interface ConfigReader {
  current(): PermissionSystemExtensionConfig;
}

/**
 * Narrow subset of `ConfigStore` that `PermissionSession` depends on.
 *
 * Using an interface rather than the concrete class avoids private-member
 * coupling between the class and test doubles.
 */
export interface SessionConfigStore extends ConfigReader {
  refresh(ctx: ExtensionContext | undefined, projectTrusted: boolean): void;
  logResolvedPaths(cwd?: string): void;
}

/**
 * Narrow subset of `ConfigStore` for the `/permission-system` command.
 *
 * Using an interface rather than the concrete class avoids private-member
 * coupling between the class and test doubles.
 */
export interface CommandConfigStore extends ConfigReader {
  save(
    next: PermissionSystemExtensionConfig,
    ctx: ExtensionCommandContext,
  ): void;
}

/** Narrow view of the manager's resolved policy paths (for `logResolvedPaths`). */
export interface ResolvedPolicyPathProvider {
  getResolvedPolicyPaths(): ResolvedPolicyPaths;
}

export interface ConfigStoreDeps {
  agentDir: string;
  policyPaths: ResolvedPolicyPathProvider;
  logger: DebugReviewLogger;
}

/**
 * Owns the mutable extension config and the operations that read/write it.
 *
 * Replaces the three `(runtime, …)` config free functions
 * (`refreshExtensionConfig`, `saveExtensionConfig`, `logResolvedConfigPaths`)
 * with methods that privately own `config` and `lastConfigWarning`.
 *
 * Implements {@link ConfigReader} so consumers that only read the current config
 * can depend on the narrow interface rather than the full class.
 */
export class ConfigStore implements SessionConfigStore, CommandConfigStore {
  private config: PermissionSystemExtensionConfig;
  private agentcfgContext: ExtensionContext | undefined;

  constructor(_deps: ConfigStoreDeps) {
    this.config = { ...DEFAULT_EXTENSION_CONFIG };
  }

  /** Return the current extension config. */
  current(): PermissionSystemExtensionConfig {
    const runtime = agentcfgRuntime(), ctx = this.agentcfgContext;
    return { ...this.config, debugLog: false, permissionReviewLog: false,
      yoloMode: ctx ? runtime.permissionAccess.yolo(ctx.sessionManager.getSessionId(), ctx.cwd) : false };
  }

  /**
   * Reload merged config from disk.
   *
   * If `ctx` is provided, uses it to derive the cwd and sync UI status.
   * When `projectTrusted` is `false`, the project scope is withheld so an
   * untrusted repository's runtime config (`yoloMode`, `permissionReviewLog`,
   * …) cannot loosen the operator's global config (#644).
   */
  refresh(ctx: ExtensionContext | undefined, projectTrusted: boolean): void {
    agentcfgRuntime();
    this.agentcfgContext = ctx;
    this.config = { ...DEFAULT_EXTENSION_CONFIG, debugLog: false, permissionReviewLog: false, yoloMode: false };
    if (ctx?.hasUI) syncPermissionSystemStatus(ctx, this.current());
  }

  /**
   * Save updated runtime knobs to the global config file, then update
   * the current config and sync UI status.
   *
   * Equivalent to `saveExtensionConfig(runtime, next, ctx)`.
   */
  save(
    next: PermissionSystemExtensionConfig,
    ctx: ExtensionCommandContext,
  ): void {
    agentcfgRuntime();
    ctx.ui.notify("AGENTCFG_CONFIGURATION_REQUIRED: edit agentcfg sources, then plan/apply after exiting this instance. Use /yolo for a bounded session prompt override.", "warning");
  }

  /**
   * Write the resolved config path set to the review and debug logs.
   *
   * Equivalent to `logResolvedConfigPaths(runtime)`.
   */
  logResolvedPaths(cwd?: string): void {
    agentcfgRuntime();
  }
}
