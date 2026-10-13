import {
  useQuery,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { jsonStringifyBigintCompatible } from "../helpers/jsonStringifyBigintCompatible";
import { capitalize, uncapitalize } from "../helpers/capitlize";

export type QueryAliased<
  ModelName extends string,
  TData = unknown,
  TError = unknown,
> = Omit<
  UseQueryResult<TData, TError>,
  "data" | "dataUpdatedAt" | "isPlaceholderData"
> & {
  [K in Uncapitalize<ModelName>]: TData;
} & {
  [K in `${Uncapitalize<ModelName>}UpdatedAt`]: number;
} & {
  [K in `isPlaceholder${Capitalize<ModelName>}`]: boolean;
};

export const useQueryAliased = <
  ModelName extends string,
  TQueryFnData = unknown,
  TError = unknown,
  TData = TQueryFnData,
  TQueryKey extends readonly unknown[] = readonly unknown[],
>(
  modelName: ModelName,
  options: UseQueryOptions<TQueryFnData, TError, TData, TQueryKey>
): QueryAliased<ModelName, TData, TError> => {
  const result = useQuery<TQueryFnData, TError, TData, TQueryKey>({
    queryKeyHashFn: jsonStringifyBigintCompatible,
    refetchOnWindowFocus: false,
    staleTime: 2 * 60 * 1000,
    ...options,
  });

  const {
    data,
    dataUpdatedAt,
    isPlaceholderData,
    ...rest
  } = result;

  return {
    ...rest,
    [uncapitalize(modelName)]: data,
    [`${uncapitalize(modelName)}UpdatedAt`]: dataUpdatedAt,
    [`isPlaceholder${capitalize(modelName)}`]: isPlaceholderData,
  } as QueryAliased<ModelName, TData, TError>;
};