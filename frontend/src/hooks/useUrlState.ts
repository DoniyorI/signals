import { useCallback } from "react";
import { useSearchParams } from "react-router";

/**
 * One URL search param as typed state (`useSearchParams` under the hood), so every page
 * filter lives in the URL and views stay shareable and reload-safe (plan 07, Global
 * Constraints). Setting a value that serializes the same as `defaultValue` removes the param
 * instead of writing it, so the URL stays clean at the default.
 */
export function useUrlState<T>(
  key: string,
  defaultValue: T,
  parse: (raw: string | null) => T,
  serialize: (value: T) => string | null,
): [T, (value: T) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get(key);
  const value = raw === null ? defaultValue : parse(raw);

  const setValue = useCallback(
    (next: T) => {
      const serialized = serialize(next);
      const atDefault = serialized === null || serialized === serialize(defaultValue);
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (atDefault) {
            params.delete(key);
          } else {
            params.set(key, serialized as string);
          }
          return params;
        },
        { replace: true },
      );
    },
    [key, setSearchParams, serialize, defaultValue],
  );

  return [value, setValue];
}
