import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icons } from '../../icons';
import { toast } from '../Toaster';
import { suggestTableDescriptions, saveTableDescriptions } from '../../services/api';

/** Shown right after a CSV/Excel is imported into a NEW project table. Pre-fills table + column
 *  descriptions with an LLM suggestion (which the user edits), then saves them to the data
 *  dictionary so the query agent understands the table. The user can also skip. */
export default function DescribeTableModal({
  projectId, table, onDone,
}: {
  projectId: string;
  table: { name: string; columns: string[] };
  onDone: () => void;
}) {
  const [tableDesc, setTableDesc] = useState('');
  const [colDesc, setColDesc] = useState<Record<string, string>>(() =>
    Object.fromEntries(table.columns.map((c) => [c, ''])),
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Pre-fill with an LLM suggestion. Best-effort: if it fails, the user fills in the blanks.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const s = await suggestTableDescriptions(projectId, table.name);
        if (cancelled) return;
        setTableDesc(s.tableDescription || '');
        setColDesc((prev) => {
          const next = { ...prev };
          for (const c of s.columns) if (c.name in next) next[c.name] = c.description || '';
          return next;
        });
      } catch {
        // leave fields empty
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [projectId, table.name]);

  const save = async () => {
    setSaving(true);
    try {
      await saveTableDescriptions(projectId, table.name, {
        tableDescription: tableDesc,
        columns: table.columns.map((c) => ({ name: c, description: colDesc[c] || '' })),
      });
      toast.success(`Saved descriptions for ${table.name}`);
      onDone();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const field: React.CSSProperties = {
    width: '100%', padding: '8px 10px', fontSize: 13.5, borderRadius: 'var(--r-sm)',
    border: '1px solid var(--border)', background: 'var(--surface)', resize: 'vertical',
  };

  return createPortal(
    <div className="backdrop" style={{ position: 'fixed', inset: 0, zIndex: 200, display: 'grid', placeItems: 'center', background: 'rgba(0,0,0,.4)', padding: 16 }} onClick={onDone}>
      <div className="card" style={{ width: 600, maxWidth: '100%', maxHeight: '88vh', display: 'flex', flexDirection: 'column', padding: 0, borderRadius: 'var(--r)' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '18px 22px', borderBottom: '1px solid var(--border)' }}>
          <span style={{ width: 38, height: 38, borderRadius: 10, display: 'grid', placeItems: 'center', background: 'var(--green-soft)', color: 'var(--green-ink)' }}><Icons.Database size={19} /></span>
          <div style={{ minWidth: 0 }}>
            <h3 style={{ fontSize: 17, fontWeight: 700 }}>Describe “{table.name}”</h3>
            <p style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>Helps the assistant understand this table. You can edit the suggestions.</p>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '18px 22px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {loading ? (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13.5 }}>Generating suggestions…</div>
          ) : (
            <>
              <div>
                <label style={{ display: 'block', fontSize: 12.5, fontWeight: 700, color: 'var(--text-soft)', marginBottom: 5 }}>Table description</label>
                <textarea value={tableDesc} onChange={(e) => setTableDesc(e.target.value)} rows={2}
                  placeholder="What this table stores…" style={field} />
              </div>
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-soft)', marginBottom: 8 }}>Columns ({table.columns.length})</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {table.columns.map((c) => (
                    <div key={c} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                      <span style={{ width: 150, flexShrink: 0, fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingTop: 8 }} title={c}>{c}</span>
                      <input value={colDesc[c] || ''} onChange={(e) => setColDesc((p) => ({ ...p, [c]: e.target.value }))}
                        placeholder="What this column means…" style={{ ...field, flex: 1 }} />
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '14px 22px', borderTop: '1px solid var(--border)' }}>
          <button type="button" className="btn btn-outline" style={{ padding: '10px 18px' }} onClick={onDone} disabled={saving}>Skip</button>
          <button type="button" className="btn btn-primary" style={{ padding: '10px 18px' }} onClick={() => void save()} disabled={saving || loading}>
            {saving ? 'Saving…' : 'Save descriptions'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
