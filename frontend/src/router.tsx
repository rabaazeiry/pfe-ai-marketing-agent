import {
  createRootRoute,
  createRoute,
  createRouter,
  redirect,
  Outlet
} from '@tanstack/react-router';
import { AppShell } from '@/components/layout/AppShell';
import { LoginPage } from '@/pages/LoginPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { ProjectsPage } from '@/pages/ProjectsPage';
import { ProjectDetailPage } from '@/pages/ProjectDetailPage';
import { AnalyticsPage } from '@/pages/AnalyticsPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { AdminPage } from '@/pages/AdminPage';
import { ForbiddenPage } from '@/pages/ForbiddenPage';
import { useAuthStore } from '@/stores/auth.store';

const rootRoute = createRootRoute({ component: () => <Outlet /> });

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
  beforeLoad: () => {
    const { token } = useAuthStore.getState();
    if (token) throw redirect({ to: '/' });
  }
});

const authedLayout = createRoute({
  getParentRoute: () => rootRoute,
  id: '_authed',
  component: AppShell,
  beforeLoad: () => {
    const { token } = useAuthStore.getState();
    if (!token) throw redirect({ to: '/login' });
  }
});

const dashboardRoute   = createRoute({ getParentRoute: () => authedLayout, path: '/', component: DashboardPage });
const projectsRoute       = createRoute({ getParentRoute: () => authedLayout, path: '/projects', component: ProjectsPage });
const projectDetailRoute  = createRoute({ getParentRoute: () => authedLayout, path: '/projects/$projectId', component: ProjectDetailPage });
const analyticsRoute   = createRoute({ getParentRoute: () => authedLayout, path: '/analytics', component: AnalyticsPage });
const settingsRoute    = createRoute({ getParentRoute: () => authedLayout, path: '/settings', component: SettingsPage });
const forbiddenRoute   = createRoute({ getParentRoute: () => authedLayout, path: '/forbidden', component: ForbiddenPage });

const adminRoute = createRoute({
  getParentRoute: () => authedLayout,
  path: '/admin',
  component: AdminPage,
  beforeLoad: () => {
    const role = useAuthStore.getState().user?.role;
    if (role !== 'admin') throw redirect({ to: '/forbidden' });
  }
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  authedLayout.addChildren([
    dashboardRoute,
    projectsRoute,
    projectDetailRoute,
    analyticsRoute,
    settingsRoute,
    forbiddenRoute,
    adminRoute
  ])
]);

export const router = createRouter({ routeTree, defaultPreload: 'intent' });

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
