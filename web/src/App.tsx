import { BrowserRouter, Routes, Route } from "react-router-dom";
import AuthGuard from "./components/AuthGuard";
import StagingBanner from "./components/StagingBanner";
import FeedbackButton from "./components/FeedbackButton";
import LoginPage from "./pages/LoginPage";
import VerifyPage from "./pages/VerifyPage";
import GeneratePage from "./pages/GeneratePage";
import HistoryPage from "./pages/HistoryPage";
import SubjectSelectPage from "./pages/SubjectSelectPage";

export default function App() {
  return (
    <BrowserRouter>
      <StagingBanner />
      <FeedbackButton />
      <Routes>
        <Route path="/" element={<LoginPage />} />
        <Route path="/verify" element={<VerifyPage />} />
        <Route
          path="/generate"
          element={
            <AuthGuard>
              <SubjectSelectPage />
            </AuthGuard>
          }
        />
        <Route
          path="/generate/math"
          element={
            <AuthGuard>
              <GeneratePage subject="math" />
            </AuthGuard>
          }
        />
        <Route
          path="/generate/social_studies"
          element={
            <AuthGuard>
              <GeneratePage subject="social_studies" />
            </AuthGuard>
          }
        />
        <Route
          path="/generate/natural_sciences"
          element={
            <AuthGuard>
              <GeneratePage subject="natural_sciences" />
            </AuthGuard>
          }
        />
        <Route
          path="/history"
          element={
            <AuthGuard>
              <HistoryPage />
            </AuthGuard>
          }
        />
        <Route
          path="/history/:id"
          element={
            <AuthGuard>
              <HistoryPage />
            </AuthGuard>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
