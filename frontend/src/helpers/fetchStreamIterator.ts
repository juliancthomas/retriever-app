// Helper to turn the Fetch API stream into an AsyncIterable
export async function* fetchStreamIterator(url: string): AsyncIterable<string> {
  const response = await fetch(url);
  if (!response.body) throw new Error("No response body");

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8"); //
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true }); //
      const lines = buffer.split("\n");
      
      // Save incomplete trailing line back to buffer
      buffer = lines.pop() || ""; 

      for (const line of lines) {
        if (line) yield line;
      }
    }
    if (buffer) yield buffer;
  } finally {
    reader.releaseLock();
  }
}
