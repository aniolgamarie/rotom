// 自有委托对象只包装公开方法；不修改 SDK 实例、原型或私有请求实现。
export function modelFacade(runtime, overrides) {
  const methods = new Map();
  return new Proxy(runtime, {
    get(target, key) {
      if (Object.hasOwn(overrides, key)) return overrides[key];
      const value = Reflect.get(target, key, target);
      if (typeof value !== "function") return value;
      if (!methods.has(key)) methods.set(key, value.bind(target));
      return methods.get(key);
    },
    set() { throw new Error("pi-model-facade-readonly"); },
    defineProperty() { throw new Error("pi-model-facade-readonly"); },
    deleteProperty() { throw new Error("pi-model-facade-readonly"); },
  });
}
