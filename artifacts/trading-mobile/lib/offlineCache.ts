import AsyncStorage from "@react-native-async-storage/async-storage";
import { useEffect, useRef, useState } from "react";

const PREFIX = "offline_snapshot:";

interface Snapshot<T> {
  data: T;
  ts: number;
}

async function readSnapshot<T>(key: string): Promise<Snapshot<T> | null> {
  try {
    const raw = await AsyncStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Snapshot<T>;
    if (parsed == null || typeof parsed.ts !== "number") return null;
    return parsed;
  } catch {
    return null;
  }
}

async function writeSnapshot<T>(key: string, data: T): Promise<void> {
  try {
    await AsyncStorage.setItem(PREFIX + key, JSON.stringify({ data, ts: Date.now() }));
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
export function useOfflineSnapshot<T>(
  key: string,
  liveData: T | undefined,
  isError: boolean,
  dataUpdatedAt?: number,
): { data: T | undefined; isStale: boolean; staleTs: number | null } {
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
      void writeSnapshot(key, liveData);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveData, isError, key]);

  if (!isError && liveData !== undefined) {
    return { data: liveData, isStale: false, staleTs: null };
  }

  // Server unreachable: fall back to in-memory query data first, then the persisted snapshot.
  if (isError) {
    if (liveData !== undefined) {
      const ts = dataUpdatedAt && dataUpdatedAt > 0 ? dataUpdatedAt : snapshot?.ts ?? null;
      return { data: liveData, isStale: true, staleTs: ts };
    }
    if (snapshot) {
      return { data: snapshot.data, isStale: true, staleTs: snapshot.ts };
    }
    return { data: undefined, isStale: true, staleTs: null };
  }

  return { data: liveData, isStale: false, staleTs: null };
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
