import type { QueryAliased } from "../types/QueryAliased";
import { useQueryAliased } from "./useQueryAliased";
import { type RAGResponse } from '../models/RAGResponse'
import { QueryDocuments } from "../services/QueryDocuments";

export const useDocument = (query: string): QueryAliased<'Document', RAGResponse, Error> => {
  const getDocument = useQueryAliased('Document', {
    queryKey: ['document', query],
    queryFn: async (): Promise<RAGResponse> => {
      return await QueryDocuments(query);
    },
    enabled: Boolean(query.trim()),
  });

  return {
    ...getDocument,
  };
};