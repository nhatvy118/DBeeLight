import { useState } from 'react';
import Modal from './Modal';
import { Icons } from '../../icons';
import { testExternalConnection, type ExternalConnectionInput, type ProjectKind } from '../../services/api';

type ProjectModalProps = {
  isOpen: boolean;
  onClose: () => void;
  /** Create an internal (DBeeLight-hosted SQLite) project. */
  onCreateInternal: (name: string, description?: string) => Promise<void> | void;
  /** Create a project bound to the user's own external database. May reject (bad connection). */
  onCreateExternal: (name: string, conn: ExternalConnectionInput, description?: string) => Promise<void>;
};

type Status = 'idle' | 'testing' | 'creating' | 'error';

export default function ProjectModal({ isOpen, onClose, onCreateInternal, onCreateExternal }: ProjectModalProps) {
  const [kind, setKind] = useState<ProjectKind>('internal');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  // external connection fields
  const [host, setHost] = useState('');
  const [port, setPort] = useState('');
  const [database, setDatabase] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [message, setMessage] = useState('');

  if (!isOpen) return null;

  const reset = () => {
    setKind('internal'); setName(''); setDescription('');
    setHost(''); setPort(''); setDatabase(''); setUsername(''); setPassword('');
    setStatus('idle'); setMessage('');
  };

  const close = () => { reset(); onClose(); };

  const conn = (): ExternalConnectionInput => ({
    host, port: parseInt(port, 10) || 5432, database, username, password,
  });

  const handleTest = async () => {
    if (!host || !database) { setStatus('error'); setMessage('Please fill in host and database name.'); return; }
    setStatus('testing'); setMessage('');
    const r = await testExternalConnection(conn());
    if (r.success) { setStatus('idle'); setMessage('Connection looks good.'); }
    else { setStatus('error'); setMessage(r.message); }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    if (kind === 'internal') {
      await onCreateInternal(name.trim(), description.trim() || undefined);
      close();
      return;
    }
    // external: must have connection fields; create probes server-side and may reject.
    if (!host || !database) { setStatus('error'); setMessage('Please fill in host and database name.'); return; }
    setStatus('creating'); setMessage('');
    try {
      await onCreateExternal(name.trim(), conn(), description.trim() || undefined);
      close();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Could not create the external project.');
    }
  };

  const busy = status === 'testing' || status === 'creating';

  const field = (id: string, label: string, value: string, set: (v: string) => void, placeholder: string, type = 'text') => (
    <div>
      <label htmlFor={id} className="field-label">{label}</label>
      <input id={id} type={type} value={value} onChange={(e) => set(e.target.value)} disabled={busy}
        placeholder={placeholder} className="field focusable" />
    </div>
  );

  const TypeCard = ({ value, icon: Icon, title, sub }: { value: ProjectKind; icon: typeof Icons.Folder; title: string; sub: string }) => {
    const on = kind === value;
    return (
      <button type="button" onClick={() => { setKind(value); setStatus('idle'); setMessage(''); }} className="focusable"
        style={{ flex: 1, textAlign: 'left', padding: '12px 14px', borderRadius: 'var(--r-sm)', cursor: 'pointer',
          border: '1.5px solid ' + (on ? 'var(--accent)' : 'var(--border)'),
          background: on ? 'var(--accent-soft)' : 'var(--surface)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, fontSize: 13.5, fontWeight: 700, color: on ? 'var(--accent-ink)' : 'var(--text)' }}>
          <Icon size={17} /> {title}
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4, lineHeight: 1.4 }}>{sub}</p>
      </button>
    );
  };

  return (
    <Modal title="New project" subtitle="Group related chats and data together." icon={Icons.FolderPlus} onClose={close} width={540}>
      <form onSubmit={(e) => void handleSubmit(e)}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* type picker */}
          <div style={{ display: 'flex', gap: 10 }}>
            <TypeCard value="internal" icon={Icons.Folder} title="Internal" sub="DBeeLight hosts the data. Upload files to get started." />
            <TypeCard value="external" icon={Icons.Database} title="External" sub="Connect to your own Postgres database." />
          </div>

          <div>
            <label htmlFor="project-name" className="field-label">Project name</label>
            <input id="project-name" type="text" value={name} onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Q2 Revenue Review" className="field focusable" autoFocus />
          </div>

          {kind === 'external' && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
                {field('host', 'Host', host, setHost, 'localhost')}
                {field('port', 'Port', port, setPort, '5432')}
              </div>
              {field('database', 'Database name', database, setDatabase, 'mydb')}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {field('username', 'Username', username, setUsername, 'postgres')}
                {field('password', 'Password', password, setPassword, '••••••••', 'password')}
              </div>
              <div style={{ display: 'flex', gap: 9, alignItems: 'flex-start', padding: '11px 13px', background: 'var(--info-soft)', borderRadius: 'var(--r-sm)', color: 'var(--text-soft)' }}>
                <Icons.Info size={16} style={{ flexShrink: 0, marginTop: 1, color: 'var(--info)' }} />
                <span style={{ fontSize: 12.5, lineHeight: 1.5 }}>
                  Your credentials are sent over a secure connection and kept on the server — never stored in your browser.
                </span>
              </div>
            </>
          )}

          <div>
            <label htmlFor="project-description" className="field-label">
              Description <span style={{ color: 'var(--text-faint)', fontWeight: 400 }}>(optional)</span>
            </label>
            <textarea id="project-description" value={description} onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this project about?" rows={2} className="field focusable" />
          </div>

          {message && (
            <div style={{ fontSize: 12.5, lineHeight: 1.5, padding: '10px 12px', borderRadius: 'var(--r-sm)',
              background: status === 'error' ? 'oklch(0.95 0.05 25)' : 'var(--green-soft)',
              color: status === 'error' ? 'oklch(0.5 0.18 25)' : 'var(--green-ink)' }}>
              {message}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
          <button type="button" className="btn btn-outline" style={{ flex: '0 0 auto', padding: '12px 20px' }} onClick={close}>Cancel</button>
          {kind === 'external' && (
            <button type="button" className="btn btn-outline" style={{ flex: '0 0 auto', padding: '12px 16px' }} disabled={busy}
              onClick={() => void handleTest()}>
              {status === 'testing' ? 'Testing…' : (<><Icons.Lightning size={16} /> Test</>)}
            </button>
          )}
          <button type="submit" className="btn btn-primary" style={{ flex: 1, padding: '12px 20px', opacity: busy ? 0.8 : 1 }} disabled={busy}>
            <Icons.Plus size={16} /> {status === 'creating' ? 'Creating…' : 'Create project'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
