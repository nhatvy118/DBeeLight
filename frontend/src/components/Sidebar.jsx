import React from 'react';

const Sidebar = () => {
  const chatHistory = [
    'Random Chat 1',
    'Random Chat 2',
    'Random Chat 3',
    'Random Chat 4'
  ];

  const navItems = [
    { icon: '?', label: 'Help' },
    { icon: '✓', label: 'Activity' },
    { icon: '⚙', label: 'Settings' },
    { icon: '!', label: 'Account Info' }
  ];

  return (
    <div className="w-64 bg-white h-screen flex flex-col shadow-sm">
      {/* Hamburger Menu */}
      <div className="p-4">
        <button className="text-gray-700 hover:text-gray-900">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      </div>

      {/* New Chat Button */}
      <div className="px-4 mb-6">
        <button className="w-full bg-blue-500 hover:bg-blue-600 text-white font-semibold py-3 px-4 rounded-lg transition-colors">
          + New Chat
        </button>
      </div>

      {/* Chats History */}
      <div className="px-4 mb-6">
        <h2 className="text-lg font-bold text-gray-800 mb-3">Chats History</h2>
        <div className="space-y-2">
          {chatHistory.map((chat, index) => (
            <button
              key={index}
              className="w-full text-left px-3 py-2 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors"
            >
              {chat}
            </button>
          ))}
        </div>
      </div>

      {/* Navigation Links */}
      <div className="mt-auto px-4 pb-6 space-y-2">
        {navItems.map((item, index) => (
          <button
            key={index}
            className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-100 text-gray-700 transition-colors"
          >
            <span className="text-lg">{item.icon}</span>
            <span className="font-medium">{item.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
};

export default Sidebar;

