import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, useState, type ComponentType } from "react";
import { createBrowserRouter, Navigate, RouterProvider, type RouteObject } from "react-router";

import { ApiError } from "./api/client";
import { AuthProvider } from "./auth/AuthContext";
import { ToastProvider } from "./components/Toasts";
import { LoginPage } from "./pages/auth/LoginPage";
import { RegisterPage } from "./pages/auth/RegisterPage";
import { HomeRedirect, PortalShell } from "./shell/PortalShell";
import { RouteError } from "./shell/RouteError";

/**
 * P5.6: each screen is its own chunk, fetched when first opened, so an employee never downloads
 * the admin dashboard's charts. The shell shows a skeleton meanwhile (PortalShell's Suspense).
 */
function page<K extends string>(
  load: () => Promise<Record<K, ComponentType>>,
  name: K,
): ComponentType {
  return lazy(async (): Promise<{ default: ComponentType }> => ({ default: (await load())[name] }));
}

const AuditPage = page(() => import("./pages/admin/AuditPage"), "AuditPage");
const AssignmentPage = page(() => import("./pages/admin/config/AssignmentPage"), "AssignmentPage");
const CategoriesPage = page(() => import("./pages/admin/config/CategoriesPage"), "CategoriesPage");
const ServicesPage = page(() => import("./pages/admin/config/ServicesPage"), "ServicesPage");
const SLAPage = page(() => import("./pages/admin/config/SLAPage"), "SLAPage");
const DashboardPage = page(() => import("./pages/admin/DashboardPage"), "DashboardPage");
const HealthMapPage = page(() => import("./pages/admin/HealthMapPage"), "HealthMapPage");
const SearchPage = page(() => import("./pages/admin/SearchPage"), "SearchPage");
const UsersPage = page(() => import("./pages/admin/UsersPage"), "UsersPage");
const ViolationsPage = page(() => import("./pages/admin/ViolationsPage"), "ViolationsPage");
const MyIncidentsPage = page(() => import("./pages/employee/MyIncidentsPage"), "MyIncidentsPage");
const ReportPage = page(() => import("./pages/employee/ReportPage"), "ReportPage");
const ChatReportPage = page(() => import("./pages/employee/ChatReportPage"), "ChatReportPage");
const IncidentDetailPage = page(
  () => import("./pages/incident/IncidentDetailPage"),
  "IncidentDetailPage",
);
const QueuePage = page(() => import("./pages/technician/QueuePage"), "QueuePage");
const TeamQueuePage = page(() => import("./pages/technician/TeamQueuePage"), "TeamQueuePage");
const WorkloadPage = page(() => import("./pages/technician/WorkloadPage"), "WorkloadPage");

/** Every route of the three portals. Exported so the navigation test can walk it. */
// eslint-disable-next-line react-refresh/only-export-components -- route table, not a component
export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  {
    path: "/employee",
    element: <PortalShell portal="employee" />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="incidents" replace /> },
      { path: "incidents", element: <MyIncidentsPage /> },
      { path: "incidents/:id", element: <IncidentDetailPage /> },
      { path: "report", element: <ReportPage /> },
      { path: "chat", element: <ChatReportPage /> },
    ],
  },
  {
    path: "/technician",
    element: <PortalShell portal="technician" />,
    errorElement: <RouteError />,
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
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="dashboard" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "health", element: <HealthMapPage /> },
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
