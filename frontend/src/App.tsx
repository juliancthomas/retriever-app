import React, { useState } from "react";
import { useResponse } from "./composables/useResponse";
import { type Citation as CitationModel } from "./models/Citation";
import { CitationCard  } from "./Citation";

function App() {
  const [searchTerm, setSearchTerm] = useState("");
  const [query, setQuery] = useState("");

  const {
    data: chunks,
    status,
    fetchStatus,
    error,
    isSuccess
  } = useResponse({ query }, { enabled: Boolean(query) });

  // `status === 'success'` triggers on the very first chunk.
  // `fetchStatus === 'fetching'` indicates chunks are still streaming in.
  const isStreaming = fetchStatus === "fetching";

  const citations = (chunks?.filter( chunk => chunk.type === 'citations')?.[0]?.data ?? []) as CitationModel[]
  let fullText = ''

  if(isSuccess){
    chunks?.map(chunk => {
        if(chunk.type === 'token'){
            fullText += chunk.data
        }
    })
  }
  

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchTerm.trim()) {
      setQuery(searchTerm.trim());
    }
  };

  return (
    <div className="max-w-2xl my-4 mx-auto">
      {/* myocardial: {`${isFetched}`} */}
      <form onSubmit={handleSearch} className="flex gap-1">
        <input
          type="text"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Ask a question..."
          style={{ flex: 1, padding: "0.5rem" }}
        />
        <button type="submit" disabled={isStreaming} style={{ padding: "0.5rem 1rem" }}>
          {isStreaming ? "Streaming..." : "Search"}
        </button>
      </form>

      {status === "error" && (
        <div style={{ marginTop: "1rem", color: "red" }}>
          Error: {error instanceof Error ? error.message : "Something went wrong"}
        </div>
      )}

      {status === "pending" && query && (
        <p style={{ marginTop: "1rem", color: "#666" }}>Connecting to stream...</p>
      )}

      {status === "success" && (
        <div style={{ marginTop: "1.5rem" }}>
          {/* Status flag */}
          <div style={{ fontSize: "0.85rem", color: isStreaming ? "#0070f3" : "#28a745" }}>
            {isStreaming ? "● Generating response..." : "✔ Stream complete"}
          </div>

          {/* Any metadata emitted as JSON objects (e.g. status, citations) */}
          <div className="flex flex-col space-y-9">
          {citations.length > 0 && (
            citations.map((citation, index) => {
              return (
                <CitationCard key={index} citation={citation}/>
              )
            })
          )}
          </div>


          {/* Aggregated text response */}
          <div
            style={{
              marginTop: "1rem",
              whiteSpace: "pre-wrap",
              lineHeight: 1.6,
            }}
          >
            {fullText}
            {isStreaming && <span style={{ opacity: 0.6 }}>▌</span>}
          </div>
        </div>
      )}
    </div>
  );
}

export default App