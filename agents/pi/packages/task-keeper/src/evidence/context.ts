import { canonical, digest, finiteInteger, ContractError } from "../contracts/primitives.ts";

/** Bound serialized UTF-8 evidence, independently of provider-specific token estimation. */
export function compileContextEvidence(body: unknown, maxBytes: number) {
  finiteInteger(maxBytes, 1, 16 * 1024 * 1024);
  const content = canonical(body), bytes = Buffer.byteLength(content, "utf8");
  if (bytes > maxBytes) throw new ContractError("PACKET_TOO_LARGE", `PACKET_TOO_LARGE: ${bytes} UTF-8 bytes exceed evidence.packetByteBudget=${maxBytes}`);
  return { content, bytes, digest: digest(body) };
}
