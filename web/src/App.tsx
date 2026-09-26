import { useMemo } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { maybeTriggerE2eCrash } from "./e2eCrash";
import { useDocumentTitle } from "./hooks/useDocumentTitle";
import { routes } from "./routes";
import { ChunkErrorBoundary } from "./components/ChunkErrorBoundary";

function shouldUseViewTransition(): boolean {
  if (typeof document === "undefined") return false;
  if (typeof document.startViewTransition !== "function") return false;
  return !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export default function App() {
  maybeTriggerE2eCrash();
  useDocumentTitle();
  const router = useMemo(() => {
    const createdRouter = createBrowserRouter(routes);
    const navigate = createdRouter.navigate.bind(createdRouter);
    createdRouter.navigate = ((to, options) => {
      if (typeof to === "number") return navigate(to, options);
      return navigate(to, {
        ...options,
        viewTransition: options?.viewTransition ?? shouldUseViewTransition(),
      });
    }) as typeof createdRouter.navigate;
    return createdRouter;
  }, []);
  return (
    <ChunkErrorBoundary>
      <RouterProvider router={router} />
    </ChunkErrorBoundary>
  );
}
