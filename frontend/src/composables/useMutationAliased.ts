import { useMutation, type UseMutationOptions } from "@tanstack/react-query";
import type { MutationAliased } from "../types/MutationAliased";
import type { MutationType } from "../types/MutationType";

const PAST_PARTICIPLE_MAP: Record<MutationType, string> = {
  create: "created",
  update: "updated",
  delete: "deleted",
  renew: "renewed",
};

const capitalize = (val: string): string =>
  val.charAt(0).toUpperCase() + val.slice(1);

export const useMutationAliased = <
  ThisMutationType extends MutationType,
  ModelName extends string,
  TData = unknown,
  TError = unknown,
  TVariables = void,
  TContext = unknown,
>(
  mutationType: ThisMutationType,
  modelName: ModelName,
  useMutationOptions: UseMutationOptions<TData, TError, TVariables, TContext>
): MutationAliased<ThisMutationType, ModelName, TData, TError, TVariables, TContext> => {
  const result = useMutation(useMutationOptions);

  const verb = mutationType;
  const capitalizedModel = capitalize(modelName);
  const pastParticiple = PAST_PARTICIPLE_MAP[mutationType];

  const aliasedResult = {
    // Model-scoped keys
    [`${pastParticiple}${capitalizedModel}`]: result.data,
    [`${verb}${capitalizedModel}`]: result.mutate,
    [`${verb}${capitalizedModel}Async`]: result.mutateAsync,

    // Verb-scoped TanStack properties
    [`${verb}Error`]: result.error,
    [`${verb}IsError`]: result.isError,
    [`${verb}IsIdle`]: result.isIdle,
    [`${verb}IsPending`]: result.isPending,
    [`${verb}IsSuccess`]: result.isSuccess,
    [`${verb}IsPaused`]: result.isPaused,
    [`${verb}Status`]: result.status,
    [`${verb}Variables`]: result.variables,
    [`${verb}Reset`]: result.reset,
    [`${verb}Context`]: result.context,
    [`${verb}FailureCount`]: result.failureCount,
    [`${verb}FailureReason`]: result.failureReason,
    [`${verb}SubmittedAt`]: result.submittedAt,
  } as MutationAliased<ThisMutationType, ModelName, TData, TError, TVariables, TContext>;

  return aliasedResult;
};