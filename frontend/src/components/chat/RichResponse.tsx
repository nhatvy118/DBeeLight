/**
 * Rich rendering for assistant answers — ported visual treatment from the
 * Chat/ design prototype (chat.jsx). Two pieces:
 *
 *   • CodeBlockCard  — replaces the default markdown code block. SQL fences
 *     render as the on-theme "Query executed" / "SQL query" card (green or
 *     honey header + Copy), matching the reference SqlPreview look. Other
 *     languages get the same card chrome with a neutral language label.
 *
 *   • ResultTableCard — wraps a markdown result table in a card with a
 *     Table / Chart segmented toggle, an "Export to Excel" button and a
 *     "Returned N rows" footer (reference ResultCard).
 *
 * Both are driven entirely off the markdown the backend already sends — no
 * API changes. ResultTableCard reads the raw cell text from the hast `node`
 * react-markdown hands each component, so the chart and export work without
 * a structured rows/columns payload.
 */
import { useState } from 'react';
import { Icons } from '../../icons';

/* ----------------------------- helpers ----------------------------- */

/** Flatten a hast node to its text content. */
function hastText(node: any): string {
  if (!node) return '';
  if (node.type === 'text') return node.value || '';
  if (Array.isArray(node.children)) return node.children.map(hastText).join('');
  return '';
}

export type TableData = { columns: string[]; rows: string[][] };

/** Pull {columns, rows} out of a markdown-table hast node. */
export function extractTableData(node: any): TableData {
  const columns: string[] = [];
  const rows: string[][] = [];
  const kids = (n: any): any[] => (n && Array.isArray(n.children) ? n.children : []);
  const find = (n: any, name: string) => kids(n).find((c) => c.tagName === name);
  const all = (n: any, ...names: string[]) => kids(n).filter((c) => names.includes(c.tagName));

  const thead = find(node, 'thead');
  const headRow = thead ? find(thead, 'tr') : undefined;
  if (headRow) for (const th of all(headRow, 'th', 'td')) columns.push(hastText(th).trim());

  const tbody = find(node, 'tbody');
  for (const tr of all(tbody, 'tr')) {
    rows.push(all(tr, 'td', 'th').map((c) => hastText(c).trim()));
  }
  return { columns, rows };
}

function isNumericValue(s: string): boolean {
  if (s == null) return false;
  const cleaned = s.replace(/[$,%\s]/g, '').replace(/^\((.*)\)$/, '-$1');
  return cleaned !== '' && cleaned !== '-' && Number.isFinite(Number(cleaned));
}

function columnIsNumeric(rows: string[][], ci: number): boolean {
  const vals = rows.map((r) => r[ci]).filter((v) => v != null && v !== '');
  if (!vals.length) return false;
  return vals.filter(isNumericValue).length >= Math.ceil(vals.length * 0.7);
}

/* --------------------------- copy button --------------------------- */

function CopyButton({ text, small }: { text: string; small?: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };
  const Ic = copied ? Icons.Check : Icons.Copy;
  return (
    <button
      type="button"
      onClick={copy}
      className="focusable"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        fontSize: small ? 12 : 12.5, fontWeight: 600,
        color: copied ? 'var(--green-ink)' : 'var(--text-soft)',
        padding: '4px 8px', borderRadius: 7, background: 'transparent', border: 'none',
      }}
    >
      <Ic size={small ? 13 : 14} />
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

/* ------------------------- code block card ------------------------- */

const READ_ONLY_RE = /^\s*(SELECT|WITH|SHOW|EXPLAIN|DESCRIBE|DESC|PRAGMA)\b/i;

export function CodeBlockCard({
  language,
  codeString,
  children,
  codeProps,
  executed,
  failed,
}: {
  language: string;
  codeString: string;
  children: React.ReactNode;
  codeProps?: Record<string, unknown>;
  /** Force the green "Query executed" header — set once a gated mutation has
   *  been run successfully, so it matches read-only queries. */
  executed?: boolean;
  /** Red "Query failed" header — set when a gated mutation errored on run. */
  failed?: boolean;
}) {
  const isSql = language === 'sql';
  const readOnly = isSql && READ_ONLY_RE.test(codeString);

  // SQL header reflects run status:
  //   failed   → red "Query failed"
  //   executed → green "Query executed" (read-only SELECTs auto-run; gated
  //              mutations after a successful Execute)
  //   pending  → honey "SQL query"
  const showFailed = isSql && !!failed;
  const showExecuted = isSql && !showFailed && (readOnly || !!executed);
  const RED_INK = 'oklch(0.58 0.2 25)';
  const HeaderIcon = showFailed ? Icons.Close : showExecuted ? Icons.Check : Icons.Code;
  const headerLabel = isSql ? (showFailed ? 'Query failed' : showExecuted ? 'Query executed' : 'SQL query') : language;
  const headerColor = showFailed ? RED_INK : showExecuted ? 'var(--green-ink)' : 'var(--accent-ink)';
  const headerBg = showFailed ? 'oklch(0.62 0.2 25 / 0.13)' : showExecuted ? 'var(--green-soft)' : 'var(--accent-soft)';
  const headerBorder = showFailed ? 'oklch(0.62 0.2 25 / 0.35)' : showExecuted ? 'var(--green-soft)' : 'var(--accent-soft-2)';

  return (
    <div className="not-prose card" style={{ overflow: 'hidden', margin: '12px 0', borderColor: headerBorder }}>
      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 14px', background: headerBg, borderBottom: '1px solid var(--border)',
        }}
      >
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12.5, fontWeight: 700, color: headerColor }}>
          <HeaderIcon size={15} />
          {isSql ? headerLabel : <span style={{ textTransform: 'lowercase', fontFamily: 'var(--font-mono)' }}>{headerLabel}</span>}
        </span>
        <CopyButton text={codeString} small />
      </div>
      <pre
        style={{
          margin: 0, padding: '14px 16px', background: 'var(--surface)', overflowX: 'auto',
          fontFamily: 'var(--font-mono)', fontSize: 13, lineHeight: 1.7, color: 'var(--text-soft)',
        }}
      >
        <code {...codeProps} style={{ background: 'none', border: 'none', padding: 0 }}>
          {children}
        </code>
      </pre>
    </div>
  );
}

/* --------------------------- result table --------------------------- */

function downloadExcel(data: TableData) {
  const esc = (s: string) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const head = `<tr>${data.columns.map((c) => `<th>${esc(c)}</th>`).join('')}</tr>`;
  const body = data.rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('');
  const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40"><head><meta charset="utf-8"></head><body><table border="1">${head}${body}</table></body></html>`;
  const blob = new Blob(['﻿', html], { type: 'application/vnd.ms-excel' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'export.xls';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function ResultTableCard({ node, data: dataProp }: { node?: any; data?: TableData }) {
  // Structured data (from a query_result event) is preferred; otherwise fall back to extracting
  // it from a markdown-table hast node (mutation preview still renders off markdown).
  const data = dataProp ?? extractTableData(node);

  if (!data.columns.length && !data.rows.length) return null;

  const numericCols = data.columns.map((_, ci) => columnIsNumeric(data.rows, ci));

  return (
    <div className="not-prose card" style={{ overflow: 'hidden', margin: '14px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600, color: 'var(--text-soft)' }}>
          <Icons.Table size={14} />Results
        </span>
        <button type="button" onClick={() => downloadExcel(data)} className="btn btn-outline" style={{ padding: '7px 14px', fontSize: 13 }}>
          <Icons.Download size={15} />Export to Excel
        </button>
      </div>

      <div style={{ padding: 0 }}>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                {data.columns.map((c, ci) => (
                  <th key={ci} className={numericCols[ci] ? 'tabular' : ''} style={numericCols[ci] ? { textAlign: 'right' } : undefined}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((cell, ci) => (
                    <td
                      key={ci}
                      className={numericCols[ci] ? 'tabular' : ''}
                      style={{ textAlign: numericCols[ci] ? 'right' : 'left', fontWeight: ci === 0 ? 600 : 400 }}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: 'var(--text-muted)' }}>
        <Icons.Info size={14} />
        {`Returned ${data.rows.length} ${data.rows.length === 1 ? 'row' : 'rows'}`}
      </div>
    </div>
  );
}
