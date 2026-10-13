import type { UseQueryResult } from "@tanstack/react-query";
import type { PickRenameMultiple } from "./PickRenameMultiple";

export type QueryAliased<
  ModelName extends string,
  TData = unknown,
  TError = unknown,
> = PickRenameMultiple<
  UseQueryResult<TData, TError>,
  {
    data: Uncapitalize<ModelName>;
    dataUpdatedAt: `${Uncapitalize<ModelName>}UpdatedAt`;
    isPlaceholderData: `isPlaceholder${Capitalize<ModelName>}`;
  }
>;