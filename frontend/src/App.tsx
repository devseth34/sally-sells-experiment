import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ChatPage } from "./pages/ChatPage";
import { ExperimentPage } from "./pages/ExperimentPage";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryPage } from "./pages/HistoryPage";
import { BookingPage } from "./pages/BookingPage";
import { AdminPage } from "./pages/AdminPage";
import { VoicePage } from "./pages/voice/VoicePage";
import { VoiceSessionsPage } from "./pages/voice/VoiceSessionsPage";
import { VoiceSessionDetailPage } from "./pages/voice/VoiceSessionDetailPage";
import { VoiceAnalyticsPage } from "./pages/voice/VoiceAnalyticsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route path="/experiment" element={<ExperimentPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/booking/:sessionId" element={<BookingPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/voice" element={<VoicePage />} />
        <Route path="/voice/sessions" element={<VoiceSessionsPage />} />
        <Route path="/voice/sessions/:id" element={<VoiceSessionDetailPage />} />
        <Route path="/voice/analytics" element={<VoiceAnalyticsPage />} />
      </Routes>
    </BrowserRouter>
  );
}