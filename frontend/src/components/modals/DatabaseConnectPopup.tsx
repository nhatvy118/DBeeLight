import React, { useState, useEffect } from 'react';
import closeIcon from '../../assets/icons/Close.svg';

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
    // Only reset local error state; form values and success state persist in parent
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
    void onDisconnect(); // clear parent state first
    setServer('');
    setPort('');
    setUsername('');
    setDatabaseName('');
    setPassword('');
    setStatus('idle');
    setErrorMessage('');
    // popup stays open so user can re-connect
  };

  const isConnecting = status === 'connecting';
  const isSuccess = status === 'success';
  const isDisabled = isConnecting || isSuccess || isInProject;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-slate-900 rounded-lg p-6 w-full max-w-md shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Connect Database</h2>
          <button
            onClick={handleClose}
            className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
            type="button"
          >
            <img src={closeIcon} alt="Close" className="w-5 h-5" />
          </button>
        </div>

        {/* Project restriction banner */}
        {isInProject && (
          <div className="mb-4 flex items-start gap-2 rounded-lg bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-700 px-4 py-3">
            <svg className="mt-0.5 h-4 w-4 flex-shrink-0 text-yellow-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
            <p className="text-sm text-yellow-800 dark:text-yellow-300">
              Cannot connect to an external database while inside a project. Switch to a non-project session to use this feature.
            </p>
          </div>
        )}

        {/* Success banner */}
        {!isInProject && isSuccess && (
          <div className="mb-4 flex items-start gap-2 rounded-lg bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-700 px-4 py-3">
            <svg className="mt-0.5 h-4 w-4 flex-shrink-0 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            <div className="text-sm text-green-800 dark:text-green-300">
              <span className="font-semibold">Connected successfully</span>
              <div className="mt-0.5 text-green-700 dark:text-green-400">
                {databaseName} @ {server}:{port}
              </div>
            </div>
          </div>
        )}

        {/* Error banner */}
        {!isInProject && status === 'error' && errorMessage && (
          <div className="mb-4 flex items-start gap-2 rounded-lg bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 px-4 py-3">
            <svg className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
            <p className="text-sm text-red-800 dark:text-red-300">{errorMessage}</p>
          </div>
        )}

        {/* Form Fields */}
        <div className="space-y-4">
          <div>
            <label htmlFor="server" className="block text-sm font-medium text-gray-900 dark:text-gray-100 mb-2">
              Server
            </label>
            <input
              id="server"
              type="text"
              value={server}
              onChange={(e) => setServer(e.target.value)}
              disabled={isDisabled}
              className="w-full px-4 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-gray-900 dark:text-gray-100 disabled:opacity-60"
              placeholder="localhost"
            />
          </div>

          <div>
            <label htmlFor="port" className="block text-sm font-medium text-gray-900 dark:text-gray-100 mb-2">
              Port
            </label>
            <input
              id="port"
              type="text"
              value={port}
              onChange={(e) => setPort(e.target.value)}
              disabled={isDisabled}
              className="w-full px-4 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-gray-900 dark:text-gray-100 disabled:opacity-60"
              placeholder="5432"
            />
          </div>

          <div>
            <label htmlFor="username" className="block text-sm font-medium text-gray-900 dark:text-gray-100 mb-2">
              Username
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isDisabled}
              className="w-full px-4 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-gray-900 dark:text-gray-100 disabled:opacity-60"
              placeholder="postgres"
            />
          </div>

          <div>
            <label htmlFor="databaseName" className="block text-sm font-medium text-gray-900 dark:text-gray-100 mb-2">
              Database name
            </label>
            <input
              id="databaseName"
              type="text"
              value={databaseName}
              onChange={(e) => setDatabaseName(e.target.value)}
              disabled={isDisabled}
              className="w-full px-4 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-gray-900 dark:text-gray-100 disabled:opacity-60"
              placeholder="mydb"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-900 dark:text-gray-100 mb-2">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isDisabled}
              className="w-full px-4 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-gray-900 dark:text-gray-100 disabled:opacity-60"
              placeholder="••••••••"
            />
          </div>
        </div>

        {/* Action Button */}
        <div className="mt-6 flex justify-center">
          {isInProject ? null : isSuccess ? (
            <button
              onClick={handleDisconnect}
              className="px-8 py-2 bg-red-100 hover:bg-red-200 dark:bg-red-900/40 dark:hover:bg-red-900/60 text-red-700 dark:text-red-300 font-medium rounded-lg transition-colors"
              type="button"
            >
              Disconnect
            </button>
          ) : (
            <button
              onClick={() => void handleConnect()}
              disabled={isConnecting}
              className="px-8 py-2 bg-blue-300 hover:bg-blue-400 text-black font-medium rounded-lg transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-2"
              type="button"
            >
              {isConnecting && (
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
              )}
              {isConnecting ? 'Connecting…' : 'Connect'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
