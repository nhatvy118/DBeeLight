import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getSession } from '../services/api';

type RawMessage = {
  role: string;
  content?: string;
  timestamp?: string;
};

const INTERNAL_MARKER_PATTERNS: RegExp[] = [
  /\[CREATE_TABLE_SCHEMA_JSON_START\][\s\S]*?\[CREATE_TABLE_SCHEMA_JSON_END\]/g,
  /\[SCHEMA_CONFIRM_INTERNAL_START\][\s\S]*?\[SCHEMA_CONFIRM_INTERNAL_END\]/g,
  // Legacy Superset chart-embed markers — kept here so historical chats
  // with these markers still print clean. Superset itself is gone.
  /\[CHART_EMBED_URL_START\][\s\S]*?\[CHART_EMBED_URL_END\]/g,
  /\[CHART_EMBED_META_START\][\s\S]*?\[CHART_EMBED_META_END\]/g,
  /\[UPLOADED_EXCEL_PATH_START\][\s\S]*?\[UPLOADED_EXCEL_PATH_END\]/g,
  /\[UPLOADED_EXCEL_NAME_START\][\s\S]*?\[UPLOADED_EXCEL_NAME_END\]/g,
  /\[SQL_ACTION_ID_START\][\s\S]*?\[SQL_ACTION_ID_END\]/g,
  /\[EXCEL_BASE64_START\][\s\S]*?\[EXCEL_BASE64_END\]/g,
  /\[EXPORT_FILE_ID_START\][\s\S]*?\[EXPORT_FILE_ID_END\]/g,
  /\[FILENAME_START\][\s\S]*?\[FILENAME_END\]/g,
  /\[ROW_COUNT_START\][\s\S]*?\[ROW_COUNT_END\]/g,
  /\[CREATE_TABLE_SCHEMA_PREVIEW\]/g,
  /^\[SHARED SESSION\s*[—-]\s*READ-ONLY MODE\][\s\S]*?\n\s*User message:\s*/i,
];

function stripInternal(text: string): string {
  let out = text || '';
  for (const re of INTERNAL_MARKER_PATTERNS) out = out.replace(re, '');
  return out.replace(/\n{3,}/g, '\n\n').trim();
}

type Props = {
  sessionId: string;
};

export default function PrintChat({ sessionId }: Props) {
  const [messages, setMessages] = useState<RawMessage[]>([]);
  const [info, setInfo] = useState<{
    session_name?: string;
    created_at?: string;
    session_id?: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await getSession(sessionId);
        if (!res.success) throw new Error('Failed to load session');
        setMessages((res.messages as RawMessage[]) || []);
        setInfo(res.session_info as any);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load');
      } finally {
        setLoaded(true);
      }
    })();
  }, [sessionId]);

  // Auto-trigger the browser print dialog once the page has rendered. The
  // user can pick "Save as PDF" from the printer dropdown.
  useEffect(() => {
    if (!loaded || error) return;
    // Tiny delay so layout settles before the dialog freezes the page.
    const t = setTimeout(() => window.print(), 400);
    return () => clearTimeout(t);
  }, [loaded, error]);

  if (error) {
    return (
      <div className="p-8 text-red-700">
        <h1 className="text-xl font-semibold mb-2">Failed to load session</h1>
        <p>{error}</p>
      </div>
    );
  }

  if (!loaded) {
    return <div className="p-8 text-gray-500">Loading…</div>;
  }

  const visible = messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map((m) => ({ ...m, content: stripInternal(m.content || '') }))
    .filter((m) => m.content.length > 0);

  return (
    <div className="print-chat min-h-screen bg-white text-gray-900 p-8 max-w-3xl mx-auto">
      {/* Print-only style: hide the toolbar, tighten spacing for paged output */}
      <style>{`
        @media print {
          .no-print { display: none !important; }
          .print-chat { padding: 0 !important; max-width: 100% !important; }
          .turn { break-inside: avoid; page-break-inside: avoid; }
        }
        .print-chat pre {
          background: #f6f8fa;
          padding: 12px 14px;
          border-radius: 6px;
          overflow-x: auto;
          font-size: 12px;
        }
        .print-chat code {
          background: #f1f3f5;
          padding: 2px 5px;
          border-radius: 3px;
          font-size: 0.9em;
        }
        .print-chat pre code { background: transparent; padding: 0; }
        .print-chat table { border-collapse: collapse; margin: 8px 0; }
        .print-chat th, .print-chat td {
          border: 1px solid #d0d7de; padding: 6px 10px; font-size: 13px;
        }
        .print-chat th { background: #f6f8fa; }
      `}</style>

      <div className="no-print mb-6 flex items-center justify-between gap-3 border-b border-gray-200 pb-4">
        <div className="text-sm text-gray-500">
          Print-friendly view. Use your browser's print dialog to save as PDF.
        </div>
        <button
          type="button"
          onClick={() => window.print()}
          className="px-4 py-2 bg-indigo-600 text-white rounded text-sm hover:bg-indigo-700"
        >
          Print / Save as PDF
        </button>
      </div>

      <header className="mb-6">
        <h1 className="text-2xl font-bold">
          {info?.session_name?.trim() || 'Chat session'}
        </h1>
        <div className="text-xs text-gray-500 mt-1">
          {info?.created_at && <span>Created {info.created_at} · </span>}
          Exported {new Date().toLocaleString()}
        </div>
      </header>

      <main className="space-y-6">
        {visible.map((m, i) => (
          <section key={i} className="turn">
            <h2
              className={
                'text-sm font-semibold mb-1 ' +
                (m.role === 'user' ? 'text-indigo-700' : 'text-gray-700')
              }
            >
              {m.role === 'user' ? 'User' : 'Assistant'}
              {m.timestamp && (
                <span className="text-xs text-gray-400 font-normal ml-2">
                  {m.timestamp}
                </span>
              )}
            </h2>
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
            </div>
          </section>
        ))}
        {visible.length === 0 && (
          <p className="text-gray-500 text-sm">No messages in this session.</p>
        )}
      </main>
    </div>
  );
}
