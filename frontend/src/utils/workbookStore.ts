/** Client-side store for ephemeral workbooks (the server keeps NOTHING between excel
 *  turns — see docs/superpowers/plans/2026-07-07-stateless-excel-editing.md).
 *  Key = `${sessionId}/${filename}`; only the latest version per key is kept.
 *  Files are ≤ ~2 MB so IndexedDB pressure is negligible. */

const DB_NAME = 'dbeelight-workbooks';
const STORE = 'workbooks';

type WorkbookRow = {
  key: string;
  sessionId: string;
  filename: string;
  blob: Blob;
  updatedAt: number;
};

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'key' }).createIndex('bySession', 'sessionId');
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx<T>(mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(STORE, mode);
        const req = run(t.objectStore(STORE));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
        t.oncomplete = () => db.close();
      }),
  );
}

export async function putWorkbook(sessionId: string, filename: string, blob: Blob): Promise<void> {
  const row: WorkbookRow = {
    key: `${sessionId}/${filename}`,
    sessionId,
    filename,
    blob,
    updatedAt: Date.now(),
  };
  await tx('readwrite', (s) => s.put(row));
}

export async function getWorkbook(sessionId: string, filename: string): Promise<Blob | null> {
  const row = await tx<WorkbookRow | undefined>('readonly', (s) => s.get(`${sessionId}/${filename}`));
  return row?.blob ?? null;
}

export async function listWorkbooks(
  sessionId: string,
): Promise<{ filename: string; updatedAt: number }[]> {
  const rows = await tx<WorkbookRow[]>('readonly', (s) =>
    s.index('bySession').getAll(sessionId) as IDBRequest<WorkbookRow[]>,
  );
  return rows.map((r) => ({ filename: r.filename, updatedAt: r.updatedAt }));
}

export async function deleteWorkbook(sessionId: string, filename: string): Promise<void> {
  await tx('readwrite', (s) => s.delete(`${sessionId}/${filename}`));
}

/** Decode a (possibly data-URL-prefixed) base64 string into an xlsx Blob. */
export function base64ToBlob(b64: string): Blob {
  const bin = atob(b64.replace(/^data:[^,]*,/, ''));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
}

/** Trigger a browser download for a stored workbook blob. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
