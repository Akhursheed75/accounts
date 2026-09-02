"use client";

import { CurrencyTag, StatusBadge } from "./ui";
import { money, shortDate } from "@/lib/format";
import type { Transaction } from "@/lib/types";

export function TransactionTable({
  rows, onSelect, selectLabel = "Match",
}: {
  rows: Transaction[];
  onSelect?: (txn: Transaction) => void;
  selectLabel?: string;
}) {
  return (
    <>
      <div className="hidden table-scroll md:block">
        <table className="w-full">
          <thead className="border-b border-ink-200 bg-ink-50">
            <tr>
              <th className="th">Date</th>
              <th className="th">Bank</th>
              <th className="th">Description</th>
              <th className="th">Reference</th>
              <th className="th text-right">Debit</th>
              <th className="th text-right">Credit</th>
              <th className="th">Currency</th>
              <th className="th">Status</th>
              {onSelect && <th className="th"></th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {rows.map((txn) => (
              <tr key={txn.id} className="hover:bg-ink-50">
                <td className="td">{shortDate(txn.txn_date)}</td>
                <td className="td font-medium">{txn.bank_code}</td>
                <td className="td max-w-xs truncate" title={txn.description}>
                  {txn.description || "—"}
                  {txn.extraction_confidence !== null && txn.extraction_confidence < 90 && (
                    <span
                      className="ml-1.5 rounded bg-amber-50 px-1 py-0.5 text-[10px] font-medium text-amber-800"
                      title="Read by OCR and not confirmed by the statement's running balance"
                    >
                      OCR {txn.extraction_confidence}%
                    </span>
                  )}
                </td>
                <td className="td font-mono text-xs">{txn.reference || txn.external_id || "—"}</td>
                <td className="td tabular text-right">
                  {Number(txn.debit) > 0 ? money(txn.debit) : "—"}
                </td>
                <td className="td tabular text-right font-medium">
                  {Number(txn.credit) > 0 ? money(txn.credit) : "—"}
                </td>
                <td className="td"><CurrencyTag code={txn.currency_code} /></td>
                <td className="td"><StatusBadge status={txn.match_status} /></td>
                {onSelect && (
                  <td className="td text-right">
                    <button className="btn-secondary btn-sm" onClick={() => onSelect(txn)}>
                      {selectLabel}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="divide-y divide-ink-100 md:hidden">
        {rows.map((txn) => (
          <li key={txn.id} className="px-4 py-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{txn.description || "—"}</p>
                <p className="mt-0.5 text-xs text-ink-500">
                  {shortDate(txn.txn_date)} · {txn.bank_code}
                  {txn.reference ? ` · ${txn.reference}` : ""}
                </p>
              </div>
              <div className="text-right">
                <p className="tabular text-sm font-semibold">
                  {money(txn.amount, txn.currency_code)}
                </p>
                <p className="text-xs text-ink-500">{txn.direction === "CREDIT" ? "received" : "paid out"}</p>
              </div>
            </div>
            <div className="mt-2 flex items-center justify-between gap-2">
              <StatusBadge status={txn.match_status} />
              {onSelect && (
                <button className="btn-secondary btn-sm" onClick={() => onSelect(txn)}>
                  {selectLabel}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
