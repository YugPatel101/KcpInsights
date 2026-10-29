"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { api, errorMessage } from "@/lib/api";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  /** true while a background refresh runs and older data is still shown */
  refreshing: boolean;
  reload: () => void;
  setData: (d: T | null) => void;
}

interface Settled<T> {
  key: string | null;
  data: T | null;
  error: string | null;
}

export interface UseApiOptions {
  /** poll interval while the tab is visible; omit for no polling */
  refreshMs?: number;
}

// One in-flight request per URL: components polling the same endpoint share it.
const inflight = new Map<string, Promise<unknown>>();

export function fetchShared<T>(url: string): Promise<T> {
  const existing = inflight.get(url);
  if (existing) return existing as Promise<T>;
  const p = api<T>(url).finally(() => inflight.delete(url));
  inflight.set(url, p);
  return p;
}

function subscribeVisibility(cb: () => void) {
  document.addEventListener("visibilitychange", cb);
  window.addEventListener("focus", cb);
  return () => {
    document.removeEventListener("visibilitychange", cb);
    window.removeEventListener("focus", cb);
  };
}

/** Page visibility as a store; the server snapshot assumes visible. */
export function usePageVisible(): boolean {
  return useSyncExternalStore(subscribeVisibility, () => document.visibilityState === "visible", () => true);
}

/** GET a resource; refetches when the URL changes, optionally polls while visible, and
 *  revalidates when the tab becomes visible again. Pass null to skip.
 *  Polling reads the KcpInsights database only — it never triggers an upstream fetch. */
export function useApi<T>(url: string | null, opts: UseApiOptions = {}): ApiState<T> {
  const [tick, setTick] = useState(0);
  const visible = usePageVisible();
  const key = url === null ? null : `${tick}:${url}`;
  const [state, setState] = useState<Settled<T>>({ key: null, data: null, error: null });

  useEffect(() => {
    if (url === null || key === null) return;
    let alive = true;
    fetchShared<T>(url)
      .then((d) => {
        if (alive) setState({ key, data: d, error: null });
      })
      .catch((e: unknown) => {
        if (alive) setState((s) => ({ key, data: s.data, error: errorMessage(e) }));
      });
    return () => {
      alive = false;
    };
  }, [url, key]);

  // poll while visible; returning to the tab triggers an immediate revalidation
  useEffect(() => {
    if (!opts.refreshMs || url === null || !visible) return;
    const id = window.setInterval(() => setTick((t) => t + 1), opts.refreshMs);
    return () => window.clearInterval(id);
  }, [opts.refreshMs, url, visible]);

  const [wasVisible, setWasVisible] = useState(visible);
  if (visible !== wasVisible) {
    setWasVisible(visible);
    if (visible && opts.refreshMs) setTick((t) => t + 1);
  }

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const setData = useCallback((d: T | null) => setState((s) => ({ ...s, data: d })), []);
  const pending = key !== null && state.key !== key;
  return {
    data: state.data,
    error: state.key === key ? state.error : null,
    loading: pending && state.data === null,
    refreshing: pending && state.data !== null,
    reload,
    setData,
  };
}
