// 公共页面请求在连接前固定已核验地址；显式声明的 CIDR 例外用于内网或 fake-IP 线路。
import { BlockList, isIP } from "node:net";
import { reject } from "./managed-types.ts";

const blocked = new BlockList();
for (const [address, prefix] of [["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8],
  ["169.254.0.0", 16], ["172.16.0.0", 12], ["192.0.0.0", 24], ["192.0.2.0", 24], ["192.168.0.0", 16],
  ["198.18.0.0", 15], ["198.51.100.0", 24], ["203.0.113.0", 24], ["224.0.0.0", 3]]) blocked.addSubnet(address, prefix, "ipv4");
for (const [address, prefix] of [["::", 96], ["::1", 128], ["fc00::", 7], ["fe80::", 10], ["fec0::", 10],
  ["ff00::", 8], ["2001:db8::", 32], ["64:ff9b:1::", 48]]) blocked.addSubnet(address, prefix, "ipv6");
const nat64 = new BlockList(); nat64.addSubnet("64:ff9b::", 96, "ipv6");

export function addressPolicy(ranges = []) {
  if (!Array.isArray(ranges) || ranges.length > 128) reject("WEB_ADDRESS_POLICY_INVALID", 2);
  const allowed = new BlockList();
  for (const range of ranges) {
    if (typeof range !== "string" || /[\s%]/.test(range)) reject("WEB_ADDRESS_POLICY_INVALID", 2);
    const parts = range.split("/"), family = isIP(parts[0]);
    const max = family === 4 ? 32 : 128;
    const prefix = parts.length === 1 ? max : /^\d+$/.test(parts[1]) ? Number(parts[1]) : -1;
    if (!family || parts.length > 2 || !Number.isInteger(prefix) || prefix < 1 || prefix > max) reject("WEB_ADDRESS_POLICY_INVALID", 2);
    allowed.addSubnet(parts[0], prefix, family === 4 ? "ipv4" : "ipv6");
  }
  return address => {
    const family = typeof address === "string" && !address.includes("%") ? isIP(address) : 0;
    if (!family) reject("WEB_ADDRESS_INVALID", 4);
    const kind = family === 4 ? "ipv4" : "ipv6";
    if (allowed.check(address, kind)) return;
    if (blocked.check(address, kind)) reject("WEB_PRIVATE_ADDRESS", 4);
    if (family === 6 && nat64.check(address, "ipv6")) {
      const text = new URL("http://[" + address + "]").hostname.slice(1, -1);
      const [left, right] = text.split("::"), first = left ? left.split(":") : [], last = right ? right.split(":") : [];
      const groups = right === undefined ? first : [...first, ...Array(8 - first.length - last.length).fill("0"), ...last];
      const a = parseInt(groups[6], 16), b = parseInt(groups[7], 16);
      const mapped = [a >> 8, a & 255, b >> 8, b & 255].join(".");
      if (blocked.check(mapped, "ipv4") && !allowed.check(mapped, "ipv4")) reject("WEB_PRIVATE_ADDRESS", 4);
    }
  };
}

export function checkWebHostname(url, policy = {}) {
  const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  const matches = value => {
    if (typeof value !== "string" || !value || /[\s/@:?#]/.test(value)) reject("WEB_DOMAIN_POLICY_INVALID", 2);
    const name = value.toLowerCase().replace(/^\*?\./, "").replace(/\.$/, "");
    return host === name || host.endsWith("." + name);
  };
  const allow = policy.domain_allow ?? [], deny = policy.domain_deny ?? [];
  if (!Array.isArray(allow) || !Array.isArray(deny)) reject("WEB_DOMAIN_POLICY_INVALID", 2);
  if (deny.some(matches) || allow.length && !allow.some(matches)) reject("WEB_DOMAIN_DENIED", 4);
  return host;
}
