// send 是被预检确认支持关闭自主重试的真实 transport；此处不提供未计量 fallback。
import { clone, digest, reject } from "./managed-types.ts";

export class MeteredTransport {
  constructor({ ledger, send }) { this.ledger = ledger; this.send = send; }
  async request(reservation, payload) {
    if (reservation.payload_digest !== digest(payload)) reject("REQUEST_IDENTITY", 4);
    await this.ledger.reserve(reservation);
    await this.ledger.mark_sent(reservation.request_id);
    let result;
    try {
      result = await this.send(clone(payload), { request_id: reservation.request_id, route_id: reservation.route_id, retries: 0 });
    } catch {
      await this.ledger.mark_unknown(reservation.request_id);
      reject("TRANSPORT_OUTCOME_UNKNOWN", 5);
    }
    if (!result || !result.usage) {
      await this.ledger.mark_unknown(reservation.request_id);
      reject("TRANSPORT_USAGE_UNKNOWN", 5);
    }
    await this.ledger.settle(reservation.request_id, result.usage);
    return result.value;
  }
}
