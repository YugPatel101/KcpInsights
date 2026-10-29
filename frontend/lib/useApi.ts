"use client";

import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  setData: (d: T | null) => void;
}

interface Settled<T> {
  key: string | null;
  data: T | null;
  error: string | null;
}

/** GET a resource; refetches when the URL changes. Pass null to skip.
 *  Loading is derived (the latest settled request differs from the current one), so the
 *  effect only sets state from async callbacks. Stale data stays visible while reloading. */
export function useApi<T>(url: string | null): ApiState<T> {
  const [tick, setTick] = useState(0);
  const key = url === null ? null : `${tick}:${url}`;
  const [state, setState] = useState<Settled<T>>({ key: null, data: null, error: null });

  useEffect(() => {
    if (url === null || key === null) return;
    const c = new AbortController();
    api<T>(url, { signal: c.signal })
      .then((d) => {
        if (!c.signal.aborted) setState({ key, data: d, error: null });
      })
      .catch((e: unknown) => {
        if (!c.signal.aborted) setState((s) => ({ key, data: s.data, error: errorMessage(e) }));
      });
    return () => c.abort();
  }, [url, key]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const setData = useCallback((d: T | null) => setState((s) => ({ ...s, data: d })), []);
  return {
    data: state.data,
    error: state.key === key ? state.error : null,
    loading: key !== null && state.key !== key,
    reload,
    setData,
  };
}
