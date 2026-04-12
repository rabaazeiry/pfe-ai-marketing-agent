import { Outlet } from '@tanstack/react-router';
import { Sidenav } from './Sidenav';
import { Topbar } from './Topbar';
import { Footer } from './Footer';
import { useLangEffect } from '@/i18n/useLangEffect';

export function AppShell() {
  useLangEffect();
  return (
    <div className="min-h-screen lg:flex">
      <Sidenav />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar />
        <main className="flex-1 px-4 sm:px-6 lg:px-8 py-6 bg-slate-50">
          <Outlet />
        </main>
        <Footer />
      </div>
    </div>
  );
}
