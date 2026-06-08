import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize, relative } from "node:path";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(dirname(fileURLToPath(import.meta.url))), "src");
const host = process.env.CBN_DASHBOARD_HOST || "127.0.0.1";
const port = Number(process.env.CBN_DASHBOARD_PORT || "5173");

const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
};

function resolvePath(urlPath) {
  const requested = urlPath === "/" ? "/index.html" : urlPath;
  const normalized = normalize(decodeURIComponent(requested).replace(/^[/\\]+/, ""));
  return join(root, normalized);
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url || "/", `http://${host}:${port}`);
    const filePath = resolvePath(url.pathname);
    const relativePath = relative(root, filePath);
    if (relativePath.startsWith("..") || relativePath === "" || relativePath.includes(":")) {
      response.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Forbidden");
      return;
    }
    const body = await readFile(filePath);
    response.writeHead(200, {
      "Content-Type": contentTypes[extname(filePath)] || "application/octet-stream",
      "Cache-Control": "no-store",
    });
    response.end(body);
  } catch {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Not found");
  }
});

server.listen(port, host, () => {
  console.log(`CBN Console listening on http://${host}:${port}`);
});
