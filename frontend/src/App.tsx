import { useState } from 'react';
import { AuthProvider } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import { LanguageProvider } from './context/LanguageContext';
import { OnboardingProvider } from './context/OnboardingContext';
import MainLayout from './components/layout/MainLayout';
import AppRoutes from './routes/AppRoutes';
import { Toaster } from './components/Toaster';
import { ConfirmHost } from './components/ConfirmDialog';

export default function App() {
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);

  return (
    <ThemeProvider>
      <LanguageProvider>
        <AuthProvider>
          <OnboardingProvider>
            <MainLayout currentSessionId={currentSessionId} onSessionSelect={setCurrentSessionId}>
              <AppRoutes sessionId={currentSessionId} onSessionIdChange={setCurrentSessionId} />
            </MainLayout>
          </OnboardingProvider>
          <Toaster />
          <ConfirmHost />
        </AuthProvider>
      </LanguageProvider>
    </ThemeProvider>
  );
}


