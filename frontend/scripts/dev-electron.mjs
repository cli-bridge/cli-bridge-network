import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import electronPath from "electron";
import { createServer } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(__dirname, "..");
const rootDir = path.resolve(frontendDir, "..");
const runtimeDir = path.join(rootDir, "runtime");

await fs.promises.mkdir(runtimeDir, { recursive: true });
const port = await findFreePort();

const vite = await createServer({
  root: frontendDir,
  appType: "spa",
  clearScreen: false,
  logLevel: "info",
  server: {
    host: "127.0.0.1",
    port,
    strictPort: true,
    hmr: {
      host: "127.0.0.1",
      port,
    },
  },
});

await vite.listen();
vite.printUrls();

const rendererUrl = vite.resolvedUrls?.local?.[0] ?? "";
if (!rendererUrl) {
  throw new Error("Vite did not report a local renderer URL.");
}

const electron = spawn(electronPath, [frontendDir], {
  cwd: frontendDir,
  env: {
    ...process.env,
    CBN_RENDERER_DEV_URL: rendererUrl,
  },
  stdio: "inherit",
  windowsHide: false,
});

let closing = false;

async function shutdown(exitCode = 0) {
  if (closing) return;
  closing = true;
  if (!electron.killed) {
    electron.kill();
  }
  await vite.close();
  process.exit(exitCode);
}

electron.on("exit", async (code, signal) => {
  await vite.close();
  if (signal) {
    process.exit(1);
  }
  process.exit(code ?? 0);
});

process.on("SIGINT", () => {
  void shutdown(0);
});

process.on("SIGTERM", () => {
  void shutdown(0);
});

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => {
        if (!address || typeof address === "string") {
          reject(new Error("Failed to allocate a local Vite dev port."));
          return;
        }
        resolve(address.port);
      });
    });
  });
}
