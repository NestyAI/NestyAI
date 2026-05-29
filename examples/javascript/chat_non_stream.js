"use strict";

/**
 * Node 18+ example.
 * Browser usage is similar with fetch(), but you must configure CORS on server.
 */

const baseUrl = (process.env.NESTY_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const apiKey = (process.env.NESTY_API_KEY || "").trim();
const model = (process.env.NESTY_MODEL || "nesty-combined-1.0").trim();

async function main() {
  const headers = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;

  const payload = {
    model,
    messages: [{ role: "user", content: "Write a short intro about NestyAI." }],
    stream: false,
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

  if (!response.ok) {
    const text = await response.text();
    console.error(`[ERROR] status=${response.status}`);
    console.error(text);
    process.exitCode = 1;
    return;
  }

  const data = await response.json();
  const content = data?.choices?.[0]?.message?.content;
  if (typeof content !== "string") {
    console.error("[ERROR] unexpected response shape");
    console.error(JSON.stringify(data, null, 2));
    process.exitCode = 1;
    return;
  }

  console.log(content);
}

main();
