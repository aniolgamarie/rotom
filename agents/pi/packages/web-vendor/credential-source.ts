import { webCredential, webCredentialDeclared } from "@agentcfg/pi-runtime/web-config";

export type CredentialFailureCategory =
	| "invalid-source"
	| "command-failed"
	| "command-timeout"
	| "command-aborted"
	| "command-empty"
	| "command-invalid-output"
	| "command-output-too-large"
	| "environment-empty"
	| "oauth-credential-rejected";

export class CredentialResolutionError extends Error {
	readonly provider: string;
	readonly category: CredentialFailureCategory;

	constructor(provider: string, category: CredentialFailureCategory) {
		const suffix =
			category === "command-aborted" ? "aborted" :
			category === "oauth-credential-rejected" ? "OAuth token exchange rejected the credentials" :
			category;
		super(`${provider} credential resolution failed: ${suffix}`);
		this.name = "CredentialResolutionError";
		this.provider = provider;
		this.category = category;
	}
}

export interface CredentialCommandResult {
	stdout: string | Buffer;
}

export interface CredentialCommandOptions {
	signal?: AbortSignal;
	timeoutMs: number;
	maxOutputBytes: number;
	environment: Record<string, string>;
}

export type CredentialCommandRunner = (
	command: string,
	options: CredentialCommandOptions,
) => Promise<CredentialCommandResult>;

export interface CredentialOptions {
	provider: string;
	configuredValue?: unknown;
	environmentValue?: unknown;
	environment?: Record<string, string | undefined>;
	signal?: AbortSignal;
	runCommand?: CredentialCommandRunner;
}

export function redactCredential(text: string, credential: string | null | undefined): string {
	return credential ? text.split(credential).join("[redacted]") : text;
}

export function hasCredentialSource(options: CredentialOptions): boolean {
  try { return webCredentialDeclared(options.configuredValue); }
  catch { throw new CredentialResolutionError(options.provider, "invalid-source"); }
}

export async function resolveCredential(options: CredentialOptions): Promise<string | null> {
  if (!hasCredentialSource(options)) return null;
  try { return webCredential(options.configuredValue, options.signal); }
  catch (error) {
    if (options.signal?.aborted) throw new CredentialResolutionError(options.provider, "command-aborted");
    const message = error instanceof Error ? error.message : "";
    if (message === "WEB_CREDENTIAL_MISSING") throw new CredentialResolutionError(options.provider, "environment-empty");
    throw new CredentialResolutionError(options.provider, "invalid-source");
  }
}
