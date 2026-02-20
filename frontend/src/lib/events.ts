import { API_BASE } from "@/lib/api";
import type { SseEvent } from "@/lib/types";

const EVENT_BASES = Array.from(
  new Set([API_BASE, "http://127.0.0.1:8010", "http://localhost:8010", "http://127.0.0.1:8000", "http://localhost:8000"])
);

type SseStatus = "open" | "close" | "error" | "reconnect";

export function subscribeEvents({
  onEvent,
  onError,
  onStatus,
}: {
  onEvent: (event: SseEvent) => void;
  onError?: () => void;
  onStatus?: (status: SseStatus, detail?: { delayMs?: number; base?: string }) => void;
}) {
  let closed = false;
  let abortController: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let baseIndex = 0;
  let attempts = 0;

  const scheduleReconnect = (delayMs: number) => {
    if (closed) return;
    onStatus?.("reconnect", { delayMs });
    timer = setTimeout(() => {
      void connect();
    }, delayMs);
  };

  const parseSseChunk = (chunk: string) => {
    const lines = chunk.split(/\r?\n/);
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (dataLines.length === 0) return;
    try {
      const event = JSON.parse(dataLines.join("\n")) as SseEvent;
      onEvent(event);
    } catch {
      // ignore malformed payload
    }
  };

  const connect = async () => {
    if (closed) return;
    const base = EVENT_BASES[baseIndex % EVENT_BASES.length];
    const streamUrl = new URL("/events/stream", `${base}/`).toString();
    abortController = new AbortController();

    try {
      const response = await fetch(streamUrl, {
        method: "GET",
        headers: { Accept: "text/event-stream" },
        cache: "no-store",
        signal: abortController.signal,
      });
      if (!response.ok || !response.body) {
        throw new Error(`SSE connect failed: ${response.status}`);
      }
      attempts = 0;
      onStatus?.("open", { base });
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (!closed) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let splitIndex = buffer.search(/\r?\n\r?\n/);
        while (splitIndex >= 0) {
          const chunk = buffer.slice(0, splitIndex);
          buffer = buffer.slice(splitIndex + (buffer[splitIndex] === "\r" ? 4 : 2));
          parseSseChunk(chunk);
          splitIndex = buffer.search(/\r?\n\r?\n/);
        }
      }
      buffer += decoder.decode();
      if (buffer.trim().length > 0) {
        parseSseChunk(buffer);
      }
      if (!closed) {
        onStatus?.("close", { base });
        baseIndex = (baseIndex + 1) % EVENT_BASES.length;
        attempts += 1;
        scheduleReconnect(1200);
      }
    } catch {
      if (closed) return;
      onStatus?.("error", { base });
      baseIndex = (baseIndex + 1) % EVENT_BASES.length;
      attempts += 1;
      if (attempts >= EVENT_BASES.length) {
        onError?.();
        attempts = 0;
      }
      scheduleReconnect(1200);
    } finally {
      abortController = null;
    }
  };

  void connect();

  return () => {
    closed = true;
    if (timer) clearTimeout(timer);
    abortController?.abort();
  };
}
