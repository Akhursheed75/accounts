"use client";

import {
  BarChart3, CalendarDays, ClipboardList, FileSpreadsheet, FileText, GitCompareArrows, KeyRound,
  LayoutDashboard, ListChecks, LogOut, Menu, Moon, ScrollText, Settings, Sun, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { ErrorNote, Modal, Spinner, useToast } from "./ui";
import { api } from "@/lib/api";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  permission: string;
  description?: string;
}

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, permission: "dashboard.view" },
  { href: "/accounting", label: "Daily accounting", icon: ClipboardList, permission: "accounting.read" },
  { href: "/monthly", label: "Monthly records", icon: CalendarDays, permission: "report.read" },
  { href: "/statements", label: "Bank statements", icon: FileText, permission: "statement.read" },
  { href: "/transactions", label: "Transactions", icon: ListChecks, permission: "transaction.read" },
  { href: "/reconciliation", label: "Reconciliation", icon: GitCompareArrows, permission: "reconciliation.read" },
  { href: "/unmatched", label: "Unmatched", icon: BarChart3, permission: "reconciliation.read" },
  { href: "/reports", label: "Reports", icon: FileSpreadsheet, permission: "report.read" },
  { href: "/audit", label: "Audit log", icon: ScrollText, permission: "audit.read" },
  { href: "/settings", label: "Settings", icon: Settings, permission: "shop.read" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, signOut, can } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Checking your session…" />
      </div>
    );
  }
  if (!user) return null;

  const items = NAV.filter((item) => can(item.permission));

  return (
    <div className="flex min-h-screen bg-ink-50">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-ink-200 bg-surface lg:flex">
        <Brand />
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-3">
          {items.map((item) => (
            <NavLink key={item.href} item={item} active={isActive(pathname, item.href)} />
          ))}
        </nav>
        <UserPanel name={user.full_name} role={user.role.name} onSignOut={signOut} />
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-ink-950/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85%] flex-col bg-surface shadow-xl">
            <div className="flex items-center justify-between border-b border-ink-200 pr-2">
              <Brand />
              <button className="btn-ghost btn-sm" onClick={() => setOpen(false)} aria-label="Close menu">
                <X className="h-5 w-5" />
              </button>
            </div>
            <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-3">
              {items.map((item) => (
                <NavLink key={item.href} item={item} active={isActive(pathname, item.href)} />
              ))}
            </nav>
            <UserPanel name={user.full_name} role={user.role.name} onSignOut={signOut} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-ink-200 bg-surface/90 px-4 py-2.5 backdrop-blur lg:hidden">
          <button className="btn-ghost btn-sm" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <span className="text-sm font-semibold">Reconcilia</span>
          <span className="ml-auto truncate text-xs text-ink-500">{user.full_name}</span>
          <ThemeToggle />
        </header>
        <main className="min-w-0 flex-1 px-4 py-4 sm:px-6 sm:py-6">{children}</main>
      </div>
    </div>
  );
}

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5 border-b border-ink-200 px-4 py-4">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white">
        R
      </span>
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold leading-tight">Reconcilia</p>
        <p className="truncate text-[11px] text-ink-500">Shop accounting &amp; banking</p>
      </div>
    </div>
  );
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link href={item.href} className={`nav-link ${active ? "nav-link-active" : ""}`}>
      <Icon className={`h-4 w-4 shrink-0 ${active ? "text-brand-800" : "text-ink-400"}`} />
      <span className="truncate">{item.label}</span>
    </Link>
  );
}

function UserPanel({
  name, role, onSignOut,
}: {
  name: string;
  role: string;
  onSignOut: () => void;
}) {
  const [changing, setChanging] = useState(false);

  return (
    <div className="border-t border-ink-200 p-3">
      <div className="mb-2 flex items-center gap-2 px-1">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-ink-900">{name}</p>
          <p className="truncate text-xs text-ink-500">{role}</p>
        </div>
        <ThemeToggle />
      </div>
      <div className="flex gap-2">
        <button className="btn-secondary btn-sm flex-1 whitespace-nowrap" onClick={() => setChanging(true)}>
          <KeyRound className="h-3.5 w-3.5" />
          Password
        </button>
        <button className="btn-secondary btn-sm flex-1 whitespace-nowrap" onClick={onSignOut}>
          <LogOut className="h-3.5 w-3.5" />
          Sign out
        </button>
      </div>
      <ChangePasswordModal
        open={changing}
        onClose={() => setChanging(false)}
        onChanged={onSignOut}
      />
    </div>
  );
}

export function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const goingTo = theme === "dark" ? "light" : "dark";
  return (
    <button
      className={`btn-secondary btn-sm ${className}`}
      onClick={toggle}
      title={`Switch to the ${goingTo} theme`}
      aria-label={`Switch to the ${goingTo} theme`}
    >
      {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
    </button>
  );
}

function ChangePasswordModal({
  open, onClose, onChanged,
}: {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (next !== confirm) {
      setError(new Error("The two new passwords do not match."));
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      // Changing the password invalidates every token already issued for this
      // account, including the one this tab is holding, so sign out cleanly.
      toast.push("ok", "Password changed. Please sign in again.");
      setCurrent(""); setNext(""); setConfirm("");
      onClose();
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Change your password"
      footer={
        <>
          <button className="btn-secondary btn-sm" onClick={onClose}>Cancel</button>
          <button className="btn-primary btn-sm" form="password-form" type="submit" disabled={busy}>
            Change password
          </button>
        </>
      }
    >
      <form id="password-form" onSubmit={submit} className="space-y-3">
        <label className="block">
          <span className="label">Current password</span>
          <input
            className="input" type="password" autoComplete="current-password" required
            value={current} onChange={(e) => setCurrent(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="label">New password</span>
          <input
            className="input" type="password" autoComplete="new-password" required minLength={10}
            value={next} onChange={(e) => setNext(e.target.value)}
          />
          <span className="mt-1 block text-xs text-ink-500">At least 10 characters.</span>
        </label>
        <label className="block">
          <span className="label">New password again</span>
          <input
            className="input" type="password" autoComplete="new-password" required minLength={10}
            value={confirm} onChange={(e) => setConfirm(e.target.value)}
          />
        </label>
        <p className="text-xs text-ink-500">
          Every session on every device will be signed out, including this one.
        </p>
        <ErrorNote error={error} />
      </form>
    </Modal>
  );
}

export function PageHeader({
  title, description, actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-ink-900">{title}</h1>
        {description && <p className="mt-0.5 text-sm text-ink-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
