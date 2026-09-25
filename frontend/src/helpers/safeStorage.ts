/**
 * Safe JSON access to `window.localStorage`.
 *
 * Storage is not always available or writable: private mode, a locked-down
 * profile, a blocked cookie policy, a full quota, or a non-browser context can
 * all make a `localStorage` read or write throw. Every call here degrades to a
 * no-op instead of throwing, which is why the callers can wrap their persistence
 * without their own try/catch.
 *
 * This centralises the guard that `themeStore.ts` and `configSnapshotStore.ts`
 * each inlined for themselves, so web-storage access has a single, tested owner.
 */

/** Read and `JSON.parse` a value under `key`, or `null` if missing/blocked/corrupt. */
export function readJSON<T>(key: string): T | null {
  try {
    if (typeof window === "undefined") {
      return null
    }
    const raw = window.localStorage.getItem(key)
    if (raw === null) {
      return null
    }
    return JSON.parse(raw) as T
  } catch {
    // Blocked storage, a quota error, or a corrupt entry: degrade to a no-op read.
    return null
  }
}

/** `JSON.stringify` and store `value` under `key`; no-op if storage is unavailable. */
export function writeJSON(key: string, value: unknown): void {
  try {
    if (typeof window === "undefined") {
      return
    }
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Blocked/locked profile or quota exceeded: degrade to an in-memory no-op.
  }
}

/** Remove `key` from storage; no-op if storage is unavailable. */
export function removeJSON(key: string): void {
  try {
    if (typeof window === "undefined") {
      return
    }
    window.localStorage.removeItem(key)
  } catch {
    // Blocked profile: a failed clear must never surface to the caller.
  }
}
