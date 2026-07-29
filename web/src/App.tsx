import { useMemo } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { maybeTriggerE2eCrash } from "./e2eCrash";
import { routes } from "./routes";

export default function App() {
  maybeTriggerE2eCrash();
  const router = useMemo(() => createBrowserRouter(routes), []);
  return <RouterProvider router={router} />;
}
