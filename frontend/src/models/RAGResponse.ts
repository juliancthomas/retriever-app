import { type Citation } from "./Citation";

export interface RAGResponse {
    query: string,
    answer: string,
    citations: Citation[]
}