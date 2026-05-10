/**
 * Assistant responses may embed an Excel file as markers for UI download.
 * Keeps parsing + stripping in one place (Chat, Home, PrintChat).
 */

/** Same shape as ``ExportData`` in ``MessageList.tsx``. */
export type ExcelExportPayload = {
  base64?: string;
  filename?: string;
  rowCount?: number;
  tableName?: string;
  /** Set after server persists export under ``file_handle/{user}/{session}/export/``. */
  sessionFileId?: string;
};

export function extractExportData(text: string): ExcelExportPayload | null {
  const base64Match = text.match(/\[EXCEL_BASE64_START\]([\s\S]*?)\[EXCEL_BASE64_END\]/);
  const fileIdMatch = text.match(/\[EXPORT_FILE_ID_START\]([\s\S]*?)\[EXPORT_FILE_ID_END\]/);
  const filenameMatch = text.match(/\[FILENAME_START\]([\s\S]*?)\[FILENAME_END\]/);
  const rowCountMatch = text.match(/\[ROW_COUNT_START\](\d+)\[ROW_COUNT_END\]/);

  if (base64Match && filenameMatch) {
    return {
      base64: base64Match[1].trim(),
      filename: filenameMatch[1].trim(),
      rowCount: rowCountMatch ? parseInt(rowCountMatch[1], 10) : 0,
    };
  }
  if (fileIdMatch && filenameMatch) {
    return {
      sessionFileId: fileIdMatch[1].trim(),
      filename: filenameMatch[1].trim(),
      rowCount: rowCountMatch ? parseInt(rowCountMatch[1], 10) : 0,
    };
  }
  return null;
}

/** Remove embedded Excel payload from markdown body (base64 must not render). */
export function stripExcelMarkersFromText(text: string): string {
  return (text || '')
    .replace(/\n?\[EXCEL_BASE64_START\][\s\S]*?\[EXCEL_BASE64_END\]\n?/g, '\n')
    .replace(/\n?\[EXPORT_FILE_ID_START\][\s\S]*?\[EXPORT_FILE_ID_END\]\n?/g, '\n')
    .replace(/\n?\[FILENAME_START\][\s\S]*?\[FILENAME_END\]\n?/g, '\n')
    .replace(/\n?\[ROW_COUNT_START\][\s\S]*?\[ROW_COUNT_END\]\n?/g, '\n');
}

/** Saves ``.xlsx`` from markers payload (runs in browser only). */
export function triggerExcelDownload(data: ExcelExportPayload): void {
  const rawB64 = data.base64?.trim();
  const filename = data.filename?.trim() || 'export.xlsx';
  if (!rawB64) throw new Error('No file data in export payload');
  const byteCharacters = atob(rawB64);
  const byteNumbers = new Array(byteCharacters.length);
  for (let i = 0; i < byteCharacters.length; i++) {
    byteNumbers[i] = byteCharacters.charCodeAt(i);
  }
  const byteArray = new Uint8Array(byteNumbers);
  const blob = new Blob([byteArray], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  a.remove();
}
