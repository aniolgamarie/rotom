import { webServiceSelected as agentcfgServiceSelected } from "@agentcfg/pi-runtime/web-binding";
import { webFetchFor } from "@agentcfg/pi-runtime/web-binding";
const agentcfgFetch = webFetchFor("gemini-auth");
import { webConfigurationIdentity, webCredentialDocument, webCredentialDeclared, webConfig as agentcfgWebConfig } from "@agentcfg/pi-runtime/web-config";
import { createHash, createSign } from "node:crypto";
import { getWebSearchConfigPath } from "./utils.ts";
import { redactCredential, CredentialResolutionError } from "./credential-source.ts";

const CONFIG_PATH = getWebSearchConfigPath();
const TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token";
const VERTEX_HOST = "https://aiplatform.googleapis.com";
const VERTEX_API_VERSION = "v1";
const REFRESH_SKEW_MS = 60_000;

interface GeminiAdcConfig {
	geminiAdcCredentials?: string;
	geminiAuth?: unknown;
	geminiProject?: unknown;
	geminiLocation?: unknown;
	geminiApiKey?: unknown;
	geminiBaseUrl?: unknown;
}

let cachedConfig: GeminiAdcConfig | null = null;

function loadConfig(): GeminiAdcConfig { return agentcfgWebConfig() as GeminiAdcConfig; }

function normalizeIdentifier(value: unknown, envName: string): string | null {
	if (typeof value === "string") {
		const trimmed = value.trim();
		if (trimmed) return trimmed;
	}
	return null;
}

export function isAdcAuthSelected(): boolean {
	return (loadConfig().geminiAuth ?? "").toString().trim().toLowerCase() === "adc";
}

export function getAdcProject(): string | null {
	return (
		normalizeIdentifier(loadConfig().geminiProject, "GOOGLE_CLOUD_PROJECT") ??
		normalizeIdentifier(null, "GCLOUD_PROJECT")
	);
}

export function getAdcLocation(): string | null {
	return normalizeIdentifier(loadConfig().geminiLocation, "GOOGLE_CLOUD_LOCATION");
}

export function getVertexApiBase(project: string, location: string): string {
	return `${VERTEX_HOST}/${VERTEX_API_VERSION}/projects/${encodeURIComponent(project)}/locations/${encodeURIComponent(location)}/publishers/google`;
}

export function isVertexHost(origin: string): boolean {
	return origin === VERTEX_HOST;
}

interface AdcFile {
	type?: string;
	client_id?: string;
	client_secret?: string;
	refresh_token?: string;
	client_email?: string;
	private_key?: string;
	private_key_id?: string;
	token_uri?: string;
	universe_domain?: string;
}

function objectRecord(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function stringField(record: Record<string, unknown>, name: string): string | undefined {
	const value = record[name];
	return typeof value === "string" ? value : undefined;
}

function requiredString(record: Record<string, unknown>, name: string, context: string): string {
	const value = stringField(record, name)?.trim();
	if (!value) throw new Error(`${context} is missing ${name}`);
	return value;
}

function parseAdcFile(raw: string): AdcFile {
	const parsed = objectRecord(JSON.parse(raw));
	if (!parsed) throw new Error("credential root must be an object");
	const type = stringField(parsed, "type") ?? "authorized_user";
	if (type === "authorized_user") {
		return {
			type,
			client_id: requiredString(parsed, "client_id", "Gemini ADC authorized_user file"),
			client_secret: requiredString(parsed, "client_secret", "Gemini ADC authorized_user file"),
			refresh_token: requiredString(parsed, "refresh_token", "Gemini ADC authorized_user file"),
			universe_domain: stringField(parsed, "universe_domain"),
		};
	}
	if (type === "service_account") {
		return {
			type,
			client_email: requiredString(parsed, "client_email", "Gemini ADC service_account file"),
			private_key: requiredString(parsed, "private_key", "Gemini ADC service_account file"),
			private_key_id: stringField(parsed, "private_key_id"),
			token_uri: stringField(parsed, "token_uri"),
			universe_domain: stringField(parsed, "universe_domain"),
		};
	}
	return { type };
}

function parseTokenExchangeResponse(text: string, context: string): CachedToken {
	let raw: unknown;
	try {
		raw = JSON.parse(text);
	} catch (err) {
		const message = err instanceof Error ? err.message : String(err);
		throw new Error(`${context} returned invalid JSON: ${message}`);
	}
	const parsed = objectRecord(raw);
	if (!parsed) throw new Error(`${context} returned a non-object response`);
	const token = stringField(parsed, "access_token")?.trim();
	if (!token) throw new Error(`${context} returned no access_token`);
	const expiresIn = parsed.expires_in ?? 3600;
	if (typeof expiresIn !== "number" || !Number.isFinite(expiresIn)) {
		throw new Error(`${context} returned invalid expires_in`);
	}
	return { token, expiresAt: Date.now() + Math.max((expiresIn * 1000) - REFRESH_SKEW_MS, 60_000) };
}

async function loadAdcFile(signal?: AbortSignal): Promise<AdcFile> {
  const reference = loadConfig().geminiAdcCredentials;
  if (!reference) throw new Error("Gemini ADC credential reference is not bound");
  const raw = webCredentialDocument(reference, signal);
  try { return parseAdcFile(raw); }
  catch { throw new Error("Gemini ADC credential document is invalid"); }
}

interface CachedToken {
	token: string;
	expiresAt: number;
}

let cachedToken: CachedToken | null = null;
let cachedTokenOwner: object | null = null;
let cachedCredentialDigest: string | null = null;

export function clearAdcTokenCache(): void {
	cachedToken = null;
}

/**
 * Classifies a failed OAuth token exchange. Only explicit credential/authorization
 * rejections (400 invalid_client/invalid_grant/invalid_scope, 401, 403 denied)
 * mean the configured credentials themselves were refused — a hard credential
 * problem callers should surface rather than silently fall back. Everything else
 * (429 rate limit, 404, 5xx, network failures, timeouts) is transient, so it is
 * left as a plain Error and existing per-provider fallbacks keep working.
 */
const OAUTH_CREDENTIAL_REJECTION_STATUSES = new Set([400, 401, 403]);

function throwOnTokenExchangeFailure(res: Response, detail: string, status: number): never {
	if (OAUTH_CREDENTIAL_REJECTION_STATUSES.has(status)) {
		throw new CredentialResolutionError("Gemini ADC", "oauth-credential-rejected");
	}
	throw new Error(`Gemini ADC token exchange failed (${status}): ${detail.slice(0, 300)}`);
}

async function exchangeRefreshToken(cfg: AdcFile, signal?: AbortSignal): Promise<CachedToken> {
	const body = new URLSearchParams({
		client_id: cfg.client_id ?? "",
		client_secret: cfg.client_secret ?? "",
		refresh_token: cfg.refresh_token ?? "",
		grant_type: "refresh_token",
	});
	const res = await agentcfgFetch(TOKEN_ENDPOINT, {
		method: "POST",
		headers: { "Content-Type": "application/x-www-form-urlencoded" },
		body,
		signal,
	});
	const text = await res.text();
	if (!res.ok) {
		throwOnTokenExchangeFailure(res, text, res.status);
	}
	return parseTokenExchangeResponse(text, "Gemini ADC token exchange");
}

async function exchangeServiceAccountJwt(cfg: AdcFile, signal?: AbortSignal): Promise<CachedToken> {
	if (!cfg.client_email || !cfg.private_key) {
		throw new Error("Gemini ADC service_account file is missing client_email or private_key");
	}
	const now = Math.floor(Date.now() / 1000);
	const header = { alg: "RS256", typ: "JWT" };
	const claims = {
		iss: cfg.client_email,
		scope: "https://www.googleapis.com/auth/cloud-platform",
		aud: TOKEN_ENDPOINT,
		iat: now,
		exp: now + 3600,
	};
	const encodePart = (obj: object): string =>
		Buffer.from(JSON.stringify(obj)).toString("base64url");
	const assertion = `${encodePart(header)}.${encodePart(claims)}`;
	const signer = createSign("RSA-SHA256");
	signer.update(assertion);
	signer.end();
	const signature = signer.sign(cfg.private_key, "base64url");
	const jwt = `${assertion}.${signature}`;

	const body = new URLSearchParams({
		grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
		assertion: jwt,
	});
	const res = await agentcfgFetch(cfg.token_uri || TOKEN_ENDPOINT, {
		method: "POST",
		headers: { "Content-Type": "application/x-www-form-urlencoded" },
		body,
		signal,
	});
	const text = await res.text();
	if (!res.ok) {
		throwOnTokenExchangeFailure(res, text, res.status);
	}
	return parseTokenExchangeResponse(text, "Gemini ADC service account token exchange");
}

export async function getAdcAccessToken(signal?: AbortSignal): Promise<string> {
  const owner = webConfigurationIdentity();
  const cfg = await loadAdcFile(signal);
  if (webConfigurationIdentity() !== owner) throw new Error("WEB_ADC_STALE");
  const credentialDigest = createHash("sha256").update(JSON.stringify(cfg)).digest("hex");
  if (cachedToken && cachedTokenOwner === owner && cachedCredentialDigest === credentialDigest && cachedToken.expiresAt > Date.now()) return cachedToken.token;
  let resolvedToken: CachedToken;
	const type = cfg.type ?? "authorized_user";
	if (type === "authorized_user") {
		resolvedToken = await exchangeRefreshToken(cfg, signal);
	} else if (type === "service_account") {
		resolvedToken = await exchangeServiceAccountJwt(cfg, signal);
	} else {
		throw new Error(`Gemini ADC unsupported credential type "${type}" (expected authorized_user or service_account)`);
	}
  if (webConfigurationIdentity() !== owner) throw new Error("WEB_ADC_STALE");
  cachedToken = resolvedToken; cachedTokenOwner = owner; cachedCredentialDigest = credentialDigest;
  return resolvedToken.token;
}

export function isGeminiAdcAvailable(): boolean {
	if (!agentcfgServiceSelected("gemini-auth")) return false;
	if (!isAdcAuthSelected()) return false;
	// An explicitly configured Gemini API key takes precedence over ADC, so
	// existing key-based setups and their unit tests keep working unchanged.
	if (hasGeminiApiKeySource()) return false;
	// An explicit base URL (gateway/relay/proxy) also wins over ADC: if the
	// user deliberately routed Gemini somewhere, honor that routing.
	if (hasExplicitApiBase()) return false;
	if (!getAdcProject() || !getAdcLocation()) return false;
	return webCredentialDeclared(loadConfig().geminiAdcCredentials);
}

function hasGeminiApiKeySource(): boolean {
	const configured = loadConfig().geminiApiKey;
	if (typeof configured === "string" && configured.trim()) return true;
	return false;
}

function hasExplicitApiBase(): boolean {
	const configured = loadConfig().geminiBaseUrl;
	return typeof configured === "string" && configured.trim().length > 0;
}

export function redactAdcToken(text: string): string {
	return cachedToken ? redactCredential(text, cachedToken.token) : text;
}
