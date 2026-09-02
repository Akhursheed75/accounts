"use client";

import { Search } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/shell";
import { TransactionTable } from "@/components/transaction-table";
import { Card, EmptyState, ErrorNote, Pagination, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi, useDebounced } from "@/lib/hooks";
import type { Bank, Page as ApiPage, Transaction } from "@/lib/types";

export default function TransactionsPage() {
  const [bankId, setBankId] = useState("");
  const [currency, setCurrency] = useState("");
  const [status, setStatus] = useState("");
  const [direction, setDirection] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [amountMin, setAmountMin] = useState("");
  const [amountMax, setAmountMax] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const debounced = useDebounced(search);

  const banks = useApi(() => api.get<Bank[]>("/banks"), []);
  const { data, error, loading } = useApi(
    () =>
      api.get<ApiPage<Transaction>>("/bank-transactions", {
        bank_id: bankId || undefined,
        currency_code: currency || undefined,
        match_status: status || undefined,
        direction: direction || undefined,
        date_from: from || undefined,
        date_to: to || undefined,
        amount_min: amountMin || undefined,
        amount_max: amountMax || undefined,
        search: debounced || undefined,
        page,
        page_size: 50,
      }),
    [bankId, currency, status, direction, from, to, amountMin, amountMax, debounced, page],
  );

  const reset = () => setPage(1);

  return (
    <>
      <PageHeader
        title="Bank transactions"
        description="Every line extracted from the uploaded statements."
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block">
            <span className="label">Bank</span>
            <select className="input" value={bankId} onChange={(e) => { setBankId(e.target.value); reset(); }}>
              <option value="">All banks</option>
              {(banks.data ?? []).map((bank) => (
                <option key={bank.id} value={bank.id}>{bank.code}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Currency</span>
            <select className="input" value={currency} onChange={(e) => { setCurrency(e.target.value); reset(); }}>
              <option value="">Both currencies</option>
              <option value="USD">USD $</option>
              <option value="NIO">Cordoba C$</option>
            </select>
          </label>
          <label className="block">
            <span className="label">Match status</span>
            <select className="input" value={status} onChange={(e) => { setStatus(e.target.value); reset(); }}>
              <option value="">Any</option>
              <option value="MATCHED">Matched</option>
              <option value="POSSIBLE">Possible match</option>
              <option value="UNMATCHED">Unmatched</option>
              <option value="IGNORED">Ignored</option>
            </select>
          </label>
          <label className="block">
            <span className="label">Direction</span>
            <select className="input" value={direction} onChange={(e) => { setDirection(e.target.value); reset(); }}>
              <option value="">In and out</option>
              <option value="CREDIT">Money in</option>
              <option value="DEBIT">Money out</option>
            </select>
          </label>
          <label className="block">
            <span className="label">From</span>
            <input type="date" className="input" value={from} onChange={(e) => { setFrom(e.target.value); reset(); }} />
          </label>
          <label className="block">
            <span className="label">To</span>
            <input type="date" className="input" value={to} onChange={(e) => { setTo(e.target.value); reset(); }} />
          </label>
          <label className="block">
            <span className="label">Amount from</span>
            <input className="input tabular" inputMode="decimal" value={amountMin} onChange={(e) => { setAmountMin(e.target.value); reset(); }} placeholder="0.00" />
          </label>
          <label className="block">
            <span className="label">Amount to</span>
            <input className="input tabular" inputMode="decimal" value={amountMax} onChange={(e) => { setAmountMax(e.target.value); reset(); }} placeholder="0.00" />
          </label>
          <label className="block sm:col-span-2 lg:col-span-4">
            <span className="label">Search description or reference</span>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
              <input
                className="input pl-8"
                value={search}
                onChange={(e) => { setSearch(e.target.value); reset(); }}
                placeholder="e.g. Pago de pacas, RAPIBAC, 48366907"
              />
            </div>
          </label>
        </div>
      </Card>

      <ErrorNote error={error} />

      <Card padded={false}>
        {loading && !data && <div className="p-5"><Spinner /></div>}
        {data && data.items.length === 0 && (
          <EmptyState title="Nothing matches these filters" description="Try widening the date range." />
        )}
        {data && data.items.length > 0 && (
          <>
            <TransactionTable rows={data.items} />
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}
