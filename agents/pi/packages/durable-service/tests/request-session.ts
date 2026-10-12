// 自有公开接口替身：串行 callback、暂存后原子采用，不导入 SDK。
export const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
export const copy = value => value === undefined ? undefined : structuredClone(value);
export function requestSession() {
  const state = { document: undefined, tasks: new Map(), nextId: 10, creates: 0, commits: 0, snapshots: 0, gets: 0, txReads: 0, writes: 0, hooks: {}, token: undefined, context: {} };
  let line = Promise.resolve();
  const assertContext = context => { if (context !== state.context) throw Error("wrong context"); };
  const durable = { defineDoc(definition) { state.token = { definition }; return state.token; } };
  const chord = { copyJson(value) { return copy(value); } };
  class Session {
    async snapshot(token, context) {
      if (this !== session) throw Error("wrong receiver"); assertContext(context); state.snapshots++;
      const result = copy(state.document); if (state.hooks.snapshot) await state.hooks.snapshot(state, result); return result;
    }
    async getTask(id, context) {
      if (this !== session) throw Error("wrong receiver"); assertContext(context); state.gets++;
      if (state.hooks.getTask) await state.hooks.getTask(state, id); return copy(state.tasks.get(id));
    }
    commit(callback, context) {
      if (this !== session) throw Error("wrong receiver"); assertContext(context);
      const job = async () => {
        state.commits++; if (state.hooks.beforeCallback) await state.hooks.beforeCallback(state);
        if (state.hooks.skipCallback) return {};
        let document = copy(state.document), wrote = false;
        const tasks = new Map([...state.tasks].map(([id, task]) => [id, copy(task)]));
        const tx = {
          async doc(token) {
            if (this !== tx) throw Error("wrong receiver");
            if (!document) document = token.definition.initial();
            if (state.hooks.doc) await state.hooks.doc(state);
            // 普通公开 Draft 写入形态，以 Proxy 模拟 SDK 边界；copyJson 替身显式提取。
            return new Proxy(document, {});
          },
          async task(id) {
            if (this !== tx || wrote) throw Error("read after write"); state.txReads++;
            if (state.hooks.task) await state.hooks.task(state, id); return copy(tasks.get(id));
          },
          async createTask(token, input, options) {
            if (this !== tx) throw Error("wrong receiver"); wrote = true; state.creates++;
            const id = state.hooks.nativeId ?? state.nextId++;
            tasks.set(id, { id, conversationId: options.conversationId, kind: token.definition.name, version: token.definition.version, input: copy(input), background: options.background, abortRequested: false, state: { status: "pending" } });
            if (state.hooks.createTask) await state.hooks.createTask(state, id); return id;
          },
        };
        const result = await callback(tx);
        if (state.hooks.beforeAdopt) await state.hooks.beforeAdopt(state);
        state.document = copy(document); state.tasks = tasks; state.writes++;
        if (state.hooks.afterAdopt) await state.hooks.afterAdopt(state);
        return state.hooks.replaceReceipt ? {} : result;
      };
      const result = line.then(job); line = result.catch(() => {}); return result;
    }
  }
  const session = new Session();
  // 本地提取 Draft；不声称真实 Chord Proxy 的一般认证。
  chord.copyJson = value => {
    function extract(value) {
      if (!value || typeof value !== "object") return value;
      if (Array.isArray(value)) return value.map(extract);
      const result = Object.create(null);
      for (const key of Object.keys(value)) result[key] = extract(Object.getOwnPropertyDescriptor(value, key).value);
      return result;
    }
    return extract(value);
  };
  return { state, session, durable, chord };
}
