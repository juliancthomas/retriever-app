export type PickRenameMultiple<
  T,
  R extends { [K in keyof R]: K extends keyof T ? PropertyKey : "Error: key not in T" },
> = Omit<T, keyof R> & {
  [P in keyof R as R[P] extends PropertyKey ? R[P] : never]: P extends keyof T
    ? T[P]
    : never;
};