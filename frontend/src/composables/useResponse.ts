import { experimental_streamedQuery } from "@tanstack/react-query";
import { useQueryAliased } from "./useQueryAliased";

export interface SearchQueryRequest {
  query: string;
  limit?: number;
  [key: string]: unknown;
}

export interface StreamEvent {
  token?: string;
  error?: string;
  [key: string]: unknown;
}

/**
 * Async generator that consumes the FastAPI SSE stream
 * and parses each SSE chunk into typed objects.
 */
async function* fetchSearchStream(
  params: SearchQueryRequest,
  signal?: AbortSignal
): AsyncIterable<StreamEvent> {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      searchParams.append(key, String(value));
    }
  }

  const response = await fetch(`/api/v1/search?${searchParams.toString()}`, {
    method: "GET",
    headers: {
      Accept: "text/event-stream",
    },
    signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  if (!response.body) {
    throw new Error("Response body is not readable.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      // Keep the incomplete trailing block in buffer
      buffer = lines.pop() ?? "";

      for (const block of lines) {
        const cleanBlock = block.trim();
        if (!cleanBlock) continue;

        // Check for custom SSE error event
        if (cleanBlock.startsWith("event: error")) {
          const dataLine = cleanBlock.split("\n").find((l) => l.startsWith("data:"));
          const errorPayload = dataLine ? JSON.parse(dataLine.replace(/^data:\s*/, "")) : {};
          throw new Error(errorPayload.error || "Server stream error");
        }

        // Process standard data events
        for (const line of cleanBlock.split("\n")) {
          if (line.startsWith("data:")) {
            const data = line.replace(/^data:\s*/, "").trim();
            if (data === "[DONE]") {
              return;
            }
            yield JSON.parse(data) as StreamEvent;
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

interface UseResponseOptions {
  enabled?: boolean;
}

export function useResponse(payload: SearchQueryRequest, options?: UseResponseOptions) {
  return useQueryAliased('Data', {
    queryKey: ["search", payload],
    queryFn: experimental_streamedQuery<StreamEvent>({
      streamFn: ({ signal }) => fetchSearchStream(payload, signal),
    }),
    enabled: options?.enabled ?? Boolean(payload.query),
  });
}