// 远程 shell 保留会话事实，但不能接收宿主机器的配置目录。
export function remoteShellEnvironment(snapshot) {
  return Object.freeze(Object.fromEntries(Object.entries(snapshot).filter(([key]) =>
    key !== "DSH_HOME" && key !== "DSH_PROFILE_DIR")));
}
