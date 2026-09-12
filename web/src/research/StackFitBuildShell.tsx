import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import "../index.css";
import App from "../App";
import ErrorBoundary from "../components/ErrorBoundary";

export function mountStackFitProbe(probe: ReactNode) {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <ErrorBoundary>
        <App />
        {probe}
      </ErrorBoundary>
    </StrictMode>,
  );
}
