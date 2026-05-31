"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ExternalLink, GitCompareArrows, Home, LayoutGrid, LogOut } from "lucide-react";
import { Logo } from "@/components/finsight/logo";
import { cn } from "@/lib/utils";
import { useAuth } from "@/components/finsight/auth-provider";

const DEFAULT_WORKSPACE = "/workspace/AAPL";

function useWorkspaceHref() {
  const pathname = usePathname();
  const [href, setHref] = useState(
    pathname.startsWith("/workspace/") ? pathname : DEFAULT_WORKSPACE
  );

  useEffect(() => {
    if (pathname.startsWith("/workspace/")) {
      const base = pathname.split("?")[0];
      // Hydrating from external state (URL) — one-shot on pathname change.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHref(base);
      return;
    }
    const last = window.localStorage.getItem("finsight.lastTicker");
    // Hydrating from external state (localStorage) — runs after mount only.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (last) setHref(`/workspace/${last}`);
  }, [pathname]);

  return href;
}

export function AppSidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const workspaceHref = useWorkspaceHref();

  const NAV = [
    { href: "/home", label: "Home", icon: Home, match: "/home" },
    { href: workspaceHref, label: "Workspace", icon: LayoutGrid, match: "/workspace" },
    { href: "/compare", label: "Compare", icon: GitCompareArrows, match: "/compare" },
  ];

  return (
    <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)]/40 px-4 py-5 md:flex">
      <div className="mb-8 px-2">
        <Logo />
      </div>

      <nav className="flex flex-col gap-1">
        {NAV.map((item) => {
          const active = pathname.startsWith(item.match);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-[var(--radius-md)] px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-[var(--color-surface-elevated)] text-[var(--color-foreground)]"
                  : "text-[var(--color-muted-strong)] hover:bg-[var(--color-surface)] hover:text-[var(--color-foreground)]"
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto space-y-3 px-2">
        {user && (
          <div className="flex items-center justify-between">
            <span className="truncate text-xs text-[var(--color-muted-strong)]">
              {user.name || user.email}
            </span>
            <button
              type="button"
              onClick={logout}
              className="text-[var(--color-muted)] hover:text-[var(--color-danger)]"
              title="Sign out"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
        <Link
          href="/"
          className="flex items-center gap-2 text-xs text-[var(--color-muted)] hover:text-[var(--color-foreground)]"
        >
          <ExternalLink className="h-3 w-3" />
          Landing page
        </Link>
      </div>
    </aside>
  );
}
