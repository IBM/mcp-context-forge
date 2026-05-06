import type { ReactNode } from "react";
import { SidebarProvider, SidebarInset } from "../ui/sidebar";
import { AppSidebar } from "./Sidebar";
import { Header } from "./Header";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <SidebarProvider className="flex min-h-svh flex-col">
      <Header />
      <div className="flex min-h-0 flex-1">
        <AppSidebar />
        <SidebarInset className="min-h-0">
          <div className="flex flex-1 flex-col gap-4 p-6">{children}</div>
        </SidebarInset>
      </div>
    </SidebarProvider>
  );
}
