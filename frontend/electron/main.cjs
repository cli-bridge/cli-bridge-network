const { app, BrowserWindow, Menu, ipcMain, shell, dialog } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const FRONTEND_DIR = path.resolve(__dirname, "..");
const ROOT_DIR = path.resolve(FRONTEND_DIR, "..");
const RENDERER_DIST = path.join(FRONTEND_DIR, "dist");
const RUNTIME_DIR = path.join(ROOT_DIR, "runtime");
const DAEMON_HOST = process.env.CBN_DAEMON_HOST || "127.0.0.1";
const DAEMON_PORT = Number(process.env.CBN_DAEMON_PORT || 8787);
const DAEMON_URL = process.env.CBN_DAEMON_URL || `http://${DAEMON_HOST}:${DAEMON_PORT}`;
const RENDERER_DEV_URL = process.env.CBN_RENDERER_DEV_URL || "";

let mainWindow = null;
let daemonProcess = null;
let rendererServer = null;
let rendererUrl = "";
let daemonStatus = {
  mode: "unknown",
  url: DAEMON_URL,
  healthy: false,
  message: "daemon not checked",
};

app.enableSandbox();
app.commandLine.appendSwitch(
  "disable-features",
  [
    "AutofillServerCommunication",
    "AutofillProfileCleanup",
    "AutofillAddressProfileSavePrompt",
    "AutofillPaymentCards",
    "SavePasswordBubble",
  ].join(","),
);
app.commandLine.appendSwitch("disable-blink-features", "Autofill");
app.commandLine.appendSwitch("force-color-profile", "srgb");

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

app.on("second-instance", () => {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    void createMainWindow();
  }
});

app.on("before-quit", () => {
  stopRendererServer();
  stopDaemon();
});

ipcMain.handle("cbn-app:get-state", () => ({
  appName: "CLI Bridge Network",
  appVersion: app.getVersion(),
  daemon: daemonStatus,
  daemonUrl: DAEMON_URL,
  rendererUrl,
  isPackaged: app.isPackaged,
  platform: process.platform,
  workspaceRoot: ROOT_DIR,
}));

ipcMain.handle("cbn-app:open-external", async (_event, url) => {
  if (typeof url !== "string" || !/^https?:\/\//i.test(url)) {
    return { ok: false, error: "Only http(s) URLs can be opened externally." };
  }
  await shell.openExternal(url);
  return { ok: true };
});

ipcMain.handle("cbn-app:relaunch-daemon", async () => {
  stopDaemon();
  await ensureDaemon();
  return daemonStatus;
});

ipcMain.handle("cbn-app:get-window-state", () => getWindowState());

ipcMain.handle("cbn-app:minimize-window", () => {
  if (!mainWindow) return getWindowState();
  mainWindow.minimize();
  return getWindowState();
});

ipcMain.handle("cbn-app:toggle-maximize-window", () => {
  if (!mainWindow) return getWindowState();
  if (mainWindow.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow.maximize();
  }
  return getWindowState();
});

ipcMain.handle("cbn-app:close-window", () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.close();
  }
  return { ok: true };
});

app.whenReady()
  .then(async () => {
    Menu.setApplicationMenu(null);
    await ensureRuntimeDir();
    logApp("app ready");
    await ensureDaemon();
    logApp(`daemon ${daemonStatus.mode} healthy=${daemonStatus.healthy} url=${daemonStatus.url}`);
    rendererUrl = await resolveRendererUrl();
    logApp(`renderer ${rendererUrl}`);
    await createMainWindow();
    logApp("main window loaded");
  })
  .catch(async (error) => {
    await dialog.showErrorBox("CLI Bridge Network failed to start", error instanceof Error ? error.stack || error.message : String(error));
    app.quit();
  });

async function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 900,
    minHeight: 620,
    title: "CLI Bridge Network",
    frame: false,
    resizable: true,
    maximizable: true,
    minimizable: true,
    backgroundColor: "#07101a",
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) {
      void shell.openExternal(url);
    }
    return { action: "deny" };
  });

  mainWindow.once("ready-to-show", () => {
    if (!mainWindow) return;
    mainWindow.show();
    mainWindow.focus();
    sendWindowState();
  });

  for (const eventName of ["resize", "move", "maximize", "unmaximize", "restore", "enter-full-screen", "leave-full-screen"]) {
    mainWindow.on(eventName, sendWindowState);
  }

  await mainWindow.loadURL(rendererUrl);
}

function getWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return {
      isMaximized: false,
      isMinimized: false,
      isFullScreen: false,
      bounds: null,
    };
  }
  return {
    isMaximized: mainWindow.isMaximized(),
    isMinimized: mainWindow.isMinimized(),
    isFullScreen: mainWindow.isFullScreen(),
    bounds: mainWindow.getBounds(),
  };
}

function sendWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send("cbn-app:window-state", getWindowState());
}

async function ensureDaemon() {
  if (await isDaemonHealthy()) {
    daemonStatus = {
      mode: "external",
      url: DAEMON_URL,
      healthy: true,
      message: "using existing daemon",
    };
    return;
  }

  const outLog = path.join(RUNTIME_DIR, "frontend-daemon.out.log");
  const errLog = path.join(RUNTIME_DIR, "frontend-daemon.err.log");
  const out = fs.openSync(outLog, "a");
  const err = fs.openSync(errLog, "a");
  const python = process.env.PYTHON || process.env.CBN_PYTHON || "python";
  daemonProcess = spawn(
    python,
    ["-m", "cbn", "daemon", "serve", "--host", DAEMON_HOST, "--port", String(DAEMON_PORT), "--no-session-token"],
    {
      cwd: ROOT_DIR,
      env: {
        ...process.env,
        PYTHONUTF8: "1",
      },
      stdio: ["ignore", out, err],
      windowsHide: true,
    },
  );

  daemonProcess.once("exit", (code, signal) => {
    daemonStatus = {
      mode: "stopped",
      url: DAEMON_URL,
      healthy: false,
      message: `daemon exited with ${code ?? signal ?? "unknown"}`,
    };
  });

  const healthy = await waitForDaemon();
  daemonStatus = {
    mode: "managed",
    url: DAEMON_URL,
    healthy,
    message: healthy ? "managed daemon ready" : `daemon did not become healthy; see ${errLog}`,
  };
}

function stopDaemon() {
  if (!daemonProcess || daemonProcess.killed) return;
  logApp("stopping managed daemon");
  daemonProcess.kill();
  daemonProcess = null;
}

async function waitForDaemon() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (await isDaemonHealthy()) return true;
    await delay(250);
  }
  return false;
}

async function isDaemonHealthy() {
  try {
    const result = await httpRequest(`${DAEMON_URL}/health`, { timeoutMs: 900 });
    return result.statusCode >= 200 && result.statusCode < 300;
  } catch {
    return false;
  }
}

async function resolveRendererUrl() {
  if (RENDERER_DEV_URL) {
    const url = new URL(RENDERER_DEV_URL);
    if (!["127.0.0.1", "localhost"].includes(url.hostname)) {
      throw new Error(`Refusing non-local renderer dev URL: ${RENDERER_DEV_URL}`);
    }
    return RENDERER_DEV_URL.replace(/\/$/, "");
  }
  if (!fs.existsSync(path.join(RENDERER_DIST, "index.html"))) {
    throw new Error(`Workflow Studio renderer is not built: ${RENDERER_DIST}. Run npm --workspace frontend run build first.`);
  }
  return startRendererServer(RENDERER_DIST);
}

async function startRendererServer(rootDir) {
  const server = http.createServer((request, response) => {
    const requestUrl = new URL(request.url || "/", "http://127.0.0.1");
    const pathname = decodeURIComponent(requestUrl.pathname);
    const relativePath = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
    const candidate = path.resolve(rootDir, relativePath);
    const safePath = candidate.startsWith(rootDir) && fs.existsSync(candidate) && fs.statSync(candidate).isFile()
      ? candidate
      : path.join(rootDir, "index.html");
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", contentType(safePath));
    fs.createReadStream(safePath).pipe(response);
  });

  rendererServer = server;
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Failed to allocate renderer server port.");
  }
  return `http://127.0.0.1:${address.port}`;
}

function stopRendererServer() {
  if (!rendererServer) return;
  rendererServer.close();
  rendererServer = null;
}

function httpRequest(url, { timeoutMs }) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, (response) => {
      response.resume();
      response.on("end", () => resolve({ statusCode: response.statusCode || 0 }));
    });
    request.setTimeout(timeoutMs, () => {
      request.destroy(new Error(`timeout requesting ${url}`));
    });
    request.on("error", reject);
  });
}

function contentType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  return {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
  }[ext] || "application/octet-stream";
}

async function ensureRuntimeDir() {
  await fs.promises.mkdir(RUNTIME_DIR, { recursive: true });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function logApp(message) {
  try {
    fs.mkdirSync(RUNTIME_DIR, { recursive: true });
    fs.appendFileSync(
      path.join(RUNTIME_DIR, "frontend.main.log"),
      `[${new Date().toISOString()}] ${message}\n`,
      "utf8",
    );
  } catch {
    // Logging must never block app launch.
  }
}
