"use client";

import { useState } from "react";

import { PageHeader } from "@/components/shell";
import { Card, EmptyState, ErrorNote, Pagination, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, titleCase } from "@/lib/format";
import { useApi, useDebounced } from "@/lib/hooks";
import type { AuditRow, Page as ApiPage } from "@/lib/types";

export default function AuditPage() {
  const [action, setAction] = useState("");
  const [module, setModule] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const debounced = useDebounced(search);

  const actions = useApi(() => api.get<string[]>("/audit-logs/actions"), []);
  const { data, error, loading } = useApi(
    () =>
      api.get<ApiPage<AuditRow>>("/audit-logs", {
        action: action || undefined,
        module: module || undefined,
        date_from: from || undefined,
        date_to: to || undefined,
        search: debounced || undefined,
        page,
        page_size: 50,
      }),
    [action, module, from, to, debounced, page],
  );

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Every sign-in, financial edit and reconciliation decision, with who did it and when."
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="block">
            <span className="label">Action</span>
            <select className="input" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
              <option value="">All actions</option>
              {(actions.data ?? []).map((value) => (
                <option key={value} value={value}>{titleCase(value)}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Module</span>
            <select className="input" value={module} onChange={(e) => { setModule(e.target.value); setPage(1); }}>
              <option value="">All modules</option>
              {["auth", "users", "shops", "banks", "accounting", "statements", "reconciliation", "reports", "settings"].map((value) => (
                <option key={value} value={value}>{titleCase(value)}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">From</span>
            <input type="date" className="input" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }} />
          </label>
          <label className="block">
            <span className="label">To</span>
            <input type="date" className="input" value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} />
          </label>
          <label className="block">
            <span className="label">Search</span>
            <input className="input" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Summary or email" />
          </label>
        </div>
      </Card>

      <ErrorNote error={error} />

      <Card padded={false}>
        {loading && !data && <div className="p-5"><Spinner /></div>}
        {data && data.items.length === 0 && (
          <EmptyState title="No entries" description="Nothing recorded for these filters." />
        )}
        {data && data.items.length > 0 && (
          <>
            <ul className="divide-y divide-ink-100">
              {data.items.map((entry) => (
                <li key={entry.id} className="px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm text-ink-900">
                        <span className="font-medium">{titleCase(entry.action)}</span>
                        {entry.summary ? ` — ${entry.summary}` : ""}
                      </p>
                      <p className="mt-0.5 text-xs text-ink-500">
                        {entry.user_name ?? entry.user_email ?? "system"} · {entry.module}
                        {entry.record_type ? ` · ${entry.record_type} #${entry.record_id}` : ""}
                        {entry.ip_address ? ` · ${entry.ip_address}` : ""}
                      </p>
                    </div>
                    <span className="whitespace-nowrap text-xs text-ink-500">
                      {dateTime(entry.created_at)}
                    </span>
                  </div>
                  {(entry.old_values || entry.new_values) && (
                    <details className="mt-1.5">
                      <summary className="cursor-pointer text-xs text-brand-700">
                        What changed
                      </summary>
                      <div className="mt-1.5 grid gap-2 sm:grid-cols-2">
                        {entry.old_values && (
                          <pre className="overflow-x-auto rounded bg-red-50 p-2 text-[11px] text-red-900">
                            {JSON.stringify(entry.old_values, null, 2)}
                          </pre>
                        )}
                        {entry.new_values && (
                          <pre className="overflow-x-auto rounded bg-emerald-50 p-2 text-[11px] text-emerald-900">
                            {JSON.stringify(entry.new_values, null, 2)}
                          </pre>
                        )}
                      </div>
                    </details>
                  )}
                </li>
              ))}
            </ul>
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}
