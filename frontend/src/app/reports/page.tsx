"use client";

import { Download, FileSpreadsheet, FileText } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/shell";
import { Card, EmptyState, ErrorNote, Spinner } from "@/components/ui";
import { api, downloadUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { daysAgo, money, today } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Bank, ReportResult, Shop } from "@/lib/types";

export default function ReportsPage() {
  const { can } = useAuth();
  const [reportKey, setReportKey] = useState("reconciliation-summary");
  const [from, setFrom] = useState(daysAgo(30));
  const [to, setTo] = useState(today());
  const [shopId, setShopId] = useState("");
  const [bankId, setBankId] = useState("");
  const [currency, setCurrency] = useState("");

  const index = useApi(() => api.get<{ key: string; title: string }[]>("/reports"), []);
  const shops = useApi(() => api.get<Shop[]>("/shops"), []);
  const banks = useApi(() => api.get<Bank[]>("/banks"), []);

  const query = {
    date_from: from || undefined,
    date_to: to || undefined,
    shop_id: shopId || undefined,
    bank_id: bankId || undefined,
    currency_code: currency || undefined,
  };

  const { data, error, loading } = useApi(
    () => api.get<ReportResult>(`/reports/${reportKey}`, query),
    [reportKey, from, to, shopId, bankId, currency],
  );

  return (
    <>
      <PageHeader title="Reports" description="Filter, review on screen, then export." />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <label className="block xl:col-span-2">
            <span className="label">Report</span>
            <select className="input" value={reportKey} onChange={(e) => setReportKey(e.target.value)}>
              {(index.data ?? []).map((report) => (
                <option key={report.key} value={report.key}>{report.title}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">From</span>
            <input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">To</span>
            <input type="date" className="input" value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">Shop</span>
            <select className="input" value={shopId} onChange={(e) => setShopId(e.target.value)}>
              <option value="">All shops</option>
              {(shops.data ?? []).map((shop) => (
                <option key={shop.id} value={shop.id}>{shop.name}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Bank</span>
            <select className="input" value={bankId} onChange={(e) => setBankId(e.target.value)}>
              <option value="">All banks</option>
              {(banks.data ?? []).map((bank) => (
                <option key={bank.id} value={bank.id}>{bank.code}</option>
              ))}
            </select>
          </label>
        </div>
        {can("report.export") && (
          <div className="mt-3 flex flex-wrap gap-2 border-t border-ink-200 pt-3">
            <a
              className="btn-secondary btn-sm"
              href={downloadUrl(`/reports/${reportKey}`, { ...query, format: "xlsx" })}
            >
              <FileSpreadsheet className="h-3.5 w-3.5" />
              Export Excel
            </a>
            <a
              className="btn-secondary btn-sm"
              href={downloadUrl(`/reports/${reportKey}`, { ...query, format: "pdf" })}
            >
              <FileText className="h-3.5 w-3.5" />
              Export PDF
            </a>
          </div>
        )}
      </Card>

      <ErrorNote error={error} />
      {loading && !data && <Spinner />}

      {data && (
        <>
          {Object.keys(data.totals).length > 0 && (
            <Card className="mb-4" title="Totals" description="Currencies are reported separately and never added together.">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(data.totals).map(([group, values]) => (
                  <div key={group} className="rounded-lg border border-ink-200 p-3">
                    <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
                      {group.replace(/_/g, " ")}
                    </p>
                    {typeof values === "string" ? (
                      <p className="tabular mt-1 text-lg font-semibold">{values}</p>
                    ) : (
                      <dl className="mt-1 space-y-0.5">
                        {Object.entries(values).map(([key, value]) => (
                          <div key={key} className="flex justify-between gap-3 text-sm">
                            <dt className="text-ink-600">{key}</dt>
                            <dd className="tabular font-medium">
                              {money(value, key === "USD" || key === "NIO" ? key : undefined)}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card title={data.title} description={data.description} padded={false}>
            {data.rows.length === 0 ? (
              <EmptyState title="No rows" description="Nothing matches these filters." />
            ) : (
              <div className="table-scroll">
                <table className="w-full">
                  <thead className="border-b border-ink-200 bg-ink-50">
                    <tr>
                      {data.columns.map((column) => (
                        <th
                          key={column.key}
                          className={`th ${["money", "number"].includes(column.kind) ? "text-right" : ""}`}
                        >
                          {column.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-100">
                    {data.rows.slice(0, 500).map((row, index) => (
                      <tr key={index} className="hover:bg-ink-50">
                        {data.columns.map((column) => (
                          <td
                            key={column.key}
                            className={`td ${
                              ["money", "number"].includes(column.kind) ? "tabular text-right" : ""
                            }`}
                          >
                            {String(row[column.key] ?? "—")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {data.rows.length > 500 && (
                  <p className="border-t border-ink-200 px-4 py-2 text-xs text-ink-500">
                    Showing the first 500 of {data.rows.length} rows. Export for the full set.
                  </p>
                )}
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
