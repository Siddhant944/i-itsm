import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter, Navigate, RouterProvider, type RouteObject } from "react-router";

import { ApiError } from "./api/client";
import { AuthProvider } from "./auth/AuthContext";
import { ToastProvider } from "./components/Toasts";
import { AuditPage } from "./pages/admin/AuditPage";
import { AssignmentPage } from "./pages/admin/config/AssignmentPage";
import { CategoriesPage } from "./pages/admin/config/CategoriesPage";
import { ServicesPage } from "./pages/admin/config/ServicesPage";
import { SLAPage } from "./pages/admin/config/SLAPage";
import { DashboardPage } from "./pages/admin/DashboardPage";
import { SearchPage } from "./pages/admin/SearchPage";
import { UsersPage } from "./pages/admin/UsersPage";
import { ViolationsPage } from "./pages/admin/ViolationsPage";
import { LoginPage } from "./pages/auth/LoginPage";
import { RegisterPage } from "./pages/auth/RegisterPage";
import { MyIncidentsPage } from "./pages/employee/MyIncidentsPage";
import { ReportPage } from "./pages/employee/ReportPage";
import { IncidentDetailPage } from "./pages/incident/IncidentDetailPage";
import { QueuePage } from "./pages/technician/QueuePage";
import { TeamQueuePage } from "./pages/technician/TeamQueuePage";
import { WorkloadPage } from "./pages/technician/WorkloadPage";
import { HomeRedirect, PortalShell } from "./shell/PortalShell";

/** Every route of the three portals. Exported so the navigation test can walk it. */
// eslint-disable-next-line react-refresh/only-export-components -- route table, not a component
export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  {
    path: "/employee",
    element: <PortalShell portal="employee" />,
    children: [
      { index: true, element: <Navigate to="incidents" replace /> },
      { path: "incidents", element: <MyIncidentsPage /> },
      { path: "incidents/:id", element: <IncidentDetailPage /> },
      { path: "report", element: <ReportPage /> },
    ],
  },
  {
    path: "/technician",
    element: <PortalShell portal="technician" />,
    children: [
      { index: true, element: <Navigate to="queue" replace /> },
      { path: "queue", element: <QueuePage /> },
      { path: "team", element: <TeamQueuePage /> },
      { path: "workload", element: <WorkloadPage /> },
      { path: "report", element: <ReportPage /> },
      { path: "reports", element: <MyIncidentsPage /> },
      { path: "incidents/:id", element: <IncidentDetailPage /> },
    ],
  },
  {
    path: "/admin",
    element: <PortalShell portal="admin" />,
    children: [
      { index: true, element: <Navigate to="dashboard" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "incidents", element: <SearchPage /> },
      { path: "incidents/:id", element: <IncidentDetailPage /> },
      { path: "violations", element: <ViolationsPage /> },
      { path: "audit", element: <AuditPage /> },
      { path: "users", element: <UsersPage /> },
      { path: "config/categories", element: <CategoriesPage /> },
      { path: "config/services", element: <ServicesPage /> },
      { path: "config/sla", element: <SLAPage /> },
      { path: "config/assignment", element: <AssignmentPage /> },
    ],
  },
  { path: "*", element: <HomeRedirect /> },
];

// eslint-disable-next-line react-refresh/only-export-components -- shared with the tests
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A refusal (401, 403, 404, 409, 422) will not change on a retry; an outage might.
        retry: (failures, error) =>
          failures < 2 && (!(error instanceof ApiError) || error.status >= 500 || error.offline),
        refetchOnWindowFocus: false,
      },
    },
  });
}

export function App() {
  const [queryClient] = useState(makeQueryClient);
  const [router] = useState(() => createBrowserRouter(routes));
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
