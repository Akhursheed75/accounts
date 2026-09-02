"use client";

import { ArrowRight, Ban, Link2, Play, RotateCcw, Search } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/shell";
import {
  Card, CurrencyTag, EmptyState, ErrorNote, Modal, Pagination, Spinner, StatusBadge, useToast,
} from "@/components/ui";
import { TransactionTable } from "@/components/transaction-table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, shortDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type {
  Bank, Match, Page as ApiPage, ReconciliationRow, Shop, Transaction, TransferSide,
} from "@/lib/types";

export default function ReconciliationPage() {
  const { can } = useAuth();
  const toast = useToast();
  const [shopId, setShopId] = useState("");
  const [bankId, setBankId] = useState("");
  const [currency, setCurrency] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const [running, setRunning] = useState(false);
  const [manualFor, setManualFor] = useState<TransferSide | null>(null);

  const shops = useApi(() => api.get<Shop[]>("/shops"), []);
  const banks = useApi(() => api.get<Bank[]>("/banks"), []);
  const { data, error, loading, reload } = useApi(
    () =>
      api.get<ApiPage<ReconciliationRow>>("/reconciliation", {
        shop_id: shopId || undefined,
        bank_id: bankId || undefined,
        currency_code: currency || undefined,
        status: status || undefined,
        date_from: from || undefined,
        date_to: to || undefined,
        page,
        page_size: 25,
      }),
    [shopId, bankId, currency, status, from, to, page],
  );

  async function runMatching() {
    setRunning(true);
    try {
      const summary = await api.post<Record<string, number>>("/reconciliation/run", {
        shop_id: shopId ? Number(shopId) : null,
        bank_id: bankId ? Number(bankId) : null,
        date_from: from || null,
        date_to: to || null,
      });
      toast.push(
        "ok",
        `Examined ${summary.examined}: ${summary.matched} matched, ` +
          `${(summary.possible ?? 0) + (summary.ambiguous ?? 0)} need a decision, ` +
          `${summary.unmatched} with no candidate.`,
      );
      reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Matching failed.");
    } finally {
      setRunning(false);
    }
  }

  async function act(action: () => Promise<unknown>, okMessage: string) {
    try {
      await action();
      toast.push("ok", okMessage);
      reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "That did not work.");
    }
  }

  return (
    <>
      <PageHeader
        title="Reconciliation"
        description="Each shop payment beside the bank transaction it belongs to."
        actions={
          can("reconciliation.match") && (
            <button className="btn-primary btn-sm" onClick={runMatching} disabled={running}>
              <Play className="h-3.5 w-3.5" />
              {running ? "Matching…" : "Run matching"}
            </button>
          )
        }
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <label className="block">
            <span className="label">Shop</span>
            <select className="input" value={shopId} onChange={(e) => { setShopId(e.target.value); setPage(1); }}>
              <option value="">All shops</option>
              {(shops.data ?? []).map((shop) => (
                <option key={shop.id} value={shop.id}>{shop.name}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Bank</span>
            <select className="input" value={bankId} onChange={(e) => { setBankId(e.target.value); setPage(1); }}>
              <option value="">All banks</option>
              {(banks.data ?? []).map((bank) => (
                <option key={bank.id} value={bank.id}>{bank.code}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Currency</span>
            <select className="input" value={currency} onChange={(e) => { setCurrency(e.target.value); setPage(1); }}>
              <option value="">Both</option>
              <option value="USD">USD $</option>
              <option value="NIO">Cordoba C$</option>
            </select>
          </label>
          <label className="block">
            <span className="label">Status</span>
            <select className="input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
              <option value="">Any</option>
              <option value="MATCHED">Matched</option>
              <option value="POSSIBLE">Possible</option>
              <option value="UNMATCHED">Unmatched</option>
              <option value="IGNORED">Ignored</option>
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
        </div>
      </Card>

      <ErrorNote error={error} />
      {loading && !data && <Spinner />}

      {data && data.items.length === 0 && (
        <Card padded={false}>
          <EmptyState
            title="Nothing to reconcile here"
            description="No shop payments match these filters."
          />
        </Card>
      )}

      <div className="space-y-3">
        {(data?.items ?? []).map((row) => (
          <ReconRow
            key={row.transfer.id}
            row={row}
            canMatch={can("reconciliation.match")}
            canUnmatch={can("reconciliation.unmatch")}
            onConfirm={(match) =>
              act(
                () => api.post("/reconciliation/confirm", { match_id: match.id }),
                "Match confirmed.",
              )
            }
            onUnmatch={(match, reason) =>
              act(
                () => api.post("/reconciliation/unmatch", { match_id: match.id, reason }),
                "Match undone. The history is kept.",
              )
            }
            onIgnore={(transfer) =>
              act(
                () =>
                  api.post(
                    `/reconciliation/transfers/${transfer.id}/ignore`,
                    undefined,
                    { reason: "No bank counterpart expected", undo: transfer.is_ignored },
                  ),
                transfer.is_ignored ? "Back in the exception list." : "Ignored.",
              )
            }
            onManual={() => setManualFor(row.transfer)}
          />
        ))}
      </div>

      {data && (
        <div className="mt-3 card">
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
        </div>
      )}

      <ManualMatchModal
        transfer={manualFor}
        onClose={() => setManualFor(null)}
        onDone={() => {
          setManualFor(null);
          reload();
        }}
      />
    </>
  );
}

function ReconRow({
  row, canMatch, canUnmatch, onConfirm, onUnmatch, onIgnore, onManual,
}: {
  row: ReconciliationRow;
  canMatch: boolean;
  canUnmatch: boolean;
  onConfirm: (match: Match) => void;
  onUnmatch: (match: Match, reason: string) => void;
  onIgnore: (transfer: TransferSide) => void;
  onManual: () => void;
}) {
  const [unmatching, setUnmatching] = useState(false);
  const [reason, setReason] = useState("");
  const { transfer } = row;

  return (
    <article className="card overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-200 bg-ink-50 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">{transfer.shop_name}</span>
          <span className="text-ink-400">·</span>
          <span>{shortDate(transfer.business_date)}</span>
          <span className="text-ink-400">·</span>
          <span className="font-medium">{transfer.bank_code}</span>
        </div>
        <StatusBadge status={row.status} />
      </header>

      <div className="grid gap-0 md:grid-cols-2">
        <div className="border-b border-ink-200 p-4 md:border-b-0 md:border-r">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Shop payment</p>
          <p className="tabular mt-1 text-2xl font-semibold">
            {money(transfer.amount, transfer.currency_code)}
          </p>
          <p className="mt-1 flex items-center gap-2 text-xs text-ink-500">
            <CurrencyTag code={transfer.currency_code} />
            {transfer.reference ? `Ref ${transfer.reference}` : "No reference recorded"}
          </p>
          {transfer.note && <p className="mt-1 text-xs text-ink-600">{transfer.note}</p>}
        </div>

        <div className="p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
            Bank transaction
          </p>

          {row.status === "MATCHED" && row.confirmed_transaction && row.confirmed && (
            <>
              <p className="tabular mt-1 text-2xl font-semibold text-emerald-700">
                {money(row.confirmed_transaction.amount, row.confirmed_transaction.currency_code)}
              </p>
              <p className="mt-1 text-xs text-ink-600">
                {shortDate(row.confirmed_transaction.txn_date)} ·{" "}
                {row.confirmed_transaction.description || "no description"}
                {row.confirmed_transaction.reference && ` · ${row.confirmed_transaction.reference}`}
              </p>
              <Breakdown match={row.confirmed} />
              {canUnmatch && (
                <div className="mt-2">
                  {unmatching ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        className="input h-8 max-w-xs text-xs"
                        placeholder="Why is this being undone?"
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                      />
                      <button
                        className="btn-danger btn-sm"
                        onClick={() => {
                          onUnmatch(row.confirmed!, reason);
                          setUnmatching(false);
                          setReason("");
                        }}
                      >
                        Confirm unmatch
                      </button>
                      <button className="btn-ghost btn-sm" onClick={() => setUnmatching(false)}>
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button className="btn-secondary btn-sm" onClick={() => setUnmatching(true)}>
                      <RotateCcw className="h-3.5 w-3.5" />
                      Unmatch
                    </button>
                  )}
                </div>
              )}
            </>
          )}

          {row.status === "POSSIBLE" && (
            <>
              <p className="mt-1 text-sm text-ink-700">
                {row.suggested_transactions.length} transaction
                {row.suggested_transactions.length === 1 ? "" : "s"} could be this payment. It was
                not matched automatically because more than one is equally likely.
              </p>
              <ul className="mt-2 space-y-2">
                {row.suggestions.map((match, index) => {
                  const txn = row.suggested_transactions.find(
                    (t) => t.id === match.bank_transaction_id,
                  );
                  if (!txn) return null;
                  return (
                    <li
                      key={match.id}
                      className="rounded-lg border border-amber-200 bg-amber-50/60 p-2.5"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="tabular text-sm font-semibold">
                            {money(txn.amount, txn.currency_code)} · {shortDate(txn.txn_date)}
                          </p>
                          <p className="truncate text-xs text-ink-600">
                            {txn.description || "no description"}
                            {txn.reference && ` · ${txn.reference}`}
                          </p>
                        </div>
                        {canMatch && (
                          <button className="btn-primary btn-sm" onClick={() => onConfirm(match)}>
                            Match #{index + 1}
                          </button>
                        )}
                      </div>
                      <Breakdown match={match} />
                    </li>
                  );
                })}
              </ul>
            </>
          )}

          {(row.status === "UNMATCHED" || row.status === "IGNORED") && (
            <>
              <p className="mt-1 text-2xl font-semibold text-red-700">Not found</p>
              <p className="mt-1 text-xs text-ink-600">
                No bank transaction in the allowed window has this amount, currency and bank.
              </p>
              {canMatch && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <button className="btn-secondary btn-sm" onClick={onManual}>
                    <Search className="h-3.5 w-3.5" />
                    Find it manually
                  </button>
                  <button className="btn-ghost btn-sm" onClick={() => onIgnore(transfer)}>
                    <Ban className="h-3.5 w-3.5" />
                    {transfer.is_ignored ? "Stop ignoring" : "Ignore"}
                  </button>
                </div>
              )}
            </>
          )}

          {row.history.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-ink-500">
                Previous matches ({row.history.length})
              </summary>
              <ul className="mt-1.5 space-y-1 text-xs text-ink-600">
                {row.history.map((match) => (
                  <li key={match.id}>
                    Transaction #{match.bank_transaction_id} · {match.match_type.toLowerCase()} ·
                    undone by {match.unmatched_by_name ?? "unknown"}
                    {match.note ? ` — ${match.note}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </div>
    </article>
  );
}

function Breakdown({ match }: { match: Match }) {
  if (!match.score_breakdown?.length) return null;
  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-xs text-ink-500">
        Why — {match.confidence}% confidence, {match.match_type.toLowerCase()} match
      </summary>
      <ul className="mt-1.5 space-y-0.5 text-xs text-ink-600">
        {match.score_breakdown.map((signal, index) => (
          <li key={index} className="flex gap-2">
            <span className="tabular w-8 shrink-0 text-right font-medium text-ink-500">
              {signal.points > 0 ? `+${signal.points}` : "—"}
            </span>
            <span>{signal.detail}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function ManualMatchModal({
  transfer, onClose, onDone,
}: {
  transfer: TransferSide | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [note, setNote] = useState("");
  const candidates = useApi(
    () =>
      transfer
        ? api.get<Transaction[]>(`/reconciliation/candidates/${transfer.id}`)
        : Promise.resolve([]),
    [transfer?.id],
  );

  async function pick(txn: Transaction) {
    if (!transfer) return;
    try {
      await api.post("/reconciliation/match", {
        shop_transfer_id: transfer.id,
        bank_transaction_id: txn.id,
        note: note || null,
      });
      toast.push("ok", "Matched by hand and recorded in the audit log.");
      onDone();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not match these.");
    }
  }

  return (
    <Modal
      open={Boolean(transfer)}
      onClose={onClose}
      wide
      title={
        transfer
          ? `Find the bank transaction for ${money(transfer.amount, transfer.currency_code)}`
          : "Manual match"
      }
    >
      {transfer && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg bg-ink-50 px-3 py-2 text-sm">
            <span className="font-medium">{transfer.shop_name}</span>
            <ArrowRight className="h-3.5 w-3.5 text-ink-400" />
            <span>{transfer.bank_code}</span>
            <span className="tabular font-semibold">
              {money(transfer.amount, transfer.currency_code)}
            </span>
            <span className="text-ink-500">on {shortDate(transfer.business_date)}</span>
          </div>

          <label className="mb-3 block">
            <span className="label">Reason (recorded in the audit log)</span>
            <input
              className="input"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. the bank posted it the next working day"
            />
          </label>

          <p className="mb-2 text-xs text-ink-500">
            Only {transfer.currency_code} transactions are listed. A payment in one currency can
            never be the same money as a payment in another, so the list will not offer them.
          </p>

          {candidates.loading && <Spinner />}
          {candidates.data && candidates.data.length === 0 && (
            <EmptyState
              title="No candidates"
              description="No unmatched transaction in this currency exists near that date. The statement may not have been uploaded yet."
            />
          )}
          {candidates.data && candidates.data.length > 0 && (
            <div className="-mx-4">
              <TransactionTable rows={candidates.data} onSelect={pick} selectLabel="Match this" />
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
