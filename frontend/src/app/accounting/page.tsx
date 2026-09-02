"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/shell";
import { Card, ErrorNote, EmptyState, Pagination, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, shortDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { DailyRecordRow, Page as ApiPage, Shop } from "@/lib/types";

export default function AccountingListPage() {
  const { can } = useAuth();
  const [shopId, setShopId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);

  const shops = useApi(() => api.get<Shop[]>("/shops"), []);
  const { data, error, loading } = useApi(
    () =>
      api.get<ApiPage<DailyRecordRow>>("/accounting/daily", {
        shop_id: shopId || undefined,
        date_from: from || undefined,
        date_to: to || undefined,
        status: status || undefined,
        page,
        page_size: 25,
      }),
    [shopId, from, to, status, page],
  );

  return (
    <>
      <PageHeader
        title="Daily accounting"
        description="One sheet per shop per day."
        actions={
          can("accounting.create") && (
            <Link href="/accounting/new" className="btn-primary btn-sm">
              <Plus className="h-4 w-4" />
              New sheet
            </Link>
          )
        }
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block">
            <span className="label">Shop</span>
            <select
              className="input"
              value={shopId}
              onChange={(e) => {
                setShopId(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All shops</option>
              {(shops.data ?? []).map((shop) => (
                <option key={shop.id} value={shop.id}>
                  {shop.name}
                </option>
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
            <span className="label">Status</span>
            <select className="input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
              <option value="">Any status</option>
              <option value="DRAFT">Draft</option>
              <option value="SUBMITTED">Submitted</option>
              <option value="LOCKED">Locked</option>
            </select>
          </label>
        </div>
      </Card>

      <ErrorNote error={error} />

      <Card padded={false}>
        {loading && !data && <div className="p-5"><Spinner /></div>}
        {data && data.items.length === 0 && (
          <EmptyState
            title="No sheets found"
            description="Adjust the filters, or create the first sheet for a shop."
          />
        )}
        {data && data.items.length > 0 && (
          <>
            {/* Table on wide screens */}
            <div className="hidden table-scroll md:block">
              <table className="w-full">
                <thead className="border-b border-ink-200 bg-ink-50">
                  <tr>
                    <th className="th">Date</th>
                    <th className="th">Shop</th>
                    <th className="th">Status</th>
                    <th className="th text-right">Bales</th>
                    <th className="th text-right">Sales USD</th>
                    <th className="th text-right">Sales C$</th>
                    <th className="th text-right">Banked USD</th>
                    <th className="th text-right">Banked C$</th>
                    <th className="th">Reconciliation</th>
                    <th className="th"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100">
                  {data.items.map((row) => (
                    <tr key={row.id} className="hover:bg-ink-50">
                      <td className="td">{shortDate(row.business_date)}</td>
                      <td className="td font-medium">{row.shop_name}</td>
                      <td className="td"><StatusBadge status={row.status} dot={false} /></td>
                      <td className="td tabular text-right">{row.bale_count}</td>
                      <td className="td tabular text-right">{money(row.total_sales_usd, "USD")}</td>
                      <td className="td tabular text-right">{money(row.total_sales_nio, "NIO")}</td>
                      <td className="td tabular text-right">{money(row.transfer_total_usd, "USD")}</td>
                      <td className="td tabular text-right">{money(row.transfer_total_nio, "NIO")}</td>
                      <td className="td"><ReconCounts row={row} /></td>
                      <td className="td text-right">
                        <Link href={`/accounting/${row.id}`} className="btn-secondary btn-sm">
                          Open
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Cards on phones */}
            <ul className="divide-y divide-ink-100 md:hidden">
              {data.items.map((row) => (
                <li key={row.id}>
                  <Link href={`/accounting/${row.id}`} className="block px-4 py-3 active:bg-ink-50">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{row.shop_name}</span>
                      <StatusBadge status={row.status} dot={false} />
                    </div>
                    <p className="mt-0.5 text-xs text-ink-500">{shortDate(row.business_date)}</p>
                    <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                      <div className="flex justify-between">
                        <dt className="text-ink-500">Sales $</dt>
                        <dd className="tabular">{money(row.total_sales_usd, "USD")}</dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-ink-500">Sales C$</dt>
                        <dd className="tabular">{money(row.total_sales_nio, "NIO")}</dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-ink-500">Banked $</dt>
                        <dd className="tabular">{money(row.transfer_total_usd, "USD")}</dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-ink-500">Banked C$</dt>
                        <dd className="tabular">{money(row.transfer_total_nio, "NIO")}</dd>
                      </div>
                    </dl>
                    <div className="mt-2"><ReconCounts row={row} /></div>
                  </Link>
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

function ReconCounts({ row }: { row: DailyRecordRow }) {
  const items = [
    { count: row.matched_count, status: "MATCHED" as const },
    { count: row.possible_count, status: "POSSIBLE" as const },
    { count: row.unmatched_count, status: "UNMATCHED" as const },
  ].filter((item) => item.count > 0);
  if (items.length === 0) return <span className="text-xs text-ink-400">No payments</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((item) => (
        <span key={item.status} className="inline-flex items-center gap-1">
          <StatusBadge status={item.status} />
          <span className="tabular text-xs text-ink-600">{item.count}</span>
        </span>
      ))}
    </div>
  );
}
