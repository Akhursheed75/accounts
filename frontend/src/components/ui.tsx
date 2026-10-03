"use client";

import { AlertTriangle, Check, Info, Loader2, X } from "lucide-react";
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";

import type { MatchStatus } from "@/lib/types";

/* ------------------------------------------------------------------ status */

const STATUS_STYLES: Record<string, string> = {
  MATCHED: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  POSSIBLE: "bg-amber-50 text-amber-800 ring-amber-600/20",
  UNMATCHED: "bg-red-50 text-red-700 ring-red-600/20",
  IGNORED: "bg-ink-100 text-ink-600 ring-ink-500/20",
  PENDING_DEPOSIT: "bg-sky-50 text-sky-700 ring-sky-600/20",
  DEMO: "bg-violet-50 text-violet-700 ring-violet-600/20",
  ACTIVE: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  INACTIVE: "bg-ink-100 text-ink-600 ring-ink-500/20",
  PROCESSED: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  PARTIALLY_PROCESSED: "bg-amber-50 text-amber-800 ring-amber-600/20",
  FAILED: "bg-red-50 text-red-700 ring-red-600/20",
  PROCESSING: "bg-brand-50 text-brand-700 ring-brand-600/20",
  UPLOADED: "bg-ink-100 text-ink-700 ring-ink-500/20",
  DRAFT: "bg-ink-100 text-ink-700 ring-ink-500/20",
  SUBMITTED: "bg-brand-50 text-brand-700 ring-brand-600/20",
  LOCKED: "bg-ink-800 text-white ring-ink-900/20",
  EXACT: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  MANUAL: "bg-violet-50 text-violet-700 ring-violet-600/20",
  CREDIT: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  DEBIT: "bg-orange-50 text-orange-700 ring-orange-600/20",
};

const STATUS_DOTS: Record<string, string> = {
  MATCHED: "bg-emerald-500",
  POSSIBLE: "bg-amber-500",
  UNMATCHED: "bg-red-500",
  IGNORED: "bg-ink-400",
  PENDING_DEPOSIT: "bg-sky-500",
};

export function StatusBadge({ status, dot = true }: { status: string; dot?: boolean }) {
  const label = status.replace(/_/g, " ").toLowerCase();
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5
        text-[11px] font-medium capitalize ring-1 ring-inset
        ${STATUS_STYLES[status] ?? "bg-ink-100 text-ink-700 ring-ink-500/20"}`}
    >
      {dot && STATUS_DOTS[status] && (
        <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOTS[status]}`} />
      )}
      {label}
    </span>
  );
}

export function CurrencyTag({ code }: { code: string }) {
  return (
    <span
      className={`inline-flex rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold ${
        code === "USD" ? "bg-emerald-50 text-emerald-700" : "bg-sky-50 text-sky-700"
      }`}
    >
      {code === "NIO" ? "C$" : "$"}
    </span>
  );
}

/* -------------------------------------------------------------------- misc */

export function Card({
  title, description, actions, children, className = "", padded = true,
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-ink-200 px-4 py-3 sm:px-5">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink-900">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-ink-500">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? "card-pad" : ""}>{children}</div>
    </section>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-ink-500">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label ?? "Loading…"}
    </div>
  );
}

export function EmptyState({
  title, description, action, icon,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-12 text-center">
      <div className="text-ink-300">{icon ?? <Info className="h-7 w-7" />}</div>
      <p className="text-sm font-medium text-ink-800">{title}</p>
      {description && <p className="max-w-md text-sm text-ink-500">{description}</p>}
      {action}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

export function Field({
  label, hint, children, className = "",
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-ink-500">{hint}</span>}
    </label>
  );
}

/* ------------------------------------------------------------------- modal */

export function Modal({
  open, onClose, title, children, footer, wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink-950/40 p-0 sm:items-center sm:p-4">
      <div
        className={`flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-2xl bg-surface shadow-xl sm:rounded-2xl ${
          wide ? "sm:max-w-4xl" : "sm:max-w-lg"
        }`}
      >
        <header className="flex items-center justify-between border-b border-ink-200 px-4 py-3">
          <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
          <button className="btn-ghost btn-sm" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">{children}</div>
        {footer && (
          <footer className="flex flex-wrap justify-end gap-2 border-t border-ink-200 bg-ink-50 px-4 py-3">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ toasts */

type Toast = { id: number; kind: "ok" | "error" | "info"; message: string };
const ToastContext = createContext<{ push: (kind: Toast["kind"], message: string) => void } | null>(
  null,
);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((kind: Toast["kind"], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, kind, message }]);
    setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 6000);
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast ${
              toast.kind === "ok"
                ? "toast-ok"
                : toast.kind === "error"
                  ? "toast-error"
                  : "toast-info"
            }`}
          >
            {toast.kind === "ok" ? (
              <Check className="mt-0.5 h-4 w-4 shrink-0" />
            ) : (
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            )}
            <span>{toast.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  return (
    context ?? {
      push: (_kind: Toast["kind"], message: string) => console.warn(message),
    }
  );
}

/* -------------------------------------------------------------- pagination */

export function Pagination({
  page, pageSize, total, onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total === 0) return null;
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-ink-200 px-4 py-2.5 text-xs text-ink-600">
      <span className="tabular">
        {first}–{last} of {total.toLocaleString()}
      </span>
      <div className="flex items-center gap-1">
        <button className="btn-secondary btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <span className="px-2 tabular">
          {page} / {pages}
        </span>
        <button
          className="btn-secondary btn-sm"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
