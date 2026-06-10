import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const root = fileURLToPath(new URL("..", import.meta.url));

for (const path of [
  "schemas/agent-cli-card.schema.json",
  "schemas/run-receipt.schema.json",
  "fixtures/agent-cli-card.valid.json",
  "fixtures/run-receipt.valid.json",
]) {
  JSON.parse(readFileSync(join(root, path), "utf8"));
}

const types = readFileSync(join(root, "ts/index.ts"), "utf8");
for (const required of ["AgentCliCard", "RunReceipt", "AgentCliCommand", "RunReceiptArtifact"]) {
  if (!types.includes(required)) {
    throw new Error(`missing TypeScript export: ${required}`);
  }
}

console.log("agent-cli-contract static check ok");
