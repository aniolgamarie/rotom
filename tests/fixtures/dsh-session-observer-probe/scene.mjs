import { observeBinding } from "./index.mjs";

// 独立接线原型：只使用公开 scene/props；不接入宿主、IPC 或恢复准入。
const installations = new WeakMap();
let nextScene = 0;

export function installObservationScene(ctx, { onObservation, onUnavailable }) {
  let reported = false;
  function report(reason) {
    if (reported) return;
    reported = true;
    try {
      Promise.resolve(onUnavailable(Object.freeze({ kind: "unknown", reason }))).catch(() => {});
    } catch { /* 消费者错误不能逃逸到宿主。 */ }
  }
  if (installations.has(ctx)) {
    report("duplicate-installation");
    return Object.freeze({ close() {}, dispose() {} });
  }
  const id = `rotom-session-observer-${++nextScene}`;
  let scenes;
  let unregister;
  let unsubscribeScenes;
  let ended = false;
  let opened = false;
  let foregroundSeen = false;
  let firstChannel;
  let mountedOnce = false;
  let mount;

  function end(reason) {
    if (ended) return;
    ended = true;
    installations.delete(ctx);
    let cleanupFailed = false;
    const attempt = fn => {
      try { fn?.(); } catch { cleanupFailed = true; }
    };
    const currentMount = mount;
    mount = undefined;
    attempt(() => currentMount?.stop());
    attempt(unsubscribeScenes);
    // active 是公开的当前场景；不能因为迟到 close 而关闭别人的场景。
    attempt(() => { if (scenes?.active?.id === id) scenes.close(); });
    attempt(unregister);
    if (reason || cleanupFailed) report(reason ?? "cleanup-failed");
  }

  const control = Object.freeze({
    close() { end(foregroundSeen ? undefined : "closed-before-observation"); },
    dispose() { end("scene-disposed"); },
  });
  installations.set(ctx, control);

  function attach(channel) {
    if (ended) return () => {};
    if (mountedOnce) {
      end(channel !== firstChannel ? "channel-changed" : "multiple-mounts");
      return () => {};
    }
    mountedOnce = true;
    firstChannel = channel;
    const current = { stop: undefined };
    mount = current;
    try {
      current.stop = observeBinding(channel, value => {
        if (ended || mount !== current) return;
        if (value.kind === "foreground-observed") foregroundSeen = true;
        try {
          Promise.resolve(onObservation(value)).catch(() => end("callback-failed"));
        } catch { end("callback-failed"); return; }
        if (value.kind === "unknown") end("observation-unavailable");
      });
    } catch {
      end("observation-unavailable");
    }
    return () => {
      if (mount !== current) return;
      mount = undefined;
      try { current.stop?.(); } catch { end("cleanup-failed"); return; }
      // effect 依赖变更会先 cleanup 再 attach；让新 attach 报精确 channel 变更。
      queueMicrotask(() => { if (!ended) end("scene-unmounted"); });
    };
  }

  function ObservationScene(props) {
    props.React.useEffect(() => attach(props.channel), [props.channel]);
    return props.React.createElement(props.ui.Text, null, "正在核对会话…");
  }

  try {
    scenes = ctx.tuiScenes;
    unregister = scenes.register({ id, title: "会话观察原型", component: ObservationScene });
    if (typeof unregister !== "function") throw Error("invalid scene registration");
  } catch {
    end("registration-failed");
    return control;
  }
  try {
    ctx.effect(() => control.dispose);
    if (ended) return control;
    unsubscribeScenes = scenes.subscribe(() => {
      if (ended || !opened) return;
      try { if (scenes.active?.id !== id) end("scene-replaced"); } catch { end("scene-unavailable"); }
    });
    if (typeof unsubscribeScenes !== "function") throw Error("invalid scene subscription");
  } catch {
    end("installation-failed");
    return control;
  }
  try {
    if (!scenes.open(id) || scenes.active?.id !== id) {
      end("open-failed");
    } else {
      opened = true;
    }
  } catch {
    end("open-failed");
  }
  return control;
}
