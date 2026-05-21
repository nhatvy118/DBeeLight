/**
 * AES-GCM encryption for sensitive values stored in localStorage.
 * The key is generated once per browser and stored in localStorage under `_dbk`.
 * This prevents casual plaintext exposure while allowing auto-reconnect on page reload.
 */

const KEY_STORAGE = '_dbk';
const ALGO = { name: 'AES-GCM', length: 256 };

async function getOrCreateKey(): Promise<CryptoKey> {
  const stored = localStorage.getItem(KEY_STORAGE);
  if (stored) {
    const raw = Uint8Array.from(atob(stored), (c) => c.charCodeAt(0));
    return crypto.subtle.importKey('raw', raw, ALGO, false, ['encrypt', 'decrypt']);
  }
  const key = await crypto.subtle.generateKey(ALGO, true, ['encrypt', 'decrypt']);
  const raw = await crypto.subtle.exportKey('raw', key);
  localStorage.setItem(KEY_STORAGE, btoa(String.fromCharCode(...new Uint8Array(raw))));
  return key;
}

/** Encrypt a plaintext string → base64(iv + ciphertext) */
export async function encryptPassword(plain: string): Promise<string> {
  const key = await getOrCreateKey();
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encoded = new TextEncoder().encode(plain);
  const cipher = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
  const combined = new Uint8Array(iv.byteLength + cipher.byteLength);
  combined.set(iv, 0);
  combined.set(new Uint8Array(cipher), iv.byteLength);
  return btoa(String.fromCharCode(...combined));
}

/** Decrypt base64(iv + ciphertext) → plaintext string */
export async function decryptPassword(cipher: string): Promise<string> {
  const key = await getOrCreateKey();
  const combined = Uint8Array.from(atob(cipher), (c) => c.charCodeAt(0));
  const iv = combined.slice(0, 12);
  const data = combined.slice(12);
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, data);
  return new TextDecoder().decode(plain);
}
