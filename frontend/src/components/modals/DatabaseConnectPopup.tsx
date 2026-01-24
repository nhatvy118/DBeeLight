import React, { useState } from 'react';
import closeIcon from '../../assets/icons/Close.svg';

type DatabaseConnectPopupProps = {
  isOpen: boolean;
  onClose: () => void;
  onConnect: (connectionData: DatabaseConnectionData) => void;
};

export type DatabaseConnectionData = {
  server: string;
  port: string;
  username: string;
  databaseName: string;
  password: string;
};

export default function DatabaseConnectPopup({ isOpen, onClose, onConnect }: DatabaseConnectPopupProps) {
  const [server, setServer] = useState('');
  const [port, setPort] = useState('');
  const [username, setUsername] = useState('');
  const [databaseName, setDatabaseName] = useState('');
  const [password, setPassword] = useState('');

  if (!isOpen) return null;

  const handleConnect = () => {
    // Validate that required fields are filled
    if (!server || !port || !username || !databaseName) {
      alert('Please fill in all required fields');
      return;
    }

    onConnect({
      server,
      port,
      username,
      databaseName,
      password,
    });

    // Reset form after connecting
    setServer('');
    setPort('');
    setUsername('');
    setDatabaseName('');
    setPassword('');
  };

  const handleClose = () => {
    // Reset form when closing
    setServer('');
    setPort('');
    setUsername('');
    setDatabaseName('');
    setPassword('');
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-md shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-gray-900">Connect Database</h2>
          <button
            onClick={handleClose}
            className="text-gray-500 hover:text-gray-700 transition-colors"
            type="button"
          >
            <img src={closeIcon} alt="Close" className="w-5 h-5" />
          </button>
        </div>

        {/* Form Fields */}
        <div className="space-y-4">
          {/* Server */}
          <div>
            <label htmlFor="server" className="block text-sm font-medium text-gray-900 mb-2">
              Server
            </label>
            <input
              id="server"
              type="text"
              value={server}
              onChange={(e) => setServer(e.target.value)}
              className="w-full px-4 py-2 bg-gray-100 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="localhost"
            />
          </div>

          {/* Port */}
          <div>
            <label htmlFor="port" className="block text-sm font-medium text-gray-900 mb-2">
              Port
            </label>
            <input
              id="port"
              type="text"
              value={port}
              onChange={(e) => setPort(e.target.value)}
              className="w-full px-4 py-2 bg-gray-100 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="5432"
            />
          </div>

          {/* Username */}
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-gray-900 mb-2">
              Username
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-2 bg-gray-100 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="postgres"
            />
          </div>

          {/* Database name */}
          <div>
            <label htmlFor="databaseName" className="block text-sm font-medium text-gray-900 mb-2">
              Database name
            </label>
            <input
              id="databaseName"
              type="text"
              value={databaseName}
              onChange={(e) => setDatabaseName(e.target.value)}
              className="w-full px-4 py-2 bg-gray-100 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="mydb"
            />
          </div>

          {/* Password */}
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-900 mb-2">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2 bg-gray-100 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="••••••••"
            />
          </div>
        </div>

        {/* Connect Button */}
        <div className="mt-6 flex justify-center">
          <button
            onClick={handleConnect}
            className="px-8 py-2 bg-blue-300 hover:bg-blue-400 text-black font-medium rounded-lg transition-colors"
            type="button"
          >
            Connect
          </button>
        </div>
      </div>
    </div>
  );
}

