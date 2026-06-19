import { useState, useEffect } from 'react';
import Modal from './Modal';
import { Icons } from '../../icons';

type DatabaseConnectPopupProps = {
  isOpen: boolean;
  onClose: () => void;
  onConnect: (connectionData: DatabaseConnectionData) => Promise<{ success: boolean; error?: string }>;
  onDisconnect: () => void | Promise<void>;
  connectedDb: DatabaseConnectionData | null;
  isInProject?: boolean;
};

export type DatabaseConnectionData = {
  server: string;
  port: string;
  username: string;
  databaseName: string;
  password: string;
};

type ConnectStatus = 'idle' | 'connecting' | 'success' | 'error';

export default function DatabaseConnectPopup({
  isOpen,
  onClose,
  onConnect,
  onDisconnect,
  connectedDb,
  isInProject = false,
}: DatabaseConnectPopupProps) {
  const [server, setServer] = useState('');
  const [port, setPort] = useState('');
  const [username, setUsername] = useState('');
  const [databaseName, setDatabaseName] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState<ConnectStatus>('idle');
  const [errorMessage, setErrorMessage] = useState('');

  // Pre-fill form from persisted connection when popup opens
  useEffect(() => {
    if (isOpen) {
      if (connectedDb) {
        setServer(connectedDb.server);
        setPort(connectedDb.port);
        setUsername(connectedDb.username);
        setDatabaseName(connectedDb.databaseName);
        setPassword(connectedDb.password);
        setStatus('success');
      } else {
        setStatus('idle');
        setErrorMessage('');
      }
    }
  }, [isOpen, connectedDb]);

  if (!isOpen) return null;

  const handleConnect = async () => {
    if (!server || !port || !username || !databaseName) {
      setStatus('error');
      setErrorMessage('Please fill in all required fields.');
      return;
    }

    setStatus('connecting');
    setErrorMessage('');

    const result = await onConnect({ server, port, username, databaseName, password });

    if (result.success) {
      setStatus('success');
    } else {
      setStatus('error');
      setErrorMessage(result.error ?? 'Failed to connect. Please check your credentials.');
    }
  };

  const handleClose = () => {
    setErrorMessage('');
    if (!connectedDb) {
      setServer('');
      setPort('');
      setUsername('');
      setDatabaseName('');
      setPassword('');
      setStatus('idle');
    }
    onClose();
  };

  const handleDisconnect = () => {
    void onDisconnect();
    setServer('');
    setPort('');
    setUsername('');
    setDatabaseName('');
    setPassword('');
    setStatus('idle');
    setErrorMessage('');
  };

  const isConnecting = status === 'connecting';
  const isSuccess = status === 'success';
  const isDisabled = isConnecting || isSuccess || isInProject;

  const field = (
    id: string,
    label: string,
    value: string,
    setter: (v: string) => void,
    placeholder: string,
    type = 'text',
  ) => (
    <div>
      <label htmlFor={id} className="field-label">{label}</label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => setter(e.target.value)}
        disabled={isDisabled}
        className="field focusable"
        style={{ opacity: isDisabled ? 0.7 : 1 }}
        placeholder={placeholder}
      />
    </div>
  );

  return (
    <Modal
      title="Connect your data"
      subtitle="Your credentials are sent over a secure connection and kept on the server — never stored in your browser."
      icon={Icons.Database}
      onClose={handleClose}
      width={540}
    >
      {/* Project restriction banner */}
      {isInProject && (
        <div style={{ display: 'flex', gap: 9, alignItems: 'flex-start', padding: '11px 13px', background: 'var(--info-soft)', borderRadius: 'var(--r-sm)', color: 'var(--text-soft)', marginBottom: 16 }}>
          <Icons.Info size={16} style={{ flexShrink: 0, marginTop: 1, color: 'var(--info)' }} />
          <span style={{ fontSize: 12.5, lineHeight: 1.5 }}>
            Cannot connect to an external database while inside a project. Switch to a non-project session to use this feature.
          </span>
        </div>
      )}

      {/* Success banner */}
      {!isInProject && isSuccess && (
        <div style={{ display: 'flex', gap: 9, alignItems: 'flex-start', padding: '11px 13px', background: 'var(--green-soft)', borderRadius: 'var(--r-sm)', marginBottom: 16 }}>
          <Icons.Check size={16} style={{ flexShrink: 0, marginTop: 1, color: 'var(--green-ink)' }} />
          <div style={{ fontSize: 13, color: 'var(--green-ink)' }}>
            <span style={{ fontWeight: 700 }}>Connected successfully</span>
            <div style={{ marginTop: 2 }}>{databaseName} @ {server}:{port}</div>
          </div>
        </div>
      )}

      {/* Error banner */}
      {!isInProject && status === 'error' && errorMessage && (
        <div style={{ display: 'flex', gap: 9, alignItems: 'flex-start', padding: '11px 13px', background: 'oklch(0.95 0.05 25)', borderRadius: 'var(--r-sm)', marginBottom: 16 }}>
          <Icons.Close size={16} style={{ flexShrink: 0, marginTop: 1, color: 'oklch(0.58 0.19 25)' }} />
          <span style={{ fontSize: 13, color: 'oklch(0.5 0.18 25)' }}>{errorMessage}</span>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
          {field('server', 'Host', server, setServer, 'localhost')}
          {field('port', 'Port', port, setPort, '5432')}
        </div>
        {field('databaseName', 'Database name', databaseName, setDatabaseName, 'mydb')}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {field('username', 'Username', username, setUsername, 'postgres')}
          {field('password', 'Password', password, setPassword, '••••••••', 'password')}
        </div>
        <div style={{ display: 'flex', gap: 9, alignItems: 'flex-start', padding: '11px 13px', background: 'var(--info-soft)', borderRadius: 'var(--r-sm)', color: 'var(--text-soft)' }}>
          <Icons.Info size={16} style={{ flexShrink: 0, marginTop: 1, color: 'var(--info)' }} />
          <span style={{ fontSize: 12.5, lineHeight: 1.5 }}>
            LightDBee only reads your data to answer questions. It never changes anything without asking you first.
          </span>
        </div>
      </div>

      {/* Action Button */}
      <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
        {isInProject ? null : isSuccess ? (
          <button
            onClick={handleDisconnect}
            type="button"
            className="btn"
            style={{ flex: '0 0 auto', width: 200, margin: '0 auto', padding: '12px 20px', background: 'oklch(0.95 0.05 25)', color: 'oklch(0.5 0.18 25)' }}
          >
            <Icons.Close size={16} /> Disconnect
          </button>
        ) : (
          <button
            onClick={() => void handleConnect()}
            disabled={isConnecting}
            type="button"
            className="btn btn-primary"
            style={{ flex: 1, padding: '12px 20px', opacity: isConnecting ? 0.8 : 1 }}
          >
            {isConnecting ? 'Connecting…' : (<><Icons.Lightning size={16} /> Test &amp; connect</>)}
          </button>
        )}
      </div>
    </Modal>
  );
}
