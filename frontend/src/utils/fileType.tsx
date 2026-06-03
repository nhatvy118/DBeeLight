/**
 * Maps an uploaded file (by filename extension and/or MIME type) to a visual
 * "kind" — so each file shows its own logo/label instead of a generic Excel one.
 */
import type { CSSProperties } from 'react';

export type FileKind = 'excel' | 'word' | 'pdf' | 'csv' | 'text' | 'sqlite' | 'generic';

type FileKindInfo = {
  /** Short uppercase tag shown inside the badge (the "logo"). */
  badge: string;
  /** Human label shown as the file subtitle. */
  label: string;
  /** Brand color (badge background). */
  color: string;
  /** Emoji fallback for plain-text contexts (e.g. trigger button). */
  emoji: string;
};

const INFO: Record<FileKind, FileKindInfo> = {
  excel:   { badge: 'XLS', label: 'Excel',  color: '#1D6F42', emoji: '📊' },
  word:    { badge: 'DOC', label: 'Word',   color: '#2B579A', emoji: '📝' },
  pdf:     { badge: 'PDF', label: 'PDF',    color: '#D93025', emoji: '📕' },
  csv:     { badge: 'CSV', label: 'CSV',    color: '#0F9D58', emoji: '📄' },
  text:    { badge: 'TXT', label: 'Text',   color: '#5F6368', emoji: '📄' },
  sqlite:  { badge: 'DB',  label: 'SQLite', color: '#0277BD', emoji: '🗄️' },
  generic: { badge: 'FILE', label: 'File',  color: '#5F6368', emoji: '📄' },
};

/** Determine the file kind from its name and/or MIME type. */
export function getFileKind(filename?: string | null, mimeType?: string | null): FileKind {
  const name = (filename || '').toLowerCase();
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.') + 1) : '';
  const mime = (mimeType || '').toLowerCase();

  if (ext === 'xlsx' || ext === 'xls' || mime.includes('excel') || mime.includes('spreadsheet')) return 'excel';
  if (ext === 'doc' || ext === 'docx' || mime.includes('word') || mime.includes('wordprocessing')) return 'word';
  if (ext === 'pdf' || mime.includes('pdf')) return 'pdf';
  if (ext === 'csv' || mime.includes('csv')) return 'csv';
  if (ext === 'db' || ext === 'sqlite' || ext === 'sqlite3' || mime.includes('sqlite')) return 'sqlite';
  if (ext === 'txt' || ext === 'md' || mime.includes('text/plain') || mime.includes('markdown')) return 'text';
  return 'generic';
}

export function getFileKindInfo(kind: FileKind): FileKindInfo {
  return INFO[kind];
}

/** Convenience: short text logo + label + color straight from name/mime. */
export function getFileTypeInfo(filename?: string | null, mimeType?: string | null): FileKindInfo {
  return INFO[getFileKind(filename, mimeType)];
}

type BadgeProps = {
  filename?: string | null;
  mimeType?: string | null;
  /** Square side in px. */
  size?: number;
  /** Corner radius in px. */
  radius?: number;
  style?: CSSProperties;
};

/** Brand-colored square showing the file-type "logo" (XLS / DOC / PDF / …). */
export function FileTypeBadge({ filename, mimeType, size = 30, radius = 7, style }: BadgeProps) {
  const info = getFileTypeInfo(filename, mimeType);
  // Scale the tag text to the badge; clamp so longer tags (FILE) still fit.
  const fontSize = Math.max(7, Math.min(10, Math.round(size * 0.32) - (info.badge.length > 3 ? 1 : 0)));
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        flexShrink: 0,
        display: 'grid',
        placeItems: 'center',
        background: info.color,
        color: '#fff',
        fontSize,
        fontWeight: 800,
        letterSpacing: '.02em',
        lineHeight: 1,
        ...style,
      }}
    >
      {info.badge}
    </span>
  );
}
