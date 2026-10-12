// 只有显式probe callback调用才打开container-local固定loopback；import无IO。
import net from "node:net";
export async function localRoundTrip() {
  const server = net.createServer(socket => { socket.end("OWN_LOCAL_SINK"); });
  try {
    await new Promise((resolve, reject) => { server.once("error", reject); server.listen(35731, "127.0.0.1", resolve); });
    return await new Promise(resolve => {
      let count = 0, content = "", correct = false; const client = net.connect({ host: "127.0.0.1", port: 35731 });
      client.setTimeout(250); client.on("data", data => { count += data.length; if (count > 64) { client.destroy(); return; } content += data.toString(); correct = content === "OWN_LOCAL_SINK"; if (correct) client.destroy(); });
      client.once("error", () => { client.destroy(); resolve(false); }); client.once("timeout", () => { client.destroy(); resolve(false); }); client.once("close", () => resolve(correct));
    });
  } finally { if (server.listening) await new Promise(resolve => server.close(resolve)); }
}
export async function deniedOutbound() {
  // TEST-NET-1固定合成地址；本包将来只可在network:none的已核验容器调用。
  return new Promise(resolve => {
    const client = net.connect({ host: "192.0.2.1", port: 35731 });
    client.setTimeout(250); client.once("connect", () => { client.destroy(); resolve(true); });
    client.once("error", () => { client.destroy(); resolve(false); }); client.once("timeout", () => { client.destroy(); resolve(false); });
  });
}
