import { reviewWithFallback } from "./reviewer";
import { handleSessionCommand } from "./session-commands";
export { handleSessionCommand, PERMISSION_USAGE, type CommandServices } from "./session-commands";

export interface PermissionRegistration {
  pluginId: "omp-permission-control";
  bridgeAbi: "permission-control/v1";
  review: typeof reviewWithFallback;
  command: typeof handleSessionCommand;
}
export interface PermissionExtensionAPI {
  /** 宿主把调用者真实加载路径、受管树摘要和运行身份绑定到注册。 */
  registerPermissionController(registration: Readonly<PermissionRegistration>): void;
}

export default function permissionControl(api: PermissionExtensionAPI): void {
  if (!api || typeof api.registerPermissionController !== "function")
    throw new Error("PERMISSION_CONTROLLER_UNAVAILABLE");
  api.registerPermissionController(Object.freeze({ pluginId: "omp-permission-control",
    bridgeAbi: "permission-control/v1", review: reviewWithFallback, command: handleSessionCommand }));
}
