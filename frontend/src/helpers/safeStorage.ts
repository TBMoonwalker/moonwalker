/**
 * Safe text and JSON access to browser storage.
 *
 * Storage is not always available or writable: private mode, a locked-down
 * profile, a blocked cookie policy, a full quota, or a non-browser context can
 * all make a `localStorage` read or write throw. Every call here degrades to a
 * no-op instead of throwing, which is why the callers can wrap their persistence
 * without their own try/catch.
 *
 * Resolve storage inside the guard: accessing localStorage itself can throw.
 * Callers with an injected window can supply a resolver without changing their
 * stored text format or falling back to another window's storage.
 */

export type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">
type StorageProvider = () => StorageLike | null

function browserStorage(): StorageLike | null {
  return typeof localStorage === "undefined" ? null : localStorage
}

/** Read literal text, or null when storage is missing or blocked. */
export function readText(
  key: string,
  storage: StorageProvider = browserStorage,
): string | null {
  try {
    return storage()?.getItem(key) ?? null
  } catch {
    return null
  }
}

/** Store literal text; a blocked write leaves the in-memory choice usable. */
export function writeText(
  key: string,
  value: string,
  storage: StorageProvider = browserStorage,
): void {
  try {
    storage()?.setItem(key, value)
  } catch {
    // Storage access and quota failures must not interrupt the caller.
  }
}

/** Read and `JSON.parse` a value under `key`, or `null` if missing/blocked/corrupt. */
export function readJSON<T>(key: string): T | null {
  try {
    const raw = readText(key)
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
    writeText(key, JSON.stringify(value))
  } catch {
    // Blocked/locked profile or quota exceeded: degrade to an in-memory no-op.
  }
}

/** Remove `key` from storage; no-op if storage is unavailable. */
export function removeJSON(
  key: string,
  storage: StorageProvider = browserStorage,
): void {
  try {
    storage()?.removeItem(key)
  } catch {
    // Blocked profile: a failed clear must never surface to the caller.
  }
}
