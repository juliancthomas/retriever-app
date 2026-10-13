export interface Citation {
    citation_chunk_id: string;
    document_id: string;
    document_name: string;
    page_number: number;
    quote_text: string;
    relevance_score?: number;
    metadata: any
}