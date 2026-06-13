const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("__cbnApp", {
  getState: () => ipcRenderer.invoke("cbn-app:get-state"),
  getWindowState: () => ipcRenderer.invoke("cbn-app:get-window-state"),
  minimizeWindow: () => ipcRenderer.invoke("cbn-app:minimize-window"),
  toggleMaximizeWindow: () => ipcRenderer.invoke("cbn-app:toggle-maximize-window"),
  closeWindow: () => ipcRenderer.invoke("cbn-app:close-window"),
  openExternal: (url) => ipcRenderer.invoke("cbn-app:open-external", url),
  relaunchDaemon: () => ipcRenderer.invoke("cbn-app:relaunch-daemon"),
  onWindowStateChange: (callback) => {
    if (typeof callback !== "function") return () => {};
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("cbn-app:window-state", listener);
    return () => ipcRenderer.removeListener("cbn-app:window-state", listener);
  },
});
