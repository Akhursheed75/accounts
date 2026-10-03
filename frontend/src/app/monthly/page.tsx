"use client";

import { AlertTriangle, CalendarDays, FileSpreadsheet, Loader2, Pencil } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/shell";
import { Card, ErrorNote, Spinner, StatusBadge, useToast } from "@/components/ui";
import { api, downloadUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime, money } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { MonthBucket, MonthDay, MonthDetail, MonthSummary, Shop } from "@/lib/types";

/** "$1,240.00" in the USD view, or "—" while no rate is set for the month. */
function usd(value: string | null) {
  return value === null ? "—" : money(value, "USD");
}

/** The original currencies under a USD figure, so the conversion can be checked. */
function originals(usdPart: string, nioPart: string) {
  const parts = [];
  if (Number(usdPart)) parts.push(money(usdPart, "USD"));
  if (Number(nioPart)) parts.push(money(nioPart, "NIO"));
  return parts.join(" + ");
}

export default function MonthlyRecordsPage() {
  const { can } = useAuth();
  const toast = useToast();

  const months = useApi(
    () => api.get<{ previous_months: number; months: MonthSummary[] }>("/monthly"),
    [],
  );
  const shops = useApi(() => api.get<Shop[]>("/shops"), []);

  const [month, setMonth] = useState<string>("");
  const [shopId, setShopId] = useState("");

  useEffect(() => {
    if (!month && months.data?.months.length) setMonth(months.data.months[0].month);
  }, [month, months.data]);

  const detail = useApi(
    () =>
      month
        ? api.get<MonthDetail>(`/monthly/${month}`, { shop_id: shopId || undefined })
        : Promise.resolve(null),
    [month, shopId],
  );

  const data = detail.data;
  const hasRate = Boolean(data?.rate);

  return (
    <>
      <PageHeader
        title="Monthly records"
        description={`Every day of the month in one sheet, with totals in US dollars. The current month and the ${
          months.data?.previous_months ?? 3
        } before it are kept here.`}
        actions={
          can("report.export") && month ? (
            <a
              className="btn-primary btn-sm"
              href={downloadUrl(`/monthly/${month}/export`, { shop_id: shopId || undefined })}
            >
              <FileSpreadsheet className="h-3.5 w-3.5" />
              Download Excel
            </a>
          ) : null
        }
      />

      <ErrorNote error={months.error} />

      {/* Month picker: one chip per month, newest first. */}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Month">
          {(months.data?.months ?? []).map((m) => {
            const active = m.month === month;
            return (
              <button
                key={m.month}
                role="tab"
                aria-selected={active}
                onClick={() => setMonth(m.month)}
                className={`rounded-lg border px-3 py-2 text-left transition ${
                  active
                    ? "border-brand-600 bg-brand-50 text-brand-900"
                    : "border-ink-200 bg-surface text-ink-700 hover:bg-ink-100"
                }`}
              >
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  <CalendarDays className="h-3.5 w-3.5" />
                  {m.label}
                </span>
                <span className="mt-0.5 block text-[11px] text-ink-500">
                  {m.is_current ? "This month · " : ""}
                  {m.sheet_count} {m.sheet_count === 1 ? "sheet" : "sheets"}
                  {m.rate ? "" : " · no rate"}
                </span>
              </button>
            );
          })}
        </div>
        {(shops.data?.length ?? 0) > 1 && (
          <label className="ml-auto block w-full sm:w-56">
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
        )}
      </div>

      {month && (
        <RateBar
          month={month}
          label={data?.label ?? ""}
          rate={data?.rate ?? null}
          updatedAt={data?.rate_updated_at ?? null}
          canEdit={can("settings.manage")}
          onSaved={() => {
            toast.push("ok", "Exchange rate saved. USD figures updated.");
            detail.reload();
            months.reload();
          }}
        />
      )}

      <ErrorNote error={detail.error} />
      {detail.loading && !data && <Spinner label="Loading the month…" />}

      {data && (
        <div className="space-y-4">
          <Totals totals={data.totals} hasRate={hasRate} />
          <DayTable data={data} hasRate={hasRate} />
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------- rate bar */

function RateBar({
  month, label, rate, updatedAt, canEdit, onSaved,
}: {
  month: string;
  label: string;
  rate: string | null;
  updatedAt: string | null;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setEditing(false);
    setError(null);
    setValue(rate ? String(Number(rate)) : "");
  }, [month, rate]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.put(`/monthly/${month}/rate`, { nio_per_usd: value.replace(",", ".").trim() });
      setEditing(false);
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const missing = !rate;
  return (
    <div
      className={`mb-4 rounded-xl border px-4 py-3 ${
        missing ? "border-amber-300 bg-amber-50" : "border-ink-200 bg-surface"
      }`}
    >
      {editing ? (
        <form onSubmit={save} className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="label">C$ per $1 for {label}</span>
            <div className="relative">
              <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-ink-400">
                C$
              </span>
              <input
                autoFocus
                className="input tabular w-40 pl-8"
                inputMode="decimal"
                placeholder="36.6243"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                required
              />
            </div>
          </label>
          <button type="submit" className="btn-primary btn-sm" disabled={busy}>
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Save rate
          </button>
          <button type="button" className="btn-secondary btn-sm" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <p className="w-full text-xs text-ink-500">
            Used only to show figures in US dollars. Bank matching never converts currencies.
          </p>
          <div className="w-full">
            <ErrorNote error={error} />
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {missing ? (
            <p className="flex items-center gap-2 text-sm text-amber-800">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              No exchange rate set for {label}. Cordoba amounts can&apos;t be shown in US dollars
              until {canEdit ? "you set one" : "an administrator sets one"}.
            </p>
          ) : (
            <p className="text-sm text-ink-700">
              Exchange rate for {label}:{" "}
              <span className="tabular font-semibold text-ink-900">
                C$ {Number(rate).toLocaleString("en-US", { maximumFractionDigits: 4 })}
              </span>{" "}
              per $1
              {updatedAt && (
                <span className="ml-2 text-xs text-ink-500">set {dateTime(updatedAt)}</span>
              )}
            </p>
          )}
          {canEdit && (
            <button
              className={`${missing ? "btn-primary" : "btn-secondary"} btn-sm ml-auto`}
              onClick={() => setEditing(true)}
            >
              <Pencil className="h-3.5 w-3.5" />
              {missing ? "Set rate" : "Change"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- totals */

function Totals({ totals, hasRate }: { totals: MonthBucket; hasRate: boolean }) {
  const tiles = [
    {
      title: "Sales",
      value: totals.sales_in_usd,
      usdPart: totals.sales_usd,
      nioPart: totals.sales_nio,
      footer: `${totals.sheets} ${totals.sheets === 1 ? "sheet" : "sheets"}`,
    },
    {
      title: "Payments received",
      value: totals.received_in_usd,
      usdPart: String(Number(totals.bank_usd) + Number(totals.cash_usd)),
      nioPart: String(Number(totals.bank_nio) + Number(totals.cash_nio)),
      footer: "Bank and cash together",
    },
    {
      title: "Of which cash",
      value: totals.cash_in_usd,
      usdPart: totals.cash_usd,
      nioPart: totals.cash_nio,
      footer:
        totals.pending_cash > 0
          ? `${totals.pending_cash} still waiting to be banked`
          : "All cash matched to a deposit",
    },
    {
      title: "Expenses",
      value: totals.expenses_in_usd,
      usdPart: totals.expenses_usd,
      nioPart: totals.expenses_nio,
      footer: "Paid out by the shops",
    },
  ];
  return (
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {tiles.map((tile) => (
        <div key={tile.title} className="card card-pad">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-500">{tile.title}</p>
          {hasRate ? (
            <p className="tabular mt-1 text-2xl font-semibold text-ink-900">{usd(tile.value)}</p>
          ) : (
            <div className="tabular mt-1 space-y-0.5 text-lg font-semibold text-ink-900">
              <p>{money(tile.usdPart, "USD")}</p>
              <p>{money(tile.nioPart, "NIO")}</p>
            </div>
          )}
          {hasRate && (
            <p className="tabular mt-0.5 text-xs text-ink-500">
              {originals(tile.usdPart, tile.nioPart) || "Nothing recorded"}
            </p>
          )}
          <p className="mt-2 border-t border-ink-100 pt-2 text-xs text-ink-500">{tile.footer}</p>
        </div>
      ))}
    </section>
  );
}

/* ------------------------------------------------------------ day table */

const COLUMNS: { key: "sales" | "bank" | "cash" | "received" | "expenses"; label: string }[] = [
  { key: "sales", label: "Sales" },
  { key: "bank", label: "Bank" },
  { key: "cash", label: "Cash" },
  { key: "received", label: "Received" },
  { key: "expenses", label: "Expenses" },
];

function cell(bucket: MonthBucket, key: (typeof COLUMNS)[number]["key"]) {
  switch (key) {
    case "sales":
      return { usd: bucket.sales_in_usd, a: bucket.sales_usd, b: bucket.sales_nio };
    case "bank":
      return { usd: bucket.bank_in_usd, a: bucket.bank_usd, b: bucket.bank_nio };
    case "cash":
      return { usd: bucket.cash_in_usd, a: bucket.cash_usd, b: bucket.cash_nio };
    case "received":
      return {
        usd: bucket.received_in_usd,
        a: String(Number(bucket.bank_usd) + Number(bucket.cash_usd)),
        b: String(Number(bucket.bank_nio) + Number(bucket.cash_nio)),
      };
    case "expenses":
      return { usd: bucket.expenses_in_usd, a: bucket.expenses_usd, b: bucket.expenses_nio };
  }
}

function Amount({ bucket, column, hasRate, strong = false }: {
  bucket: MonthBucket;
  column: (typeof COLUMNS)[number]["key"];
  hasRate: boolean;
  strong?: boolean;
}) {
  const { usd: inUsd, a, b } = cell(bucket, column);
  const empty = !Number(a) && !Number(b);
  if (empty) return <span className="text-ink-300">–</span>;
  if (!hasRate) {
    return (
      <span className={`tabular block leading-tight ${strong ? "font-semibold" : ""}`}>
        {Number(a) ? <span className="block">{money(a, "USD")}</span> : null}
        {Number(b) ? <span className="block">{money(b, "NIO")}</span> : null}
      </span>
    );
  }
  return (
    <span className="tabular block leading-tight">
      <span className={`block ${strong ? "font-semibold" : "font-medium"} text-ink-900`}>
        {usd(inUsd)}
      </span>
      <span className="block text-[11px] text-ink-500">{originals(a, b)}</span>
    </span>
  );
}

function Status({ bucket }: { bucket: MonthBucket }) {
  const items = [
    { status: "MATCHED", count: bucket.matched },
    { status: "POSSIBLE", count: bucket.possible },
    { status: "UNMATCHED", count: bucket.unmatched },
    { status: "PENDING_DEPOSIT", count: bucket.pending_cash },
  ].filter((item) => item.count > 0);
  if (items.length === 0) return null;
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

function sheetsLink(day: MonthDay) {
  return `/accounting?date_from=${day.date}&date_to=${day.date}`;
}

function DayTable({ data, hasRate }: { data: MonthDetail; hasRate: boolean }) {
  return (
    <Card
      padded={false}
      title={`${data.label}${data.shop_name ? ` · ${data.shop_name}` : ""}`}
      description={
        hasRate
          ? "Each figure in US dollars, with the original $ and C$ amounts underneath."
          : "Shown in each currency until the month's exchange rate is set."
      }
    >
      {/* Table on wide screens */}
      <div className="hidden table-scroll md:block">
        <table className="w-full">
          <thead className="border-b border-ink-200 bg-ink-50">
            <tr>
              <th className="th">Day</th>
              <th className="th text-right">Sheets</th>
              {COLUMNS.map((c) => (
                <th key={c.key} className="th text-right">
                  {c.label}
                  {hasRate ? " (USD)" : ""}
                </th>
              ))}
              <th className="th">Payments</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {data.days.map((day) => {
              const weekend = day.weekday === "Sat" || day.weekday === "Sun";
              return (
                <tr
                  key={day.date}
                  className={`${day.is_future ? "opacity-40" : ""} ${weekend ? "bg-ink-50/60" : ""}`}
                >
                  <td className="td">
                    <span className="tabular inline-block w-6 font-semibold text-ink-900">
                      {day.day}
                    </span>
                    <span className="text-xs text-ink-500">{day.weekday}</span>
                  </td>
                  <td className="td tabular text-right">
                    {day.sheets > 0 ? (
                      <Link className="text-brand-700 hover:underline" href={sheetsLink(day)}>
                        {day.sheets}
                      </Link>
                    ) : (
                      <span className="text-ink-300">0</span>
                    )}
                  </td>
                  {COLUMNS.map((c) => (
                    <td key={c.key} className="td text-right align-top">
                      <Amount bucket={day} column={c.key} hasRate={hasRate} />
                    </td>
                  ))}
                  <td className="td">
                    <Status bucket={day} />
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot className="border-t-2 border-ink-300 bg-ink-50">
            <tr>
              <td className="td font-semibold">Month total</td>
              <td className="td tabular text-right font-semibold">{data.totals.sheets}</td>
              {COLUMNS.map((c) => (
                <td key={c.key} className="td text-right align-top">
                  <Amount bucket={data.totals} column={c.key} hasRate={hasRate} strong />
                </td>
              ))}
              <td className="td">
                <Status bucket={data.totals} />
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Cards on phones: only the days with sheets, so the list stays short. */}
      <ul className="divide-y divide-ink-100 md:hidden">
        {data.days.filter((d) => d.sheets > 0).length === 0 && (
          <li className="px-4 py-6 text-center text-sm text-ink-500">No sheets this month yet.</li>
        )}
        {data.days
          .filter((d) => d.sheets > 0)
          .map((day) => (
            <li key={day.date} className="px-4 py-3">
              <Link href={sheetsLink(day)} className="flex items-center justify-between">
                <span className="text-sm font-medium">
                  {day.day} · {day.weekday}
                </span>
                <span className="text-xs text-ink-500">
                  {day.sheets} {day.sheets === 1 ? "sheet" : "sheets"}
                </span>
              </Link>
              <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
                {COLUMNS.map((c) => (
                  <div key={c.key} className="flex justify-between gap-2">
                    <dt className="text-ink-500">{c.label}</dt>
                    <dd className="text-right">
                      <Amount bucket={day} column={c.key} hasRate={hasRate} />
                    </dd>
                  </div>
                ))}
              </dl>
              <div className="mt-2">
                <Status bucket={day} />
              </div>
            </li>
          ))}
        <li className="bg-ink-50 px-4 py-3">
          <p className="text-sm font-semibold">Month total</p>
          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
            {COLUMNS.map((c) => (
              <div key={c.key} className="flex justify-between gap-2">
                <dt className="text-ink-500">{c.label}</dt>
                <dd className="text-right">
                  <Amount bucket={data.totals} column={c.key} hasRate={hasRate} strong />
                </dd>
              </div>
            ))}
          </dl>
        </li>
      </ul>
    </Card>
  );
}
