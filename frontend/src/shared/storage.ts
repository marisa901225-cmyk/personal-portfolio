type StorageKind = 'local' | 'session';

const getStorage = (kind: StorageKind): Storage | null => {
  if (typeof window === 'undefined') return null;
  try {
    return kind === 'local' ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
};

export const safeStorage = {
  getItem(kind: StorageKind, key: string): string | null {
    const storage = getStorage(kind);
    if (!storage) return null;
    try {
      return storage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(kind: StorageKind, key: string, value: string): void {
    const storage = getStorage(kind);
    if (!storage) return;
    try {
      storage.setItem(key, value);
    } catch {
      // Storage might be blocked (e.g. in-app browser); ignore.
    }
  },
  removeItem(kind: StorageKind, key: string): void {
    const storage = getStorage(kind);
    if (!storage) return;
    try {
      storage.removeItem(key);
    } catch {
      // Storage might be blocked (e.g. in-app browser); ignore.
    }
  },
};
