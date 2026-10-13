export interface SearchQueryRequest {
  query: string;
  limit?: number;
  offset?: number;
}
const API_BASE_URL = 'http://localhost:8000'; // your FastAPI port

export const QueryDocuments = async (params: SearchQueryRequest | string) => {
  // Normalize parameters into URLSearchParams
  const queryParams = new URLSearchParams(
    typeof params === 'string'
      ? { query: params }
      : (Object.entries(params).filter(([_, v]) => v !== undefined) as [string, string][])
  );

  const response = await fetch(`${API_BASE_URL}/search?${queryParams.toString()}`, {
    method: 'GET',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    const errorDetail = await response.text();
    throw new Error(`Request failed with status ${response.status}: ${errorDetail}`);
  }

  return response.json();
};