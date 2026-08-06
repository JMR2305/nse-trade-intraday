import AsyncStorage from "@react-native-async-storage/async-storage";
import { useEffect, useRef, useState } from "react";

import { decodeSnapshot, encodeSnapshot } from "@/lib/cacheSchema";

const PREFIX = "offline_snapshot:";

interface Snapshot<T> {
  data: T;
  ts: number;
}

async function readSnapshot<T>(key: string): Promise<Snapshot<T> | null> {
  try {
    const raw = await AsyncStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const result = decodeSnapshot<T>(key, raw);
    if (!result.ok) {
      // Incompatible/corrupt/partial record: reject and remove it so the
      // screen shows an explicit unavailable state, never wrong data.
      void AsyncStorage.removeItem(PREFIX + key).catch(() => {});
      return null;
    }
    if (result.migrated) {
      // Re-persist compatible legacy records in the current envelope.
      void AsyncStorage.setItem(PREFIX + key, encodeSnapshot(result.data, result.ts)).catch(() => {});
    }
    return { data: result.data, ts: result.ts };
  } catch {
    return null;
  }
}

/** @internal Exported for unit testing only — use the hook in production code. */
export async function writeSnapshot<T>(key: string, data: T, ts?: number): Promise<void> {
  try {
    await AsyncStorage.setItem(PREFIX + key, encodeSnapshot(data, ts ?? Date.now()));
  } catch {
    // best-effort cache; ignore storage failures
  }
}

/**
 * Keeps a persisted snapshot of the latest successful query data so screens
 * can show stale-but-real data (with its age) when the API server is slow,
 * cold-starting, or offline.
 *
 * Returns the effective data (live if available, otherwise the last snapshot),
 * whether the shown data is stale, and the timestamp it was captured.
 */
export type SnapshotSource = "live" | "memory" | "offline-cache" | "none";

type SelectResult<T> = {
  data: T | undefined;
  isStale: boolean;
  staleTs: number | null;
  source: SnapshotSource;
  dataTs: number | null;
};

/**
 * Pure selection function: given the current query state and the in-memory
 * persisted snapshot, returns which data to display and whether it is stale.
 *
 * Extracted from `useOfflineSnapshot` so it can be unit-tested without a
 * React renderer.
 */
export function selectCacheData<T>(
  liveData: T | undefined,
  isError: boolean,
  snapshot: Snapshot<T> | null,
  dataUpdatedAt?: number,
): SelectResult<T> {
  if (!isError && liveData !== undefined) {
    const ts = dataUpdatedAt && dataUpdatedAt > 0 ? dataUpdatedAt : null;
    return { data: liveData, isStale: false, staleTs: null, source: "live", dataTs: ts };
  }

  if (isError) {
    if (liveData !== undefined) {
      const ts = dataUpdatedAt && dataUpdatedAt > 0 ? dataUpdatedAt : snapshot?.ts ?? null;
      return { data: liveData, isStale: true, staleTs: ts, source: "memory", dataTs: ts };
    }
    if (snapshot) {
      return { data: snapshot.data, isStale: true, staleTs: snapshot.ts, source: "offline-cache", dataTs: snapshot.ts };
    }
    return { data: undefined, isStale: true, staleTs: null, source: "none", dataTs: null };
  }

  // Loading state (liveData === undefined, !isError): serve the persisted snapshot immediately
  // so screens never show a blank spinner on cold-start when the server is slow or offline.
  if (snapshot) {
    return { data: snapshot.data, isStale: true, staleTs: snapshot.ts, source: "offline-cache", dataTs: snapshot.ts };
  }
  return { data: undefined, isStale: false, staleTs: null, source: "none", dataTs: null };
}

export function useOfflineSnapshot<T>(
  key: string,
  liveData: T | undefined,
  isError: boolean,
  dataUpdatedAt?: number,
): { data: T | undefined; isStale: boolean; staleTs: number | null; source: SnapshotSource; dataTs: number | null } {
  const [snapshot, setSnapshot] = useState<Snapshot<T> | null>(null);
  const loadedRef = useRef(false);

  // Load persisted snapshot once on mount (used when the server is down at cold start).
  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    void readSnapshot<T>(key).then((snap) => {
      if (snap) setSnapshot(snap);
    });
  }, [key]);

  // Persist every fresh successful payload.
  useEffect(() => {
    if (liveData !== undefined && !isError) {
      const ts = dataUpdatedAt && dataUpdatedAt > 0 ? dataUpdatedAt : Date.now();
      setSnapshot({ data: liveData, ts });
      void writeSnapshot(key, liveData, ts);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveData, isError, key]);

  return selectCacheData(liveData, isError, snapshot, dataUpdatedAt);
}

export function formatAge(ts: number | null): string {
  if (!ts) return "unknown age";
  const mins = Math.max(0, Math.round((Date.now() - ts) / 60_000));
  if (mins < 1) return "moments ago";
  if (mins === 1) return "1 minute ago";
  if (mins < 60) return `${mins} minutes ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}
