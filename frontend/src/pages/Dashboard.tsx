import { useCallback, useEffect, useRef, useState } from 'react';
import VegaLiteChart from '../components/chat/VegaLiteChart';
import { Icons } from '../icons';
import { toast } from '../components/Toaster';
import { confirm } from '../components/ConfirmDialog';
import {
  renderDashboard,
  deleteSavedChart,
  updateChart,
  reorderDashboard,
  type DashboardChart,
} from '../services/api';

type DashboardProps = { projectId: string };

function projectName(projectId: string): string {
  try {
    const projects = JSON.parse(localStorage.getItem('projects') || '[]') as { id: string; name: string }[];
    return projects.find((p) => p.id === projectId)?.name || 'Project';
  } catch {
    return 'Project';
  }
}

/** Live project dashboard — re-runs every saved chart's SQL on load / refresh. */
export default function Dashboard({ projectId }: DashboardProps) {
  const [charts, setCharts] = useState<DashboardChart[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [auto, setAuto] = useState(false);
  const [editing, setEditing] = useState<DashboardChart | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await renderDashboard(projectId);
      setCharts(res.success ? res.charts : []);
      setUpdatedAt(new Date());
    } catch {
      toast.error('Could not load dashboard');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  // Auto-refresh every 30s when enabled.
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    if (!auto) return;
    const t = setInterval(() => { void loadRef.current(); }, 30000);
    return () => clearInterval(t);
  }, [auto]);

  const remove = async (id: string) => {
    if (!(await confirm({ title: 'Remove chart?', message: 'This removes the chart from the dashboard.' }))) return;
    try {
      await deleteSavedChart(id);
      setCharts((prev) => prev.filter((c) => c.id !== id));
    } catch {
      toast.error('Could not remove chart');
    }
  };

  const move = async (index: number, dir: -1 | 1) => {
    const next = index + dir;
    if (next < 0 || next >= charts.length) return;
    const reordered = [...charts];
    [reordered[index], reordered[next]] = [reordered[next], reordered[index]];
    setCharts(reordered);
    try {
      await reorderDashboard(projectId, reordered.map((c) => c.id));
    } catch {
      toast.error('Could not save order');
    }
  };

  const saveTitle = async (id: string, title: string) => {
    const trimmed = title.trim();
    if (!trimmed) return;
    setCharts((prev) => prev.map((c) => c.id === id ? { ...c, title: trimmed } : c));
    try {
      await updateChart(id, { title: trimmed });
    } catch {
      toast.error('Could not update title');
    }
  };

  const goBack = () => {
    window.history.pushState({}, '', `/chat/${projectId}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  const addChart = () => {
    window.history.pushState({}, '', `/chat/${projectId}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  const multi = charts.length > 1;

  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', background: 'var(--bg)' }}>
    <div style={{ maxWidth: 1400, margin: '0 auto', padding: '28px 32px 48px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
        <button type="button" onClick={goBack} className="btn btn-outline" style={{ padding: '6px 10px' }} aria-label="Back to chat">
          <Icons.ChevronRight size={18} style={{ transform: 'rotate(180deg)' }} />
        </button>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Dashboard</h1>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'var(--surface-2)', padding: '3px 10px', borderRadius: 'var(--r-sm)', fontSize: 12.5, color: 'var(--text-muted)' }}>
          <Icons.Folder size={14} /> {projectName(projectId)}
        </span>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={addChart} className="btn btn-outline" style={{ padding: '7px 12px' }}>
          <Icons.Plus size={15} /> Add chart
        </button>
        <button type="button" onClick={() => void load()} className="btn btn-outline" style={{ padding: '7px 13px' }}>
          <Icons.Refresh size={16} /> Refresh
        </button>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, marginBottom: 22, fontSize: 12.5, color: 'var(--text-muted)' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--green-ink)', background: 'var(--green-soft)', padding: '4px 10px', borderRadius: 'var(--r-sm)' }}>
          <Icons.Lightning size={14} /> Live · re-runs on open
        </span>
        {updatedAt && <span>Updated {updatedAt.toLocaleTimeString()}</span>}
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><Icons.Chart size={14} /> {charts.length} chart{charts.length === 1 ? '' : 's'}</span>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 'auto', cursor: 'pointer' }}>
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Auto-refresh 30s
        </label>
      </div>

      {loading && charts.length === 0 ? (
        <div style={{ padding: '48px 0', textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
      ) : charts.length === 0 ? (
        <div className="card" style={{ padding: '40px 24px', textAlign: 'center' }}>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>No charts yet</div>
          <div style={{ fontSize: 13.5, color: 'var(--text-muted)' }}>
            Generate a chart in this project's chat, then press <b>Save</b> on it to add it here.
          </div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: multi ? 'repeat(auto-fit, minmax(340px, 1fr))' : '1fr', gap: 14 }}>
          {charts.map((c, i) => {
            const full = !multi || c.layout !== 'half';
            return (
              <div key={c.id} style={{ gridColumn: full ? '1 / -1' : 'auto', minWidth: 0, position: 'relative' }}>
                <div style={{ position: 'absolute', top: 28, right: 52, zIndex: 2, display: 'flex', gap: 4 }}>
                  <button type="button" onClick={() => void move(i, -1)} disabled={i === 0} title="Move up" className="btn btn-outline" style={{ padding: '5px 7px' }} aria-label="Move up"><Icons.ChevronDown size={13} style={{ transform: 'rotate(180deg)' }} /></button>
                  <button type="button" onClick={() => void move(i, 1)} disabled={i === charts.length - 1} title="Move down" className="btn btn-outline" style={{ padding: '5px 7px' }} aria-label="Move down"><Icons.ChevronDown size={13} /></button>
                  <button type="button" onClick={() => setEditing(c)} title="Edit SQL" className="btn btn-outline" style={{ padding: '5px 7px' }} aria-label="Edit"><Icons.Code size={14} /></button>
                  <button type="button" onClick={() => void remove(c.id)} title="Remove" className="btn btn-outline" style={{ padding: '5px 7px' }} aria-label="Remove"><Icons.Trash size={14} /></button>
                </div>
                {c.error ? (
                  <div className="card" style={{ padding: '18px 16px' }}>
                    <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{c.title || 'Chart'}</div>
                    <div style={{ fontSize: 12.5, color: 'var(--danger-ink, #a3372d)' }}>Couldn't render: {c.error}</div>
                  </div>
                ) : c.spec ? (
                  <VegaLiteChart
                    specJson={(() => {
                      try { const s = JSON.parse(c.spec!); delete s.title; return JSON.stringify(s); }
                      catch { return c.spec!; }
                    })()}
                    editableTitle={c.title || ''}
                    onTitleSave={(t) => void saveTitle(c.id, t)}
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {editing && (
        <EditChartModal
          chart={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); void load(); }}
        />
      )}
    </div>
    </div>
  );
}

function EditChartModal({ chart, onClose, onSaved }: { chart: DashboardChart; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState(chart.title || '');
  const [sql, setSql] = useState(chart.sql || '');
  const [layout, setLayout] = useState(chart.layout || 'full');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const res = await updateChart(chart.id, { title, sql, layout });
      if (res.success) onSaved();
      else toast.error(res.detail || 'Could not update chart');
    } catch {
      toast.error('Could not update chart');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'grid', placeItems: 'center', zIndex: 50, padding: 16 }}
    >
      <div onClick={(e) => e.stopPropagation()} className="card" style={{ width: 560, maxWidth: '100%', padding: '20px 22px' }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>Edit chart</div>
        <label className="field-label">Title</label>
        <input className="field focusable" value={title} onChange={(e) => setTitle(e.target.value)} style={{ marginBottom: 12 }} />
        <label className="field-label">SQL (read-only SELECT)</label>
        <textarea className="field focusable" value={sql} onChange={(e) => setSql(e.target.value)} rows={6}
          style={{ marginBottom: 12, fontFamily: 'var(--font-mono)', fontSize: 13 }} />
        <label className="field-label">Layout</label>
        <select className="field focusable" value={layout} onChange={(e) => setLayout(e.target.value)} style={{ marginBottom: 18 }}>
          <option value="full">Full width</option>
          <option value="half">Half width</option>
        </select>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn-outline" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void save()}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
    </div>
  );
}
