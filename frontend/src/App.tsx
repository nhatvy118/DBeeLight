import { useState } from 'react';
import Sidebar from './components/Sidebar';
import MainContent from './components/MainContent';
import Header from './components/Header';

export default function App() {
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar onSessionSelect={setCurrentSessionId} currentSessionId={currentSessionId} />
      <div className="flex-1 relative">
        <Header />
        <MainContent sessionId={currentSessionId} onSessionIdChange={setCurrentSessionId} />
      </div>
    </div>
  );
}


