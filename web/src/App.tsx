import { BrowserRouter, Routes, Route } from "react-router-dom";
import AuthGuard from "./components/AuthGuard";
import StagingBanner from "./components/StagingBanner";
import LoginPage from "./pages/LoginPage";
import VerifyPage from "./pages/VerifyPage";
import GeneratePage from "./pages/GeneratePage";
import SubjectSelectPage from "./pages/SubjectSelectPage";

export default function App() {
  return (
    <BrowserRouter>
      <StagingBanner />
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
      </Routes>
    </BrowserRouter>
  );
}
