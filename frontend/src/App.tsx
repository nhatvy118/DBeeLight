import { useState } from 'react';
import { AuthProvider } from './context/AuthContext';
import MainLayout from './components/layout/MainLayout';
import AppRoutes from './routes/AppRoutes';

export default function App() {
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);

  return (
    <AuthProvider>
      <MainLayout currentSessionId={currentSessionId} onSessionSelect={setCurrentSessionId}>
        <AppRoutes sessionId={currentSessionId} onSessionIdChange={setCurrentSessionId} />
      </MainLayout>
    </AuthProvider>
  );
}


