import Sidebar from './components/Sidebar';
import MainContent from './components/MainContent';
import Header from './components/Header';

export default function App() {
  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <div className="flex-1 relative">
        <Header />
        <MainContent />
      </div>
    </div>
  );
}


