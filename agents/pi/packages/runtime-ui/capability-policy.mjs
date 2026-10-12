// 仅所选UI历史变换门槛；不授予工具权限，不访问SDK或任何控制器。
export function mayTransformHistory(runtime) {
  return runtime?.owner?.role === "manager" && !runtime.managedRequestScope?.getStore();
}
