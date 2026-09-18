import { useMemo } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { maybeTriggerE2eCrash } from "./e2eCrash";
import { useDocumentTitle } from "./hooks/useDocumentTitle";
import { routes } from "./routes";
import { ChunkErrorBoundary } from "./components/ChunkErrorBoundary";

export default function App() {
  maybeTriggerE2eCrash();
  useDocumentTitle();
  const router = useMemo(() => createBrowserRouter(routes), []);
  return (
    <ChunkErrorBoundary>
      <RouterProvider router={router} />
    </ChunkErrorBoundary>
  );
}
