// 将 managed-executor-v1 绑定到 factory 已创建的管理者，绝不另建调度器。

import { join } from "node:path";
import { externalControl } from "@agentcfg/pi-runtime/external-control";
import { ExternalBridge } from "@agentcfg/pi-runtime/external-executor";
import { registerExternalRpc } from "@agentcfg/pi-runtime/external-rpc";
import { ManagedBridge } from "@agentcfg/pi-runtime/managed-bridge";
import { listenerCount, registerManagedRpc } from "@agentcfg/pi-runtime/managed-rpc";
import { ManagedStore } from "@agentcfg/pi-runtime/managed-store";
import { reject } from "@agentcfg/pi-runtime/managed-types";
import { ManagerExecutor } from "@agentcfg/pi-runtime/manager-executor";
import type { AgentManager } from "./agent-manager.js";
import { BRIDGE_KEY, runtimeContext } from "./agentcfg-config.js";

export function attachManaged(manager: AgentManager, pi: any, getContext: () => any) {
  if ((globalThis as any)[BRIDGE_KEY] !== undefined || listenerCount(pi.events)) reject("MANAGER_LISTENER_CONFLICT", 5);
  const context = runtimeContext();
  const owner = { instance_id: context.owner.instance_id, manager_activation_id: context.owner.manager_activation_id, owner_nonce: context.owner.owner_nonce };
  const authorize = async () => {
    const current = await context.supervisor.call("handshake", {});
    if (current.manager_activation_id !== owner.manager_activation_id || current.owner_nonce !== owner.owner_nonce
        || current.runtime_identity !== context.installed.runtime_identity) reject("OWNER_MISMATCH", 4);
  };
  const external = context.manifest.options.model_delegate?.enabled ? new ExternalBridge({ runtime: context, manager, pi, getContext,
    store: new ManagedStore({ root: join(context.instanceRoot, "pi-home", "model-delegate", "manager"), owner, authorize }) }) : null;
  const offExternal = external ? registerExternalRpc(pi.events, external) : () => {};
  const control = external ? externalControl({ runtime: context, bridge: external,
    root: join(context.instanceRoot, "pi-home", "model-delegate", "manager") }) : Promise.resolve(null);
  // 失败时没有可用批次端点；拒绝隐藏的独立 fanout 执行。
  void control.catch(() => {});
  const closeExternal = async () => { offExternal(); const stop = await control.catch(() => null); await stop?.(); await external?.close(); };
  const backend = context.managedBackend;
  // 未完成 worker/transport 认证的运行包不能靠补丁版本号宣称能力存在。
  if (!backend) {
    const fail = () => reject("CAPABILITY_MISSING", 5);
    const unavailable = { handshake: fail, preflight: fail, dispatch: fail, inspect: fail, get_result: fail, cancelAttempt: fail, reconcile: fail, consume: fail };
    const off = registerManagedRpc(pi.events, unavailable);
    const entry = Object.freeze({ manager, external, pi, getContext, available: false });
    (globalThis as any)[BRIDGE_KEY] = entry;
    return async () => { off(); await closeExternal(); if ((globalThis as any)[BRIDGE_KEY] === entry) delete (globalThis as any)[BRIDGE_KEY]; };
  }
  const store = new ManagedStore({ root: join(context.instanceRoot, "pi-home", "managed-executions"), owner,
    authorize: async () => {
      const current = await context.supervisor.call("handshake", {});
      if (current.manager_activation_id !== owner.manager_activation_id || current.owner_nonce !== owner.owner_nonce
          || current.runtime_identity !== context.installed.runtime_identity) reject("OWNER_MISMATCH", 4);
    } });
  const executor = new ManagerExecutor({ manager, backend, store, pi, context: getContext });
  const bridge = new ManagedBridge({ owner, store, executor, resolve: (descriptor, options) => backend.resolve(descriptor, options),
    runtime: { identity: context.installed.runtime_identity, slice_identity: context.installed.slice_identity, capabilities: backend.capabilities },
    listeners: () => listenerCount(pi.events) });
  backend.bindBridge(bridge, owner);
  const off = registerManagedRpc(pi.events, bridge);
  const entry = Object.freeze({ manager, bridge, external, pi, getContext, available: true });
  (globalThis as any)[BRIDGE_KEY] = entry;
  return async () => {
    off(); await closeExternal();
    if ((globalThis as any)[BRIDGE_KEY] === entry) delete (globalThis as any)[BRIDGE_KEY];
    await store.close();
    backend.unbindBridge(bridge);
  };
}
