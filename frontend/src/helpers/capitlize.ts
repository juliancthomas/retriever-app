export const uncapitalize = <S extends string>(str: S): Uncapitalize<S> =>
  (str.charAt(0).toLowerCase() + str.slice(1)) as Uncapitalize<S>;

export const capitalize = <S extends string>(str: S): Capitalize<S> =>
  (str.charAt(0).toUpperCase() + str.slice(1)) as Capitalize<S>;