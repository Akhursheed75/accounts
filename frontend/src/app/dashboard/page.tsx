"use client";

import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { StatusBar, TrendChart } from "@/components/charts";
import { PageHeader } from "@/components/shell";
import { Card, ErrorNote, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { daysAgo, money, today } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Dashboard, Shop } from "@/lib/types";

export default function DashboardPage() {
  const [from, setFrom] = useState(daysAgo(30));
  const [to, setTo] = useState(today());
  const [shopId, setShopId] = useState("");

  const shops = useApi(() => api.get<Shop[]>("/shops"), []);
  const { data, error, loading, reload } = useApi(
    () =>
      api.get<Dashboard>("/dashboard", {
        date_from: from,
        date_to: to,
        shop_id: shopId || undefined,
      }),
    [from, to, shopId],
  );

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Sales, banking and reconciliation for the selected period."
        actions={
          <button className="btn-secondary btn-sm" onClick={reload}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        }
      />

      <Card className="mb-4" padded>
        <div className="grid gap-3 sm:grid-cols-3">
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
                <option key={shop.id} value={shop.id}>
                  {shop.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Card>

      <ErrorNote error={error} />
      {loading && !data && <Spinner />}

      {data && (
        <div className="space-y-4">
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <SplitStat
              title="Sales recorded"
              usd={data.sales.USD}
              nio={data.sales.NIO}
              footer={`${data.sales.records} sheet(s) · ${data.sales.bales} bales · ${data.sales.invoices} invoices`}
            />
            <SplitStat
              title="Banked by shops"
              usd={data.shop_transfers.USD}
              nio={data.shop_transfers.NIO}
              footer="What the shops say they deposited"
            />
            <SplitStat
              title="Received by banks"
              usd={data.bank_received.USD}
              nio={data.bank_received.NIO}
              footer="Credits on the uploaded statements"
            />
            <ReconStat data={data} />
          </section>

          <Card
            title="Sales per day"
            description="Amounts are shown per currency and never combined."
          >
            <div className="grid gap-6 lg:grid-cols-2">
              <div>
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-500">
                  US dollars
                </p>
                <TrendChart
                  points={data.trend.map((p) => ({ date: p.date, value: Number(p.USD) }))}
                  currency="USD"
                  label="Sales"
                />
              </div>
              <div>
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-500">
                  Cordobas
                </p>
                <TrendChart
                  points={data.trend.map((p) => ({ date: p.date, value: Number(p.NIO) }))}
                  currency="NIO"
                  label="Sales"
                />
              </div>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="By shop" padded={false}>
              <div className="table-scroll">
                <table className="w-full">
                  <thead className="border-b border-ink-200 bg-ink-50">
                    <tr>
                      <th className="th">Shop</th>
                      <th className="th text-right">Sales USD</th>
                      <th className="th text-right">Sales C$</th>
                      <th className="th text-right">Sheets</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-100">
                    {data.shops.length === 0 && (
                      <tr>
                        <td className="td text-ink-500" colSpan={4}>
                          No sheets recorded in this period.
                        </td>
                      </tr>
                    )}
                    {data.shops.map((shop) => (
                      <tr key={shop.shop_id}>
                        <td className="td font-medium">{shop.name}</td>
                        <td className="td tabular text-right">{money(shop.USD, "USD")}</td>
                        <td className="td tabular text-right">{money(shop.NIO, "NIO")}</td>
                        <td className="td tabular text-right">{shop.records}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card title="By bank" description="What the shops recorded as deposited." padded={false}>
              <div className="table-scroll">
                <table className="w-full">
                  <thead className="border-b border-ink-200 bg-ink-50">
                    <tr>
                      <th className="th">Bank</th>
                      <th className="th text-right">USD</th>
                      <th className="th text-right">C$</th>
                      <th className="th text-right">Payments</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-100">
                    {data.banks.length === 0 && (
                      <tr>
                        <td className="td text-ink-500" colSpan={4}>
                          No bank transfers recorded in this period.
                        </td>
                      </tr>
                    )}
                    {data.banks.map((bank) => (
                      <tr key={bank.bank_id}>
                        <td className="td font-medium">{bank.code}</td>
                        <td className="td tabular text-right">{money(bank.USD, "USD")}</td>
                        <td className="td tabular text-right">{money(bank.NIO, "NIO")}</td>
                        <td className="td tabular text-right">{bank.transfer_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}

function SplitStat({
  title, usd, nio, footer,
}: {
  title: string;
  usd: string;
  nio: string;
  footer: string;
}) {
  return (
    <div className="card card-pad">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-500">{title}</p>
      <div className="mt-2 space-y-1">
        <p className="tabular text-xl font-semibold leading-tight">{money(usd, "USD")}</p>
        <p className="tabular text-xl font-semibold leading-tight text-ink-700">
          {money(nio, "NIO")}
        </p>
      </div>
      <p className="mt-2 text-xs text-ink-500">{footer}</p>
    </div>
  );
}

function ReconStat({ data }: { data: Dashboard }) {
  const counts = data.reconciliation.counts;
  const amounts = data.reconciliation.amounts;
  return (
    <div className="card card-pad">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Reconciliation</p>
        <Link href="/reconciliation" className="text-xs font-medium text-brand-700 hover:underline">
          Open
        </Link>
      </div>
      <div className="mt-2">
        <StatusBar
          segments={[
            { label: "Matched", value: counts.MATCHED ?? 0, className: "bg-emerald-500" },
            { label: "Possible", value: counts.POSSIBLE ?? 0, className: "bg-amber-500" },
            { label: "Unmatched", value: counts.UNMATCHED ?? 0, className: "bg-red-500" },
            { label: "Cash pending deposit", value: counts.PENDING_DEPOSIT ?? 0, className: "bg-sky-500" },
            { label: "Ignored", value: counts.IGNORED ?? 0, className: "bg-ink-400" },
          ]}
        />
      </div>
      <ul className="mt-3 space-y-1.5 text-xs">
        {(["MATCHED", "POSSIBLE", "UNMATCHED", "PENDING_DEPOSIT"] as const)
          .filter((state) => state !== "PENDING_DEPOSIT" || (counts[state] ?? 0) > 0)
          .map((state) => (
          <li key={state} className="flex items-center justify-between gap-2">
            <StatusBadge status={state} />
            <span className="tabular text-ink-700">
              {counts[state] ?? 0} · {money(amounts[state]?.USD, "USD")} ·{" "}
              {money(amounts[state]?.NIO, "NIO")}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
