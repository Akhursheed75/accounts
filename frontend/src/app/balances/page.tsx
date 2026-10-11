"use client";

import { AlertTriangle, Check, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/shell";
import { Card, EmptyState, ErrorNote, Spinner, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, shortDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Currency } from "@/lib/types";

type Source = "ENTERED" | "STATEMENT" | "CALCULATED" | null;

interface BalanceDay {
  date: string;
  opening: string | null;
  credits: string;
  debits: string;
  movements: number;
  closing: string | null;
  source: Source;
  statement_closing: string | null;
  entered_closing: string | null;
  difference: string | null;
}

interface AccountBalances {
  account_id: number;
  bank_code: string | null;
  bank_name: string | null;
  label: string;
  currency_code: Currency;
  latest: BalanceDay | null;
  days: BalanceDay[];
}

const SOURCE_WORDS: Record<string, string> = {
  STATEMENT: "from the statement",
  ENTERED: "typed from the bank",
  CALCULATED: "calculated",
};

function daysAgo(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

export default function BankBalancesPage() {
  const [from, setFrom] = useState(daysAgo(14));
  const [to, setTo] = useState(daysAgo(0));
  const { data, error, loading, reload } = useApi(
    () => api.get<AccountBalances[]>("/bank-balances", { date_from: from || undefined, date_to: to || undefined }),
    [from, to],
  );

  return (
    <>
      <PageHeader
        title="Bank balances"
        description="Each account's balance day by day. BAC and LAFISE print theirs on the statement; BANPRO's export has none, so type the closing balance the bank shows and the following days are calculated from it."
        actions={
          <button className="btn-secondary btn-sm" onClick={reload}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        }
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:w-1/2">
          <label className="block">
            <span className="label">From</span>
            <input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">To</span>
            <input type="date" className="input" value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
        </div>
      </Card>

      <ErrorNote error={error} />
      {loading && !data && <Spinner />}

      {data && (
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {data.map((a) => (
            <div key={a.account_id} className="card px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                {a.bank_code} · {a.label}
              </p>
              {a.latest?.closing != null ? (
                <>
                  <p className="tabular mt-1 text-xl font-semibold">{money(a.latest.closing, a.currency_code)}</p>
                  <p className="text-xs text-ink-500">
                    {shortDate(a.latest.date)} · {SOURCE_WORDS[a.latest.source ?? ""] ?? ""}
                  </p>
                </>
              ) : (
                <p className="mt-1 text-sm text-ink-500">No balance yet: type one below.</p>
              )}
            </div>
          ))}
        </div>
      )}

      {data?.map((a) => <AccountTable key={a.account_id} account={a} onChanged={reload} />)}
    </>
  );
}

function AccountTable({ account, onChanged }: { account: AccountBalances; onChanged: () => void }) {
  const { can } = useAuth();
  const canType = can("statement.upload");
  const [adding, setAdding] = useState("");
  const code = account.currency_code;

  return (
    <Card
      className="mb-4"
      padded={false}
      title={`${account.bank_code} · ${account.label}`}
      description={account.bank_name ?? undefined}
      actions={
        canType ? (
          <label className="flex items-center gap-2 text-xs text-ink-500">
            Type a balance for
            <input type="date" className="input w-auto py-1 text-xs" value={adding}
              onChange={(e) => setAdding(e.target.value)} />
          </label>
        ) : null
      }
    >
      {account.days.length === 0 && !adding ? (
        <EmptyState title="Nothing in this period" description="No statement lines or balances for these dates." />
      ) : (
        <div className="table-scroll">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-ink-200 bg-ink-50">
              <tr>
                <th className="th">Date</th>
                <th className="th text-right">Opening</th>
                <th className="th text-right">+ Credits</th>
                <th className="th text-right">− Debits</th>
                <th className="th text-right">Closing</th>
                <th className="th">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {adding && !account.days.some((d) => d.date === adding) && (
                <BalanceRow
                  account={account}
                  day={{
                    date: adding, opening: null, credits: "0", debits: "0", movements: 0, closing: null,
                    source: null, statement_closing: null, entered_closing: null, difference: null,
                  }}
                  canType={canType}
                  onChanged={() => { setAdding(""); onChanged(); }}
                />
              )}
              {account.days.map((d) => (
                <BalanceRow key={d.date} account={account} day={d} canType={canType} onChanged={onChanged} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="border-t border-ink-200 px-4 py-2 text-xs text-ink-500">
        Closing = opening + credits − debits. A typed or printed closing that disagrees with the
        calculation is flagged: a movement is missing from the uploaded statements, or a figure was
        typed wrong. All amounts in {code === "USD" ? "dollars" : "córdobas"}.
      </p>
    </Card>
  );
}

function BalanceRow({
  account, day, canType, onChanged,
}: {
  account: AccountBalances;
  day: BalanceDay;
  canType: boolean;
  onChanged: () => void;
}) {
  const toast = useToast();
  const code = account.currency_code;
  const [value, setValue] = useState(day.entered_closing ?? "");
  const [busy, setBusy] = useState(false);

  async function save(next: string) {
    const cleaned = next.replace(/[^\d.-]/g, "");
    if ((day.entered_closing ?? "") === cleaned) return;
    setBusy(true);
    try {
      await api.put(`/bank-balances/${account.account_id}/${day.date}`, {
        closing_balance: cleaned === "" ? null : cleaned,
      });
      toast.push("ok", cleaned === "" ? "Typed balance removed." : "Balance saved.");
      onChanged();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not save the balance.");
    } finally {
      setBusy(false);
    }
  }

  const amount = (v: string | null) => (v === null ? <span className="text-ink-300">–</span> : money(v, code));

  return (
    <tr className={day.difference ? "bg-amber-50" : ""}>
      <td className="td whitespace-nowrap font-medium">
        {shortDate(day.date)}
        {day.movements > 0 && <span className="ml-1 text-xs text-ink-400">({day.movements})</span>}
      </td>
      <td className="td tabular text-right">{amount(day.opening)}</td>
      <td className="td tabular text-right text-emerald-700">{Number(day.credits) ? money(day.credits, code) : ""}</td>
      <td className="td tabular text-right text-red-700">{Number(day.debits) ? money(day.debits, code) : ""}</td>
      <td className="td text-right">
        {canType && day.source !== "STATEMENT" ? (
          <div className="flex items-center justify-end gap-2">
            {day.source === "CALCULATED" && (
              <span className="tabular text-xs text-ink-500">{money(day.closing ?? "0", code)}</span>
            )}
            <input
              className="input tabular w-36 py-1 text-right text-sm"
              inputMode="decimal"
              placeholder={day.source === "CALCULATED" ? "type bank's" : "closing"}
              value={value}
              disabled={busy}
              aria-label={`Closing balance ${account.label} ${day.date}`}
              onChange={(e) => setValue(e.target.value)}
              onBlur={(e) => save(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
            />
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          </div>
        ) : (
          <span className="tabular font-semibold">{amount(day.closing)}</span>
        )}
      </td>
      <td className="td text-xs">
        {day.source && (
          <span className="inline-flex items-center gap-1 text-ink-600">
            {day.source !== "CALCULATED" && <Check className="h-3.5 w-3.5 text-emerald-600" />}
            {SOURCE_WORDS[day.source]}
          </span>
        )}
        {day.difference && (
          <p className="mt-0.5 flex items-center gap-1 font-medium text-amber-800">
            <AlertTriangle className="h-3.5 w-3.5" />
            {money(day.difference, code)} different from the calculation
          </p>
        )}
      </td>
    </tr>
  );
}
