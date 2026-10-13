export const jsonStringifyBigintCompatible = (
  obj: Parameters<typeof JSON.stringify>[0],
  space?: number | string
): ReturnType<typeof JSON.stringify> =>
  JSON.stringify(
    obj,
    (_, value) => (typeof value === "bigint" ? value.toString() : value),
    space
  );