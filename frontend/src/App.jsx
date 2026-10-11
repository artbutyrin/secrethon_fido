import { BrowserRouter, Routes, Route } from 'react-router-dom';
import AppMenu from './components/AppMenu';
import LandingPage from './pages/LandingPage';
import RequestPage from './pages/RequestPage';
import ReportPage from './pages/ReportPage';
import HistoryPage from './pages/HistoryPage';
import { AnalysisProvider } from './hooks/analysisContext';

export default function App() {
  return (
    <AnalysisProvider>
      <BrowserRouter>
        <AppMenu />
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/request" element={<RequestPage />} />
          <Route path="/report/:runId" element={<ReportPage />} />
          <Route path="/report" element={<ReportPage />} />
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </BrowserRouter>
    </AnalysisProvider>
  );
}
