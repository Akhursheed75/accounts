"use client";

import { useState } from "react";

import { PageHeader } from "@/components/shell";
import { TransactionTable } from "@/components/transaction-table";
import { Card, CurrencyTag, EmptyState, ErrorNote, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { money, shortDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Bank, Shop, UnmatchedSummary } from "@/lib/types";

export default function UnmatchedPage() {
  const [shopId, setShopId] = useState("");
  const [bankId, setBankId] = useState("");
  const [currency, setCurrency] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const shops = useApi(() => api.get<Shop[]>("/shops"), []);
  const banks = useApi(() => api.get<Bank[]>("/banks"), []);
  const { data, error, loading } = useApi(
    () =>
      api.get<UnmatchedSummary>("/reconciliation/unmatched", {
        shop_id: shopId || undefined,
        bank_id: bankId || undefined,
        currency_code: currency || undefined,
        date_from: from || undefined,
        date_to: to || undefined,
      }),
    [shopId, bankId, currency, from, to],
  );

  return (
    <>
      <PageHeader
        title="Unmatched"
        description="The two exception lists — money the shops banked that the bank has no record of, and money the bank received that no shop claimed."
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
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
          <label className="block">
            <span className="label">Currency</span>
            <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
              <option value="">Both</option>
              <option value="USD">USD $</option>
              <option value="NIO">Cordoba C$</option>
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
        </div>
      </Card>

      <ErrorNote error={error} />
      {loading && !data && <Spinner />}

      {data && (
        <div className="space-y-4">
          <Card
            title="Shop payments not found in the bank"
            description={`${data.totals.shop_payments.count} payment(s) · ${money(
              data.totals.shop_payments.USD, "USD",
            )} and ${money(data.totals.shop_payments.NIO, "NIO")}`}
            padded={false}
          >
            {data.shop_payments.length === 0 ? (
              <EmptyState
                title="Every shop payment is accounted for"
                description="Nothing the shops recorded is missing from the statements."
              />
            ) : (
              <>
                <div className="hidden table-scroll md:block">
                  <table className="w-full">
                    <thead className="border-b border-ink-200 bg-ink-50">
                      <tr>
                        <th className="th">Date</th>
                        <th className="th">Shop</th>
                        <th className="th">Bank</th>
                        <th className="th">Currency</th>
                        <th className="th text-right">Amount</th>
                        <th className="th">Detail</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink-100">
                      {data.shop_payments.map((payment) => (
                        <tr key={payment.id} className="hover:bg-ink-50">
                          <td className="td">{shortDate(payment.business_date)}</td>
                          <td className="td font-medium">{payment.shop_name}</td>
                          <td className="td">
                            {payment.payment_method === "CASH" ? (
                              <StatusBadge status="PENDING_DEPOSIT" />
                            ) : (
                              payment.bank_code
                            )}
                          </td>
                          <td className="td"><CurrencyTag code={payment.currency_code} /></td>
                          <td className="td tabular text-right font-medium">
                            {money(payment.amount, payment.currency_code)}
                          </td>
                          <td className="td text-ink-600">
                            {payment.note || payment.reference || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <ul className="divide-y divide-ink-100 md:hidden">
                  {data.shop_payments.map((payment) => (
                    <li key={payment.id} className="flex items-center justify-between gap-2 px-4 py-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium">{payment.shop_name}</p>
                        <p className="text-xs text-ink-500">
                          {shortDate(payment.business_date)} ·{" "}
                          {payment.payment_method === "CASH" ? "Cash, not banked yet" : payment.bank_code}
                        </p>
                      </div>
                      <span className="tabular text-sm font-semibold">
                        {money(payment.amount, payment.currency_code)}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Card>

          <Card
            title="Bank receipts with no shop record"
            description={`${data.totals.bank_transactions.count} transaction(s) · ${money(
              data.totals.bank_transactions.USD, "USD",
            )} and ${money(data.totals.bank_transactions.NIO, "NIO")}`}
            padded={false}
          >
            {data.bank_transactions.length === 0 ? (
              <EmptyState
                title="Every bank receipt is claimed"
                description="Every incoming transaction has a shop payment behind it."
              />
            ) : (
              <TransactionTable rows={data.bank_transactions} />
            )}
          </Card>

          <p className="text-xs text-ink-500">
            Bank receipts on this list are not necessarily errors — a customer paying the company
            directly, or a transfer between the company&rsquo;s own accounts, will appear here until it is
            recorded or ignored.
          </p>
        </div>
      )}
    </>
  );
}
