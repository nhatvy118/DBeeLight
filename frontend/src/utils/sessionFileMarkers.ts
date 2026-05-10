/**
 * Markers persisted with chat history for session files stored under `file_handle/{user}/{session}/import/`.
 */

export type SessionFileAttachment = { name: string; fileId?: string };

/** One block per file (same order as upload / send). */
export function buildSessionFilePayloadPrefix(files: { id: string; filename: string }[]): string {
  if (!files.length) return '';
  return files
    .map(
      (f) =>
        `[SESSION_FILE_ID_START]${f.id}[SESSION_FILE_ID_END]\n[UPLOADED_EXCEL_NAME_START]${f.filename}[UPLOADED_EXCEL_NAME_END]`,
    )
    .join('\n');
}

/** Full body for POST /api/chat: markers + user text (persisted in session). */
export function buildChatMessageWithSessionFiles(
  userText: string,
  files: { id: string; filename: string }[],
): string {
  const t = (userText || '').trim();
  const prefix = buildSessionFilePayloadPrefix(files);
  if (!prefix) return t;
  return t ? `${prefix}\n\n${t}` : prefix;
}

export function extractSessionFileAttachments(text: string): SessionFileAttachment[] | undefined {
  if (!text) return undefined;
  const out: SessionFileAttachment[] = [];
  const pairRe =
    /\[SESSION_FILE_ID_START\]([\s\S]*?)\[SESSION_FILE_ID_END\]\s*\n?\s*\[UPLOADED_EXCEL_NAME_START\]([\s\S]*?)\[UPLOADED_EXCEL_NAME_END\]/g;
  let m: RegExpExecArray | null;
  while ((m = pairRe.exec(text)) !== null) {
    const id = (m[1] || '').trim();
    const name = (m[2] || '').trim();
    if (name) out.push({ name, fileId: id || undefined });
  }
  if (out.length > 0) return out;

  const idMatch = /\[SESSION_FILE_ID_START\]([\s\S]*?)\[SESSION_FILE_ID_END\]/.exec(text);
  const fileId = idMatch?.[1]?.trim() || undefined;
  const re = /\[UPLOADED_EXCEL_NAME_START\]([\s\S]*?)\[UPLOADED_EXCEL_NAME_END\]/g;
  let idx = 0;
  while ((m = re.exec(text)) !== null) {
    const name = (m[1] || '').trim();
    if (name) {
      out.push({ name, fileId: idx === 0 ? fileId : undefined });
      idx += 1;
    }
  }
  return out.length > 0 ? out : undefined;
}

/** Removes session file id + display name markers (not path markers). */
export function stripSessionFileMarkers(text: string): string {
  return (text || '')
    .replace(/\n?\[SESSION_FILE_ID_START\][\s\S]*?\[SESSION_FILE_ID_END\]\n?/g, '\n')
    .replace(/\n?\[UPLOADED_EXCEL_NAME_START\][\s\S]*?\[UPLOADED_EXCEL_NAME_END\]\n?/g, '\n');
}
