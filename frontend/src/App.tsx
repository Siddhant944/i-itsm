import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router";

import { HealthPage } from "./pages/HealthPage";

const queryClient = new QueryClient();

const router = createBrowserRouter([{ path: "*", element: <HealthPage /> }]);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
