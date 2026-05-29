"use strict";

/**
 * Node 18+ streaming example with fetch + ReadableStream.
 * Browser note: direct frontend calls require intentional CORS configuration on the server.
 */

const baseUrl = (process.env.NESTY_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const apiKey = (process.env.NESTY_API_KEY || "").trim();
const model = (process.env.NESTY_MODEL || "nesty-combined-1.0").trim();

function parseSseLinesFromBuffer(buffer) {
  const lines = buffer.split(/\r?\n/);
  const tail = lines.pop() || "";
  return { lines, tail };
}

async function main() {
  const headers = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;

  const payload = {
    model,
    messages: [{ role: "user", content: "Write a short intro about NestyAI." }],
    stream: true,
    search: "off",
    tools: "off",
  };

  let response;
  try {
    response = await fetch(`${baseUrl}/v1/chat/completions`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
  } catch (err) {
    console.error("[ERROR] request failed:", err);
    process.exitCode = 1;
    return;
  }

  if (!response.ok || !response.body) {
    const text = await response.text();
    console.error(`[ERROR] status=${response.status}`);
    console.error(text);
    process.exitCode = 1;
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let doneSeen = false;
  let metadata = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseLinesFromBuffer(buffer);
    buffer = parsed.tail;

    for (const line of parsed.lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice("data: ".length).trim();
      if (!raw) continue;

      if (raw === "[DONE]") {
        doneSeen = true;
        break;
      }

      let event;
      try {
        event = JSON.parse(raw);
      } catch {
        continue;
      }

      if (event.object === "chat.completion.chunk") {
        const content = event?.choices?.[0]?.delta?.content;
        if (typeof content === "string" && content.length > 0) {
          process.stdout.write(content);
        }
      } else if (event.object === "chat.completion.metadata") {
        metadata = event;
      } else if (event.object === "chat.completion.error") {
        console.error("\n[STREAM ERROR]", event.error || {});
        process.exitCode = 1;
        return;
      }
    }

    if (doneSeen) break;
  }

  process.stdout.write("\n");
  if (metadata) {
    const provider = metadata.provider || "-";
    const toolsUsed = Array.isArray(metadata?.tools?.used) ? metadata.tools.used.length : 0;
    const sourceCount = Array.isArray(metadata?.sources) ? metadata.sources.length : 0;
    const redactionCount = Number(metadata?.guard?.redaction_count || 0);
    console.log(
      `[METADATA] provider=${provider}, tools_used=${toolsUsed}, sources=${sourceCount}, redactions=${redactionCount}`
    );
  }

  if (!doneSeen) {
    console.error("[ERROR] stream ended without [DONE]");
    process.exitCode = 1;
  }
}

main();
