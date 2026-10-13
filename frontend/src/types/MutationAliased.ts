import type { UseMutationResult } from '@tanstack/react-query';
import type { PickRenameMultiple } from './PickRenameMultiple';
import type { MutationType } from './MutationType';

export type MutationAliased<
  M extends MutationType,
  ModelName extends string,
  TData = unknown,
  TError = unknown,
  TVariables = void,
  TContext = unknown,
> = M extends 'create'
  ? CreateMutationAliased<ModelName, TData, TError, TVariables, TContext>
  : M extends 'update'
    ? UpdateMutationAliased<ModelName, TData, TError, TVariables, TContext>
    : M extends 'delete'
      ? DeleteMutationAliased<ModelName, TData, TError, TVariables, TContext>
      : RenewMutationAliased<ModelName, TData, TError, TVariables, TContext>;

export type CreateMutationAliased<
  ModelName extends string,
  TData = unknown,
  TError = unknown,
  TVariables = void,
  TOnMutateResult = unknown,
> = PickRenameMultiple<
  UseMutationResult<TData, TError, TVariables, TOnMutateResult>,
  {
    data: `created${Capitalize<ModelName>}`;
    error: 'createError';
    isError: 'createIsError';
    isIdle: 'createIsIdle';
    isPending: 'createIsPending';
    isSuccess: 'createIsSuccess';
    isPaused: 'createIsPaused';
    status: 'createStatus';
    variables: 'createVariables';
    mutate: `create${Capitalize<ModelName>}`;
    mutateAsync: `create${Capitalize<ModelName>}Async`;
    reset: 'createReset';
    context: 'createContext';
    failureCount: 'createFailureCount';
    failureReason: 'createFailureReason';
    submittedAt: 'createSubmittedAt';
  }
>;

export type UpdateMutationAliased<
  ModelName extends string,
  TData = unknown,
  TError = unknown,
  TVariables = void,
  TOnMutateResult = unknown,
> = PickRenameMultiple<
  UseMutationResult<TData, TError, TVariables, TOnMutateResult>,
  {
    data: `updated${Capitalize<ModelName>}`;
    error: 'updateError';
    isError: 'updateIsError';
    isIdle: 'updateIsIdle';
    isPending: 'updateIsPending';
    isSuccess: 'updateIsSuccess';
    isPaused: 'updateIsPaused';
    status: 'updateStatus';
    variables: 'updateVariables';
    mutate: `update${Capitalize<ModelName>}`;
    mutateAsync: `update${Capitalize<ModelName>}Async`;
    reset: 'updateReset';
    context: 'updateContext';
    failureCount: 'updateFailureCount';
    failureReason: 'updateFailureReason';
    submittedAt: 'updateSubmittedAt';
  }
>;

export type DeleteMutationAliased<
  ModelName extends string,
  TData = unknown,
  TError = unknown,
  TVariables = void,
  TOnMutateResult = unknown,
> = PickRenameMultiple<
  UseMutationResult<TData, TError, TVariables, TOnMutateResult>,
  {
    data: `deleted${Capitalize<ModelName>}`;
    error: 'deleteError';
    isError: 'deleteIsError';
    isIdle: 'deleteIsIdle';
    isPending: 'deleteIsPending';
    isSuccess: 'deleteIsSuccess';
    isPaused: 'deleteIsPaused';
    status: 'deleteStatus';
    variables: 'deleteVariables';
    mutate: `delete${Capitalize<ModelName>}`;
    mutateAsync: `delete${Capitalize<ModelName>}Async`;
    reset: 'deleteReset';
    context: 'deleteContext';
    failureCount: 'deleteFailureCount';
    failureReason: 'deleteFailureReason';
    submittedAt: 'deleteSubmittedAt';
  }
>;

export type RenewMutationAliased<
  ModelName extends string,
  TData = unknown,
  TError = unknown,
  TVariables = void,
  TOnMutateResult = unknown,
> = PickRenameMultiple<
  UseMutationResult<TData, TError, TVariables, TOnMutateResult>,
  {
    data: `renewed${Capitalize<ModelName>}`;
    error: 'renewError';
    isError: 'renewIsError';
    isIdle: 'renewIsIdle';
    isPending: 'renewIsPending';
    isSuccess: 'renewIsSuccess';
    isPaused: 'renewIsPaused';
    status: 'renewStatus';
    variables: 'renewVariables';
    mutate: `renew${Capitalize<ModelName>}`;
    mutateAsync: `renew${Capitalize<ModelName>}Async`;
    reset: 'renewReset';
    context: 'renewContext';
    failureCount: 'renewFailureCount';
    failureReason: 'renewFailureReason';
    submittedAt: 'renewSubmittedAt';
  }
>;