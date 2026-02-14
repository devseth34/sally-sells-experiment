import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ChatPage } from "./pages/ChatPage";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryPage } from "./pages/HistoryPage";
import { BookingPage } from "./pages/BookingPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/booking/:sessionId" element={<BookingPage />} />
      </Routes>
    </BrowserRouter>
  );
}