import { type RouteObject } from "react-router-dom";
import AuthGuard from "./components/AuthGuard";
import RootLayout from "./components/RootLayout";
import LoginPage from "./pages/LoginPage";
import VerifyPage from "./pages/VerifyPage";
import GeneratePage from "./pages/GeneratePage";
import HistoryPage from "./pages/HistoryPage";
import SubjectSelectPage from "./pages/SubjectSelectPage";
import FidelityComparePage from "./pages/FidelityComparePage";

export const routes: RouteObject[] = [
  {
    element: <RootLayout />,
    children: [
      { index: true, element: <LoginPage /> },
      { path: "verify", element: <VerifyPage /> },
      {
        path: "generate",
        element: (
          <AuthGuard>
            <SubjectSelectPage />
          </AuthGuard>
        ),
      },
      {
        path: "generate/math",
        element: (
          <AuthGuard>
            <GeneratePage subject="math" />
          </AuthGuard>
        ),
      },
      {
        path: "generate/social_studies",
        element: (
          <AuthGuard>
            <GeneratePage subject="social_studies" />
          </AuthGuard>
        ),
      },
      {
        path: "generate/natural_sciences",
        element: (
          <AuthGuard>
            <GeneratePage subject="natural_sciences" />
          </AuthGuard>
        ),
      },
      {
        path: "history",
        element: (
          <AuthGuard>
            <HistoryPage />
          </AuthGuard>
        ),
      },
      {
        path: "history/:id",
        element: (
          <AuthGuard>
            <HistoryPage />
          </AuthGuard>
        ),
      },
      { path: "fidelity-compare", element: <FidelityComparePage /> },
    ],
  },
];
