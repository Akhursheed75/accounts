"use client";

/**
 * The daily sheet, laid out like the paper "CLOSING CASH" form the shops fill
 * in, so whoever types it in can read across from the photo line by line.
 *
 * Every amount the shop banked ends up coloured: green when it is on the bank
 * statement, amber when there is a likely line to confirm, red when it is not
 * there (or the sheet disagrees with itself), grey when that bank's statement
 * for the day has not been uploaded yet.
 */
import {
  AlertTriangle, Camera, Check, ClipboardPaste, ImagePlus, Loader2, Maximize2, Plus, RefreshCw, ScanLine,
  Trash2, X, ZoomIn,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Card, ErrorNote, Modal, StatusBadge, useToast } from "./ui";
import { cleanAmount } from "./record-form";
import { api, request } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, today } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { parseBreakdown, type Breakdown } from "@/lib/breakdown";
import type {
  BankCell, BaleType, Bank, CandidateLine, Currency, DailyRecord, PhotoUpload, SheetDraft,
  SheetPhoto, Shop,
} from "@/lib/types";

/* ----------------------------------------------------------------- helpers */

const newKey = () => Math.random().toString(36).slice(2);
const cellKey = (bankId: number | string, currency: Currency) => `${bankId}:${currency}`;
const CURRENCIES: Currency[] = ["USD", "NIO"];

function num(value: string | null | undefined): number {
  const parsed = Number(cleanAmount(value ?? ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function toUsd(usd: number, nio: number, rate: number | null): number | null {
  if (!nio) return usd;
  if (!rate) return null;
  return usd + nio / rate;
}

function usd(value: number | null) {
  return value === null ? "—" : money(value, "USD");
}

/** Status colour for a whole cell or a single chip. */
const TONE: Record<string, string> = {
  MATCHED: "border-emerald-500 bg-emerald-50 text-emerald-800",
  POSSIBLE: "border-amber-500 bg-amber-50 text-amber-900",
  UNMATCHED: "border-red-500 bg-red-50 text-red-800",
  DIFFERENT: "border-red-500 bg-red-50 text-red-800",
  PENDING_DEPOSIT: "border-sky-500 bg-sky-50 text-sky-800",
  WAITING: "border-ink-300 bg-ink-50 text-ink-600",
  NEW: "border-ink-300 bg-surface text-ink-800",
};

const CELL_WORDS: Record<string, string> = {
  MATCHED: "On the statement",
  POSSIBLE: "Confirm the match",
  UNMATCHED: "Not on the statement",
  DIFFERENT: "Detail ≠ total",
  WAITING: "Statement not uploaded",
};

interface Chip {
  key: string;
  id?: number;
  amount: string;
  status?: string;
}

interface ExpenseRow {
  key: string;
  id?: number;
  description: string;
  currency_code: Currency;
  amount: string;
}

interface BaleRow {
  key: string;
  id?: number;
  bale_type_id: number;
  name: string;
  opening: string;
  received: string;
  closing: string;
}

/* ===================================================================== form */

export function PaperSheet({ record, onSaved }: { record?: DailyRecord; onSaved?: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const { can } = useAuth();
  const editing = Boolean(record);

  const shops = useApi(() => api.get<Shop[]>("/shops"), []);
  const banks = useApi(() => api.get<Bank[]>("/banks"), []);
  const baleTypes = useApi(() => api.get<BaleType[]>("/accounting/bale-types"), []);
  const reader = useApi(() => api.get<{ available: boolean }>("/accounting/reader"), []);

  /* --------------------------------------------------------- form state */
  const [shopId, setShopId] = useState(record ? String(record.shop_id) : "");
  const [date, setDate] = useState(record?.business_date ?? today());
  const [status, setStatus] = useState(
    record?.status === "LOCKED" ? "SUBMITTED" : record?.status ?? "SUBMITTED",
  );
  const [bales, setBales] = useState(String(record?.bale_count ?? ""));
  const [invoices, setInvoices] = useState(String(record?.invoice_count ?? ""));
  const [sales, setSales] = useState(record ? record.total_sales_usd : "");
  const [other, setOther] = useState(record ? record.opening_balance_usd : "");

  const cashOf = (code: Currency) =>
    record?.transfers.filter((t) => t.payment_method === "CASH" && t.currency_code === code) ?? [];
  const [cashNio, setCashNio] = useState(sumStr(cashOf("NIO").map((t) => t.amount)));
  const [cashUsd, setCashUsd] = useState(sumStr(cashOf("USD").map((t) => t.amount)));
  const cashIds = useMemo(
    () => ({ NIO: cashOf("NIO")[0]?.id, USD: cashOf("USD")[0]?.id }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [record?.id],
  );

  const [ciCash, setCiCash] = useState(zeroBlank(record?.commercial_invoice_cash_usd));
  const [ciDeposit, setCiDeposit] = useState(zeroBlank(record?.commercial_invoice_deposit_usd));
  const [delCash, setDelCash] = useState(zeroBlank(record?.delivery_cash_usd));
  const [delTransfer, setDelTransfer] = useState(zeroBlank(record?.delivery_transfer_usd));
  const [credit, setCredit] = useState(zeroBlank(record?.credit_usd));
  const [observations, setObservations] = useState(record?.observations ?? "");
  const [closing, setClosing] = useState(record?.declared_closing_usd ?? "");

  // TRANSFERS table: the total per bank and currency, as written on the sheet.
  const [totals, setTotals] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const t of record?.bank_totals ?? []) out[cellKey(t.bank_id, t.currency_code)] = t.amount;
    return out;
  });

  // DETAIL rows: each deposit the sheet lists, as a chip.
  const [details, setDetails] = useState<Record<string, Chip[]>>(() => {
    const out: Record<string, Chip[]> = {};
    for (const t of record?.transfers ?? []) {
      if (t.payment_method !== "BANK" || t.source !== "SHEET" || t.bank_id === null) continue;
      const key = cellKey(t.bank_id, t.currency_code);
      (out[key] ??= []).push({ key: newKey(), id: t.id, amount: t.amount, status: t.match_status });
    }
    return out;
  });

  const [expenses, setExpenses] = useState<ExpenseRow[]>(
    record?.expenses.map((e) => ({
      key: newKey(), id: e.id, description: e.description || e.category,
      currency_code: e.currency_code, amount: e.amount,
    })) ?? [],
  );

  const [baleRows, setBaleRows] = useState<BaleRow[]>(
    record?.bale_records.map((b) => ({
      key: newKey(), id: b.id, bale_type_id: b.bale_type_id,
      name: b.bale_type_code ?? b.bale_type_name ?? "",
      opening: String(b.opening_qty), received: b.received_qty ? String(b.received_qty) : "",
      closing: String(b.closing_qty),
    })) ?? [],
  );

  useEffect(() => {
    if (!baleTypes.data) return;
    setBaleRows((current) => {
      const present = new Set(current.map((r) => r.bale_type_id));
      const missing = baleTypes.data!.filter((t) => !present.has(t.id));
      if (!missing.length) return current;
      return [
        ...current,
        ...missing.map((t) => ({
          key: newKey(), bale_type_id: t.id, name: t.code, opening: "", received: "", closing: "",
        })),
      ];
    });
  }, [baleTypes.data]);

  /* ------------------------------------------------------------- photos */
  const [photos, setPhotos] = useState<SheetPhoto[]>(record?.photos ?? []);
  const [newPhotoIds, setNewPhotoIds] = useState<number[]>([]);
  const [reading, setReading] = useState(false);
  const [checks, setChecks] = useState<string[]>([]);
  const [fromPhoto, setFromPhoto] = useState(false);

  const rate = useApi(
    () => api.get<{ nio_per_usd: string | null }>("/monthly/rate", { on: date }),
    [date.slice(0, 7)],
  );
  const nioPerUsd = rate.data?.nio_per_usd ? Number(rate.data.nio_per_usd) : null;

  const bankList = useMemo(
    () => (banks.data ?? []).filter((b) => b.is_active || totals[cellKey(b.id, "USD")] || totals[cellKey(b.id, "NIO")]),
    [banks.data, totals],
  );

  function applyDraft(draft: SheetDraft) {
    if (draft.business_date && !editing) setDate(draft.business_date);
    if (draft.shop_id && !editing) setShopId(String(draft.shop_id));
    setBales(String(draft.bale_count || ""));
    setInvoices(String(draft.invoice_count || ""));
    setSales(zeroBlank(draft.total_sales_usd));
    setOther(zeroBlank(draft.opening_balance_usd));
    const cash = { USD: "", NIO: "" } as Record<Currency, string>;
    const nextDetails: Record<string, Chip[]> = {};
    for (const t of draft.transfers) {
      if (t.payment_method === "CASH") cash[t.currency_code] = t.amount;
      else if (t.bank_id) {
        (nextDetails[cellKey(t.bank_id, t.currency_code)] ??= []).push({ key: newKey(), amount: t.amount });
      }
    }
    setCashUsd(zeroBlank(cash.USD));
    setCashNio(zeroBlank(cash.NIO));
    // Keep the ids of deposits already saved where the amount is unchanged, so
    // their matches survive; anything else starts fresh.
    setDetails((current) => {
      const merged: Record<string, Chip[]> = {};
      for (const [key, chips] of Object.entries(nextDetails)) {
        const pool = [...(current[key] ?? [])];
        merged[key] = chips.map((chip) => {
          const i = pool.findIndex((p) => num(p.amount) === num(chip.amount));
          if (i < 0) return chip;
          const [kept] = pool.splice(i, 1);
          return kept;
        });
      }
      return merged;
    });
    const nextTotals: Record<string, string> = {};
    for (const t of draft.bank_totals) nextTotals[cellKey(t.bank_id, t.currency_code)] = t.amount;
    setTotals(nextTotals);
    setExpenses(
      draft.expenses.map((e) => ({
        key: newKey(), description: e.description, currency_code: e.currency_code, amount: e.amount,
      })),
    );
    setCiCash(zeroBlank(draft.commercial_invoice_cash_usd));
    setCiDeposit(zeroBlank(draft.commercial_invoice_deposit_usd));
    setDelCash(zeroBlank(draft.delivery_cash_usd));
    setDelTransfer(zeroBlank(draft.delivery_transfer_usd));
    setCredit(zeroBlank(draft.credit_usd));
    if (draft.observations) setObservations(draft.observations);
    setClosing(draft.declared_closing_usd ?? "");
    if (draft.bale_records.length) {
      setBaleRows((rows) =>
        rows.map((row) => {
          const read = draft.bale_records.find((b) => b.bale_type_id === row.bale_type_id);
          if (!read) return row;
          return {
            ...row,
            opening: String(read.opening_qty),
            received: read.received_qty ? String(read.received_qty) : "",
            closing: String(read.closing_qty),
          };
        }),
      );
    }
    setFromPhoto(true);
  }

  async function addPhoto(file: File, readIt: boolean) {
    setReading(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const result = await request<PhotoUpload>("/accounting/photos", {
        method: "POST", body, query: { read: readIt },
      });
      setPhotos((p) => [...p, result.photo]);
      setNewPhotoIds((ids) => [...ids, result.photo.id]);
      if (result.draft) {
        applyDraft(result.draft);
        setChecks([...result.checks, ...result.unclear.map((f) => `Hard to read: ${f.replace(/_/g, " ")}`)]);
        toast.push("ok", "Sheet read. Check each line against the photo, then save.");
      } else if (result.photo.extraction_error) {
        toast.push("error", `Photo kept, but it could not be read: ${result.photo.extraction_error}`);
      } else {
        toast.push("info", "Photo added. Type the amounts beside it.");
      }
    } catch (err) {
      setError(err);
    } finally {
      setReading(false);
    }
  }

  async function rereadPhoto(photoId: number) {
    setReading(true);
    try {
      const result = await api.post<PhotoUpload>(`/accounting/photos/${photoId}/read`);
      if (result.draft) {
        applyDraft(result.draft);
        setChecks([...result.checks, ...result.unclear.map((f) => `Hard to read: ${f.replace(/_/g, " ")}`)]);
        toast.push("ok", "Filled from the photo. Nothing is saved until you press Save.");
      } else {
        toast.push("error", result.photo.extraction_error ?? "The photo could not be read.");
      }
    } catch (err) {
      setError(err);
    } finally {
      setReading(false);
    }
  }

  /* -------------------------------------------------------- arithmetic */
  const transferUsd = useMemo(() => {
    let usdSum = 0;
    let nioSum = 0;
    for (const bank of bankList) {
      for (const code of CURRENCIES) {
        const key = cellKey(bank.id, code);
        const amount = totals[key] ? num(totals[key]) : (details[key] ?? []).reduce((s, c) => s + num(c.amount), 0);
        if (code === "USD") usdSum += amount;
        else nioSum += amount;
      }
    }
    return { usd: usdSum, nio: nioSum, total: toUsd(usdSum, nioSum, nioPerUsd) };
  }, [bankList, totals, details, nioPerUsd]);

  const expenseTotal = useMemo(() => {
    const u = expenses.filter((e) => e.currency_code === "USD").reduce((s, e) => s + num(e.amount), 0);
    const n = expenses.filter((e) => e.currency_code === "NIO").reduce((s, e) => s + num(e.amount), 0);
    return toUsd(u, n, nioPerUsd);
  }, [expenses, nioPerUsd]);

  const cashTotal = toUsd(num(cashUsd), num(cashNio), nioPerUsd);
  const headerTotal = num(sales) + num(other);
  // Mirrors the server's default formula; the saved sheet shows the server's own.
  const computedClosing =
    cashTotal === null || transferUsd.total === null || expenseTotal === null
      ? null
      : headerTotal - cashTotal - transferUsd.total - expenseTotal;

  /* ------------------------------------------------------------ saving */
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function save(event?: React.FormEvent) {
    event?.preventDefault();
    setError(null);
    if (!shopId) {
      setError(new Error("Choose the shop."));
      return;
    }
    const transfers: Record<string, unknown>[] = [];
    for (const code of CURRENCIES) {
      const amount = code === "USD" ? cashUsd : cashNio;
      if (num(amount) > 0) {
        transfers.push({ id: cashIds[code], payment_method: "CASH", currency_code: code, amount: cleanAmount(amount) });
      }
    }
    for (const [key, chips] of Object.entries(details)) {
      const [bankId, code] = key.split(":");
      for (const chip of chips) {
        if (!(num(chip.amount) > 0)) continue;
        transfers.push({
          id: chip.id, payment_method: "BANK", bank_id: Number(bankId), currency_code: code,
          amount: cleanAmount(chip.amount),
        });
      }
    }
    const bankTotals = Object.entries(totals)
      .filter(([, v]) => num(v) > 0)
      .map(([key, value]) => {
        const [bankId, code] = key.split(":");
        return { bank_id: Number(bankId), currency_code: code, amount: cleanAmount(value) };
      });

    const payload = {
      shop_id: Number(shopId),
      business_date: date,
      status,
      bale_count: Number(bales) || 0,
      invoice_count: Number(invoices) || 0,
      total_sales_usd: cleanAmount(sales) || "0",
      opening_balance_usd: cleanAmount(other) || "0",
      commercial_invoice_cash_usd: cleanAmount(ciCash) || "0",
      commercial_invoice_deposit_usd: cleanAmount(ciDeposit) || "0",
      delivery_cash_usd: cleanAmount(delCash) || "0",
      delivery_transfer_usd: cleanAmount(delTransfer) || "0",
      credit_usd: cleanAmount(credit) || "0",
      observations,
      declared_closing_usd: closing.trim() === "" ? null : cleanAmount(closing),
      transfers,
      bank_totals: bankTotals,
      expenses: expenses
        .filter((e) => num(e.amount) > 0)
        .map((e) => ({
          id: e.id, category: "GENERAL", description: e.description, currency_code: e.currency_code,
          amount: cleanAmount(e.amount),
        })),
      bale_records: baleRows.map((b) => {
        const opening = Number(b.opening) || 0;
        const received = Number(b.received) || 0;
        const closingQty = Number(b.closing) || 0;
        return {
          id: b.id, bale_type_id: b.bale_type_id, opening_qty: opening, received_qty: received,
          closing_qty: closingQty, sold_qty: Math.max(opening + received - closingQty, 0),
        };
      }),
      photo_ids: newPhotoIds,
    };

    setSaving(true);
    try {
      const saved = record
        ? await api.put<DailyRecord>(`/accounting/daily/${record.id}`, payload)
        : await api.post<DailyRecord>("/accounting/daily", payload);
      const green = saved.bank_cells.filter((c) => c.status === "MATCHED").length;
      toast.push("ok", `Saved. ${green} of ${saved.bank_cells.length} bank amounts found on the statements.`);
      setNewPhotoIds([]);
      if (record) onSaved?.();
      else router.push(`/accounting/${saved.id}`);
    } catch (err) {
      setError(err);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setSaving(false);
    }
  }

  const readOnly = record?.status === "LOCKED" && !can("accounting.lock");
  const cells = useMemo(() => {
    const out: Record<string, BankCell> = {};
    for (const c of record?.bank_cells ?? []) out[cellKey(c.bank_id, c.currency_code)] = c;
    return out;
  }, [record?.bank_cells]);

  const hasPhoto = photos.length > 0;
  const [pasting, setPasting] = useState(false);

  /* ============================================================== layout */
  return (
    <div className={hasPhoto ? "grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]" : ""}>
      {hasPhoto && (
        <PhotoPanel
          photos={photos}
          readerAvailable={Boolean(reader.data?.available)}
          reading={reading}
          onReread={rereadPhoto}
        />
      )}

      <form onSubmit={save} className="min-w-0 space-y-4 pb-24">
        <ErrorNote error={error} />

        {!readOnly && (
          <PhotoDrop
            hasPhoto={hasPhoto}
            reading={reading}
            readerAvailable={Boolean(reader.data?.available)}
            onFile={addPhoto}
          />
        )}

        {fromPhoto && (
          <div className="rounded-lg border border-sky-300 bg-sky-50 px-3 py-2 text-sm text-sky-900">
            <p className="flex items-center gap-2 font-medium">
              <ScanLine className="h-4 w-4" /> Filled from the photo — check every line against it before saving.
            </p>
            {checks.length > 0 && (
              <ul className="mt-1.5 list-disc space-y-0.5 pl-6 text-xs text-amber-800">
                {checks.map((c) => <li key={c}>{c}</li>)}
              </ul>
            )}
          </div>
        )}

        {readOnly && (
          <div className="rounded-lg border border-ink-300 bg-ink-100 px-3 py-2 text-sm text-ink-700">
            This sheet is locked. Ask an administrator to unlock it before editing.
          </div>
        )}

        {/* ---------------------------------------------------- header */}
        <Card padded={false}>
          <div className="grid gap-3 border-b border-ink-200 p-4 sm:grid-cols-3">
            <label className="block">
              <span className="label">Date</span>
              <input type="date" className="input" value={date} max={today()}
                disabled={editing || readOnly} onChange={(e) => setDate(e.target.value)} required />
            </label>
            <label className="block">
              <span className="label">Closing cash — shop</span>
              <select className="input" value={shopId} disabled={editing || readOnly}
                onChange={(e) => setShopId(e.target.value)} required>
                <option value="">Choose the shop…</option>
                {(shops.data ?? []).map((s) => (
                  <option key={s.id} value={s.id}>{s.name}{s.city_name ? ` — ${s.city_name}` : ""}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="label">Status</span>
              <select className="input" value={status} disabled={readOnly} onChange={(e) => setStatus(e.target.value)}>
                <option value="SUBMITTED">Submitted — check against the banks</option>
                <option value="DRAFT">Draft — still being entered</option>
              </select>
            </label>
          </div>
          <div className="grid grid-cols-2 divide-ink-200 sm:grid-cols-5 sm:divide-x">
            <Box label="Quantity of bales">
              <PlainInput value={bales} onChange={setBales} disabled={readOnly} integer />
            </Box>
            <Box label="Total sales $">
              <PlainInput value={sales} onChange={setSales} disabled={readOnly} prefix="$" />
            </Box>
            <Box label="Other balances $">
              <PlainInput value={other} onChange={setOther} disabled={readOnly} prefix="$" />
            </Box>
            <Box label="Total" tone="computed">
              <p className="tabular py-2 text-lg font-semibold">{money(headerTotal, "USD")}</p>
            </Box>
            <Box label="Invoices">
              <PlainInput value={invoices} onChange={setInvoices} disabled={readOnly} integer />
            </Box>
          </div>
        </Card>

        {/* ------------------------------------------ cash & commercial invoice */}
        <Card padded={false}>
          <SheetTable
            head={["", "C$", "$", "TOTAL$"]}
            rows={[
              {
                label: "Cash received",
                cells: [
                  <PlainInput key="n" value={cashNio} onChange={setCashNio} disabled={readOnly} prefix="C$" />,
                  <PlainInput key="u" value={cashUsd} onChange={setCashUsd} disabled={readOnly} prefix="$" />,
                  <Computed key="t" value={cashTotal} />,
                ],
                after: (num(cashNio) > 0 || num(cashUsd) > 0) && record ? (
                  <CashStatus record={record} />
                ) : null,
              },
            ]}
          />
          <SheetTable
            head={["", "Cash", "Deposit", "TOTAL$"]}
            rows={[
              {
                label: "Commercial invoice",
                cells: [
                  <PlainInput key="c" value={ciCash} onChange={setCiCash} disabled={readOnly} prefix="$" />,
                  <PlainInput key="d" value={ciDeposit} onChange={setCiDeposit} disabled={readOnly} prefix="$" />,
                  <Computed key="t" value={num(ciCash) + num(ciDeposit)} />,
                ],
              },
            ]}
          />
        </Card>

        {/* ---------------------------------------------------- transfers */}
        <Card
          padded={false}
          title="Transfers"
          description="The bank totals as written on the sheet. Each turns green when the statement shows it."
          actions={
            record && can("reconciliation.match") ? (
              <RecheckButton recordId={record.id} onDone={onSaved} />
            ) : null
          }
        >
          <div className="table-scroll">
            <table className="w-full min-w-[560px] text-sm">
              <thead className="border-b border-ink-200 bg-ink-50">
                <tr>
                  <th className="th w-28">Bank</th>
                  <th className="th">$</th>
                  <th className="th">C$</th>
                  <th className="th text-right">TOTAL$</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {bankList.map((bank) => {
                  const u = cellKey(bank.id, "USD");
                  const n = cellKey(bank.id, "NIO");
                  const rowUsd = totals[u] ? num(totals[u]) : sumChips(details[u]);
                  const rowNio = totals[n] ? num(totals[n]) : sumChips(details[n]);
                  return (
                    <tr key={bank.id}>
                      <td className="td font-semibold">{bank.code}</td>
                      {(["USD", "NIO"] as const).map((code) => {
                        const key = cellKey(bank.id, code);
                        return (
                          <td key={code} className="td align-top">
                            <TotalCell
                              value={totals[key] ?? ""}
                              onChange={(v) => setTotals((t) => ({ ...t, [key]: v }))}
                              currency={code}
                              cell={cells[key]}
                              dirty={(totals[key] ?? "") !== (record?.bank_totals.find((t) => cellKey(t.bank_id, t.currency_code) === key)?.amount ?? "")}
                              disabled={readOnly}
                              recordId={record?.id}
                              onPicked={onSaved}
                            />
                          </td>
                        );
                      })}
                      <td className="td tabular text-right align-top font-medium">
                        {rowUsd || rowNio ? usd(toUsd(rowUsd, rowNio, nioPerUsd)) : <span className="text-ink-300">–</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot className="border-t-2 border-ink-300 bg-ink-50">
                <tr>
                  <td className="td font-semibold">Total</td>
                  <td className="td tabular">{money(transferUsd.usd, "USD")}</td>
                  <td className="td tabular">{money(transferUsd.nio, "NIO")}</td>
                  <td className="td tabular text-right font-semibold">{usd(transferUsd.total)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
          {!nioPerUsd && (
            <p className="border-t border-ink-200 px-4 py-2 text-xs text-amber-700">
              No exchange rate for this month yet, so C$ amounts are not converted into TOTAL$.
              An administrator sets it in Monthly records.
            </p>
          )}
        </Card>

        {/* ----------------------------------------------------- expenses */}
        <Card
          title="Total expenses"
          actions={
            !readOnly && (
              <button type="button" className="btn-secondary btn-sm"
                onClick={() => setExpenses((r) => [...r, { key: newKey(), description: "", currency_code: "NIO", amount: "" }])}>
                <Plus className="h-3.5 w-3.5" /> Add expense
              </button>
            )
          }
        >
          {expenses.length === 0 ? (
            <p className="text-sm text-ink-500">No expenses.</p>
          ) : (
            <div className="space-y-2">
              {expenses.map((e) => (
                <div key={e.key} className="flex flex-wrap items-center gap-2">
                  <input className="input min-w-[8rem] flex-1" placeholder="What for (e.g. Bonos, bus)"
                    value={e.description} disabled={readOnly}
                    onChange={(ev) => setExpenses((r) => r.map((x) => (x.key === e.key ? { ...x, description: ev.target.value } : x)))} />
                  <CurrencySwitch value={e.currency_code} disabled={readOnly}
                    onChange={(c) => setExpenses((r) => r.map((x) => (x.key === e.key ? { ...x, currency_code: c } : x)))} />
                  <div className="w-36">
                    <PlainInput value={e.amount} disabled={readOnly} prefix={e.currency_code === "USD" ? "$" : "C$"}
                      onChange={(v) => setExpenses((r) => r.map((x) => (x.key === e.key ? { ...x, amount: v } : x)))} />
                  </div>
                  {!readOnly && (
                    <button type="button" className="btn-ghost btn-sm text-red-600" aria-label="Remove expense"
                      onClick={() => setExpenses((r) => r.filter((x) => x.key !== e.key))}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          <div className="mt-3 flex justify-between border-t border-ink-200 pt-2 text-sm">
            <span className="text-ink-500">Total expenses</span>
            <span className="tabular font-semibold">{usd(expenseTotal)}</span>
          </div>
        </Card>

        {/* ----------------------------------------------------- delivery */}
        <Card padded={false}>
          <SheetTable
            head={["", "Cash", "Transfers"]}
            rows={[{
              label: "Delivery",
              cells: [
                <PlainInput key="c" value={delCash} onChange={setDelCash} disabled={readOnly} prefix="$" />,
                <PlainInput key="t" value={delTransfer} onChange={setDelTransfer} disabled={readOnly} prefix="$" />,
              ],
            }]}
          />
        </Card>

        {/* ------------------------------------------------- bank details */}
        <Card
          title="Bank detail"
          description="Each deposit the sheet lists. Type an amount and press Enter, or paste several at once; each one turns green when it is found on the statement."
          actions={
            !readOnly && (
              <button type="button" className="btn-secondary btn-sm" onClick={() => setPasting(true)}>
                <ClipboardPaste className="h-3.5 w-3.5" /> Paste breakdown
              </button>
            )
          }
        >
          <div className="divide-y divide-ink-100">
            {bankList.flatMap((bank) =>
              (["USD", "NIO"] as const).map((code) => {
                const key = cellKey(bank.id, code);
                const cell = cells[key];
                const fromStatement = (cell?.lines ?? []).filter((l) => l.source !== "SHEET");
                return (
                  <DetailRow
                    key={key}
                    label={`${bank.code} detail ${code === "USD" ? "$" : "C$"}`}
                    currency={code}
                    chips={details[key] ?? []}
                    fromStatement={fromStatement}
                    total={totals[key]}
                    disabled={readOnly}
                    onChange={(chips) => setDetails((d) => ({ ...d, [key]: chips }))}
                    onFillTotal={(sum) => setTotals((t) => (t[key] ? t : { ...t, [key]: String(sum) }))}
                  />
                );
              }),
            )}
          </div>
        </Card>

        {pasting && (
          <BreakdownModal
            banks={bankList}
            onClose={() => setPasting(false)}
            onApply={(breakdown, keep) => {
              setDetails((d) => {
                const next = { ...d };
                for (const e of breakdown.entries) {
                  if (e.amounts.length === 0) continue;
                  const key = cellKey(e.bankId, e.currency);
                  const fresh = e.amounts.map((amount) => ({ key: newKey(), amount }));
                  next[key] = keep ? [...(next[key] ?? []), ...fresh] : fresh;
                }
                return next;
              });
              setTotals((t) => {
                const next = { ...t };
                for (const e of breakdown.entries) {
                  const key = cellKey(e.bankId, e.currency);
                  const sum = e.amounts.reduce((s, a) => s + Number(a), 0) + (keep ? sumChips(details[key]) : 0);
                  if (e.total) next[key] = e.total;
                  else if (!next[key] && sum > 0) next[key] = sum.toFixed(2);
                }
                return next;
              });
              setPasting(false);
              toast.push("ok", "Added. Check the amounts, then save to match them with the banks.");
            }}
          />
        )}

        {/* ---------------------------------------------- credit, bales, balance */}
        <Card title="Credit / observations">
          <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
            <label className="block">
              <span className="label">Credit $</span>
              <PlainInput value={credit} onChange={setCredit} disabled={readOnly} prefix="$" />
            </label>
            <label className="block">
              <span className="label">Observations</span>
              <textarea className="input min-h-[60px]" value={observations} disabled={readOnly}
                onChange={(e) => setObservations(e.target.value)}
                placeholder="e.g. $1,615 28/09/26 used on invoice #174805" />
            </label>
          </div>
        </Card>

        <Card padded={false}>
          <div className="table-scroll">
            <table className="w-full min-w-[480px] text-sm">
              <thead className="border-b border-ink-200 bg-ink-50">
                <tr>
                  <th className="th"></th>
                  {baleRows.map((b) => <th key={b.key} className="th text-center">{b.name}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {([
                  ["opening", "Bales quantity"],
                  ["received", "+ received"],
                  ["closing", "After closing"],
                ] as const).map(([field, label]) => (
                  <tr key={field}>
                    <td className="td font-medium">{label}</td>
                    {baleRows.map((b) => (
                      <td key={b.key} className="td">
                        <input className="input tabular mx-auto w-24 text-center" inputMode="numeric"
                          value={b[field]} disabled={readOnly}
                          onChange={(e) => setBaleRows((r) => r.map((x) => (x.key === b.key ? { ...x, [field]: e.target.value.replace(/[^0-9]/g, "") } : x)))} />
                      </td>
                    ))}
                  </tr>
                ))}
                <tr className="bg-ink-50">
                  <td className="td text-ink-500">Sold</td>
                  {baleRows.map((b) => (
                    <td key={b.key} className="td tabular text-center font-semibold">
                      {Math.max((Number(b.opening) || 0) + (Number(b.received) || 0) - (Number(b.closing) || 0), 0)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          {(() => {
            const sold = baleRows.reduce((s, b) => s + Math.max((Number(b.opening) || 0) + (Number(b.received) || 0) - (Number(b.closing) || 0), 0), 0);
            return bales && sold !== Number(bales) && baleRows.some((b) => b.opening) ? (
              <p className="border-t border-ink-200 px-4 py-2 text-xs text-amber-700">
                Bales sold here add up to {sold}, but Quantity of bales says {bales}.
              </p>
            ) : null;
          })()}
        </Card>

        <Card padded={false}>
          <div className="grid divide-y divide-ink-200 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            <Box label="Starting balance $" tone="computed">
              <p className="tabular py-2 font-semibold">{money(num(other), "USD")}</p>
            </Box>
            <Box label="Closing balance $ (as written)">
              <PlainInput value={closing} onChange={setClosing} disabled={readOnly} prefix="$" />
            </Box>
            <Box label="Closing balance $ (calculated)" tone="computed">
              <p className="tabular py-2 font-semibold">{usd(computedClosing)}</p>
              {computedClosing !== null && closing.trim() !== "" && Math.abs(num(closing) - computedClosing) >= 1 && (
                <p className="text-xs text-amber-700">
                  Differs from the sheet by {money(num(closing) - computedClosing, "USD")}
                </p>
              )}
            </Box>
          </div>
          <p className="border-t border-ink-200 px-4 py-2 text-xs text-ink-500">
            Total − cash received − transfers − expenses, with C$ at the month&apos;s rate
            {nioPerUsd ? ` (C$${nioPerUsd} per $1)` : ""}. The saved sheet shows the calculation step by step.
          </p>
        </Card>

        <div className="fixed inset-x-0 bottom-0 z-20 border-t border-ink-200 bg-surface/95 px-4 py-3 backdrop-blur lg:pl-64">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
            <div className="text-xs text-ink-500">
              Transfers {usd(transferUsd.total)} · Expenses {usd(expenseTotal)} · Closing {usd(computedClosing)}
            </div>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary btn-sm" onClick={() => router.back()}>Cancel</button>
              <button type="submit" className="btn-primary btn-sm" disabled={saving || readOnly}>
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                {editing ? "Save changes" : "Save sheet"}
              </button>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}

/* ================================================================ pieces */

function sumChips(chips?: Chip[]) {
  return (chips ?? []).reduce((s, c) => s + num(c.amount), 0);
}

function sumStr(values: string[]) {
  const total = values.reduce((s, v) => s + num(v), 0);
  return total ? total.toFixed(2) : "";
}

function zeroBlank(value: string | null | undefined) {
  return value && Number(value) !== 0 ? value : "";
}

function Box({ label, children, tone }: { label: string; children: React.ReactNode; tone?: "computed" }) {
  return (
    <div className={`px-4 py-3 ${tone === "computed" ? "bg-ink-50" : ""}`}>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-500">{label}</p>
      {children}
    </div>
  );
}

function PlainInput({
  value, onChange, disabled, prefix, integer,
}: {
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  prefix?: string;
  integer?: boolean;
}) {
  return (
    <div className="relative">
      {prefix && (
        <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-ink-400">
          {prefix}
        </span>
      )}
      <input
        className={`input tabular ${prefix ? (prefix.length > 1 ? "pl-8" : "pl-6") : ""}`}
        inputMode={integer ? "numeric" : "decimal"}
        value={value}
        disabled={disabled}
        placeholder="0"
        onChange={(e) => onChange(integer ? e.target.value.replace(/[^0-9]/g, "") : e.target.value)}
        onBlur={(e) => !integer && e.target.value && onChange(cleanAmount(e.target.value))}
      />
    </div>
  );
}

function Computed({ value }: { value: number | null }) {
  return <p className="tabular py-2 text-right font-medium">{value ? usd(value) : <span className="text-ink-300">–</span>}</p>;
}

function SheetTable({
  head, rows,
}: {
  head: string[];
  rows: { label: string; cells: React.ReactNode[]; after?: React.ReactNode }[];
}) {
  return (
    <div className="table-scroll border-b border-ink-200 last:border-b-0">
      <table className="w-full min-w-[480px] text-sm">
        <thead className="bg-ink-50">
          <tr>{head.map((h, i) => <th key={i} className={`th ${i === head.length - 1 && h.includes("TOTAL") ? "text-right" : ""}`}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td className="td w-44 font-semibold">
                {row.label}
                {row.after && <div className="mt-1">{row.after}</div>}
              </td>
              {row.cells.map((c, i) => <td key={i} className="td">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CurrencySwitch({
  value, onChange, disabled,
}: {
  value: Currency;
  onChange: (c: Currency) => void;
  disabled?: boolean;
}) {
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-ink-300" role="radiogroup" aria-label="Currency">
      {(["USD", "NIO"] as const).map((code) => (
        <button key={code} type="button" role="radio" aria-checked={value === code} disabled={disabled}
          onClick={() => onChange(code)}
          className={`px-2.5 py-1.5 text-xs font-semibold ${value === code ? "bg-ink-800 text-white" : "bg-surface text-ink-600 hover:bg-ink-100"}`}>
          {code === "USD" ? "$" : "C$"}
        </button>
      ))}
    </div>
  );
}

function CashStatus({ record }: { record: DailyRecord }) {
  const cash = record.transfers.filter((t) => t.payment_method === "CASH");
  if (!cash.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {cash.map((t) => <StatusBadge key={t.id} status={t.match_status} />)}
    </div>
  );
}

/** One $ or C$ cell of the TRANSFERS table, coloured by what the bank shows. */
function TotalCell({
  value, onChange, currency, cell, dirty, disabled, recordId, onPicked,
}: {
  value: string;
  onChange: (v: string) => void;
  currency: Currency;
  cell?: BankCell;
  dirty: boolean;
  disabled?: boolean;
  recordId?: number;
  onPicked?: () => void;
}) {
  const [picking, setPicking] = useState(false);
  const status = !value && !cell ? null : dirty || !cell ? "NEW" : cell.status;
  const canPick = Boolean(
    recordId && cell?.total_id && !dirty && cell.status !== "MATCHED" && cell.status !== "WAITING"
      && cell.lines.every((l) => l.source !== "SHEET"),
  );
  return (
    <div>
      <div className={`relative rounded-lg border-2 ${status ? TONE[status] : "border-transparent"}`}>
        <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs opacity-60">
          {currency === "USD" ? "$" : "C$"}
        </span>
        <input
          className="input tabular border-0 bg-transparent pl-8 shadow-none focus:ring-0"
          inputMode="decimal"
          value={value}
          disabled={disabled}
          placeholder="0"
          onChange={(e) => onChange(e.target.value)}
          onBlur={(e) => e.target.value && onChange(cleanAmount(e.target.value))}
        />
        {status === "MATCHED" && (
          <Check className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-emerald-600" />
        )}
      </div>
      {status && status !== "NEW" && (
        <p className="mt-1 text-[11px] leading-tight">
          <span className="font-medium">{CELL_WORDS[status] ?? status}</span>
          {cell && cell.status === "POSSIBLE" && (
            <span className="text-ink-500"> · more than one bank line fits —{" "}
              <a href="/reconciliation" className="font-medium text-brand-700 hover:underline">confirm it</a>
            </span>
          )}
          {cell && !["MATCHED", "POSSIBLE", "WAITING"].includes(cell.status) && Number(cell.remaining) > 0 && (
            <span className="text-ink-500"> · {money(cell.remaining, currency)} not found</span>
          )}
          {cell && cell.status === "DIFFERENT" && (
            <span className="text-ink-500"> · detail adds to {money(cell.listed_sum, currency)}</span>
          )}
        </p>
      )}
      {status === "NEW" && value && <p className="mt-1 text-[11px] text-ink-500">Checked when saved</p>}
      {canPick && (
        <button type="button" className="mt-1 text-[11px] font-medium text-brand-700 hover:underline"
          onClick={() => setPicking(true)}>
          Choose the bank lines…
        </button>
      )}
      {picking && cell?.total_id && recordId && (
        <PickLinesModal recordId={recordId} totalId={cell.total_id} currency={currency}
          onClose={() => setPicking(false)} onDone={() => { setPicking(false); onPicked?.(); }} />
      )}
    </div>
  );
}

/** A DETAIL row: the deposits as chips, each coloured by its own match. */
function DetailRow({
  label, currency, chips, fromStatement, total, disabled, onChange, onFillTotal,
}: {
  label: string;
  currency: Currency;
  chips: Chip[];
  fromStatement: { transfer_id: number; amount: string; source: string; status: string; bank_description: string | null }[];
  total?: string;
  disabled?: boolean;
  onChange: (chips: Chip[]) => void;
  onFillTotal: (sum: number) => void;
}) {
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const sum = sumChips(chips);

  function add(raw: string) {
    // "18000-19030" or "18000 19030" as on paper: several deposits at once.
    const parts = raw.split(/[\s;/+]+|,(?=\s)|(?<=\d)\s*-\s*(?=\d)/).map((p) => cleanAmount(p)).filter((p) => num(p) > 0);
    if (!parts.length) return;
    const next = [...chips, ...parts.map((amount) => ({ key: newKey(), amount }))];
    onChange(next);
    setDraft("");
    onFillTotal(sumChips(next));
  }

  const totalNum = num(total);
  const mismatch = chips.length > 0 && totalNum > 0 && Math.abs(sum - totalNum) >= 0.005;

  return (
    <div className="flex flex-wrap items-center gap-2 py-2">
      <span className="w-32 shrink-0 text-xs font-semibold uppercase tracking-wide text-ink-500">{label}</span>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
        {chips.map((chip) => (
          <span key={chip.key}
            title={chip.status ? CELL_WORDS[chip.status] ?? chip.status.replace(/_/g, " ").toLowerCase() : "Checked when saved"}
            className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-sm tabular ${TONE[chip.status ?? "NEW"] ?? TONE.NEW}`}>
            {chip.status === "MATCHED" && <Check className="h-3.5 w-3.5" />}
            {money(chip.amount, currency)}
            {!disabled && (
              <button type="button" aria-label="Remove deposit" className="opacity-60 hover:opacity-100"
                onClick={() => onChange(chips.filter((c) => c.key !== chip.key))}>
                <X className="h-3 w-3" />
              </button>
            )}
          </span>
        ))}
        {fromStatement.map((line) => (
          <span key={line.transfer_id} title={`From the statement: ${line.bank_description ?? ""}`}
            className={`inline-flex items-center gap-1 rounded-md border border-dashed px-2 py-0.5 text-sm tabular ${TONE[line.status] ?? TONE.NEW}`}>
            <Check className="h-3.5 w-3.5" />
            {money(line.amount, currency)}
          </span>
        ))}
        {!disabled && (
          <input
            ref={input}
            className="input w-32 py-1 text-sm tabular"
            inputMode="decimal"
            placeholder={chips.length ? "+ another" : "amount"}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onPaste={(e) => {
              const text = e.clipboardData.getData("text");
              if (/\d[\s\S]*[\s,;+-][\s\S]*\d/.test(text.trim())) {
                e.preventDefault();
                add(text);
              }
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add(draft);
              }
            }}
            onBlur={() => draft && add(draft)}
          />
        )}
      </div>
      {(chips.length > 0 || fromStatement.length > 0) && (
        <span className={`text-xs tabular ${mismatch ? "font-semibold text-red-700" : "text-ink-500"}`}>
          = {money(sum + fromStatement.reduce((s, l) => s + num(l.amount), 0), currency)}
          {mismatch && ` (total ${money(totalNum, currency)})`}
        </span>
      )}
    </div>
  );
}

function PickLinesModal({
  recordId, totalId, currency, onClose, onDone,
}: {
  recordId: number;
  totalId: number;
  currency: Currency;
  onClose: () => void;
  onDone: () => void;
}) {
  const base = `/accounting/daily/${recordId}/bank-totals/${totalId}`;
  const { data, error, loading } = useApi(
    () => api.get<{ total: { bank_code: string; amount: string }; lines: CandidateLine[] }>(`${base}/candidates`),
    [base],
  );
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);

  useEffect(() => {
    if (data) setChosen(new Set(data.lines.filter((l) => l.selected).map((l) => l.id)));
  }, [data]);

  const target = Number(data?.total.amount ?? 0);
  const picked = (data?.lines ?? []).filter((l) => chosen.has(l.id)).reduce((s, l) => s + Number(l.amount), 0);
  const exact = Math.abs(picked - target) < 0.005;

  async function submit() {
    setBusy(true);
    setSaveError(null);
    try {
      await api.post(`${base}/pick`, { transaction_ids: [...chosen] });
      onDone();
    } catch (err) {
      setSaveError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} wide
      title={data ? `Bank lines for ${data.total.bank_code} ${money(data.total.amount, currency)}` : "Bank lines"}
      footer={
        <>
          <span className={`mr-auto self-center text-sm tabular ${exact ? "font-semibold text-emerald-700" : "text-ink-600"}`}>
            Chosen {money(picked, currency)} of {money(target, currency)}
            {!exact && ` · ${money(target - picked, currency)} to go`}
          </span>
          <button className="btn-secondary btn-sm" onClick={onClose}>Cancel</button>
          <button className="btn-primary btn-sm" onClick={submit} disabled={busy || picked > target + 0.005 || chosen.size === 0}>
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Use these lines
          </button>
        </>
      }>
      <ErrorNote error={error ?? saveError} />
      {loading && !data && <p className="text-sm text-ink-500">Loading…</p>}
      {data && (
        <>
          <p className="mb-2 text-xs text-ink-500">
            More than one combination of this day&apos;s lines adds up to the sheet&apos;s total, or none does.
            Tick the payments that belong to this shop.
          </p>
          <ul className="divide-y divide-ink-100 rounded-lg border border-ink-200">
            {data.lines.map((line) => (
              <li key={line.id}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-ink-50">
                  <input type="checkbox" checked={chosen.has(line.id)}
                    onChange={(e) => setChosen((s) => {
                      const next = new Set(s);
                      if (e.target.checked) next.add(line.id); else next.delete(line.id);
                      return next;
                    })} />
                  <span className="tabular w-28 shrink-0 text-right font-medium">{money(line.amount, currency)}</span>
                  <span className="min-w-0 flex-1 truncate text-sm text-ink-700">{line.description}</span>
                  {line.reference && <span className="text-xs text-ink-400">{line.reference}</span>}
                </label>
              </li>
            ))}
            {data.lines.length === 0 && (
              <li className="px-3 py-4 text-center text-sm text-ink-500">No unclaimed lines for this bank on this day.</li>
            )}
          </ul>
        </>
      )}
    </Modal>
  );
}

function RecheckButton({ recordId, onDone }: { recordId: number; onDone?: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <button type="button" className="btn-secondary btn-sm" disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await api.post(`/accounting/daily/${recordId}/recheck`);
          toast.push("ok", "Checked again against the day's statements.");
          onDone?.();
        } catch (err) {
          toast.push("error", err instanceof Error ? err.message : "Could not re-check.");
        } finally {
          setBusy(false);
        }
      }}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
      Check again
    </button>
  );
}

/* ---------------------------------------------------------------- photos */

function PhotoDrop({
  hasPhoto, reading, readerAvailable, onFile,
}: {
  hasPhoto: boolean;
  reading: boolean;
  readerAvailable: boolean;
  onFile: (file: File, read: boolean) => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const pick = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (file) onFile(file, readerAvailable && !hasPhoto);
    },
    [onFile, readerAvailable, hasPhoto],
  );

  useEffect(() => {
    function onPaste(event: ClipboardEvent) {
      const item = Array.from(event.clipboardData?.items ?? []).find((i) => i.type.startsWith("image/"));
      const file = item?.getAsFile();
      if (!file || reading) return;
      event.preventDefault();
      onFile(new File([file], file.name || "pasted-sheet.png", { type: file.type }), readerAvailable && !hasPhoto);
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [onFile, readerAvailable, hasPhoto, reading]);

  if (hasPhoto) {
    return (
      <div className="flex justify-end">
        <button type="button" className="btn-secondary btn-sm" onClick={() => fileInput.current?.click()} disabled={reading}>
          <ImagePlus className="h-3.5 w-3.5" /> Add another photo
        </button>
        <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" className="hidden"
          onChange={(e) => pick(e.target.files)} />
      </div>
    );
  }
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files); }}
      className={`rounded-xl border-2 border-dashed px-4 py-6 text-center transition ${over ? "border-brand-500 bg-brand-50" : "border-ink-300 bg-surface"}`}
    >
      {reading ? (
        <p className="flex items-center justify-center gap-2 text-sm text-ink-700">
          <Loader2 className="h-4 w-4 animate-spin" /> Reading the sheet… this takes about 15 seconds.
        </p>
      ) : (
        <>
          <Camera className="mx-auto h-7 w-7 text-ink-400" />
          <p className="mt-2 text-sm font-medium text-ink-900">Photo of the paper sheet</p>
          <p className="mt-0.5 text-xs text-ink-500">
            {readerAvailable
              ? "Drop it here, choose it, or paste it (Ctrl+V). The amounts are read into the form for you to check and edit."
              : "Drop it here, choose it, or paste it (Ctrl+V). It is kept with the sheet and shown beside the form."}
          </p>
          {!readerAvailable && (
            <p className="mx-auto mt-2 max-w-md rounded border border-amber-300 bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
              Automatic reading is off on this server: no GEMINI_API_KEY (free) or
              ANTHROPIC_API_KEY is set. Until an administrator adds one, type the amounts, or
              use “Paste breakdown” below.
            </p>
          )}
          <div className="mt-3 flex justify-center gap-2">
            <button type="button" className="btn-primary btn-sm" onClick={() => fileInput.current?.click()}>
              <Camera className="h-3.5 w-3.5" /> {readerAvailable ? "Choose photo and read it" : "Choose photo"}
            </button>
          </div>
          <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" capture="environment"
            className="hidden" onChange={(e) => pick(e.target.files)} />
          <p className="mt-2 text-[11px] text-ink-400">Or skip it and type the sheet below.</p>
        </>
      )}
    </div>
  );
}

function PhotoPanel({
  photos, readerAvailable, reading, onReread,
}: {
  photos: SheetPhoto[];
  readerAvailable: boolean;
  reading: boolean;
  onReread: (id: number) => void;
}) {
  const [index, setIndex] = useState(photos.length - 1);
  const [zoom, setZoom] = useState(false);
  const photo = photos[Math.min(index, photos.length - 1)];
  useEffect(() => setIndex(photos.length - 1), [photos.length]);
  if (!photo) return null;
  const src = `/api/v1/accounting/photos/${photo.id}/file`;
  return (
    <aside className="min-w-0">
      <div className="card sticky top-16 overflow-hidden xl:top-4">
        <div className="flex items-center justify-between gap-2 border-b border-ink-200 px-3 py-2">
          <p className="truncate text-sm font-medium">Photo of the sheet</p>
          <div className="flex gap-1">
            {readerAvailable && (
              <button type="button" className="btn-ghost btn-sm" disabled={reading} onClick={() => onReread(photo.id)}
                title="Read the amounts from this photo into the form again">
                {reading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ScanLine className="h-3.5 w-3.5" />}
                Read
              </button>
            )}
            <button type="button" className="btn-ghost btn-sm" onClick={() => setZoom(true)} aria-label="Enlarge">
              <Maximize2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt="Photo of the paper sheet" className="max-h-[calc(100vh-8rem)] w-full cursor-zoom-in object-contain bg-ink-100"
          onClick={() => setZoom(true)} />
        {photos.length > 1 && (
          <div className="flex gap-1 border-t border-ink-200 p-2">
            {photos.map((p, i) => (
              <button key={p.id} type="button" onClick={() => setIndex(i)}
                className={`rounded px-2 py-0.5 text-xs ${i === index ? "bg-brand-600 text-white" : "bg-ink-100 text-ink-700"}`}>
                {i + 1}
              </button>
            ))}
          </div>
        )}
        {photo.extraction_error && (
          <p className="flex items-start gap-1.5 border-t border-ink-200 px-3 py-2 text-xs text-amber-800">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {photo.extraction_error}
          </p>
        )}
      </div>
      {zoom && (
        <div className="fixed inset-0 z-50 overflow-auto bg-ink-950/90 p-4" onClick={() => setZoom(false)}>
          <button type="button" className="fixed right-4 top-4 rounded-full bg-white/90 p-2" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src} alt="Photo of the paper sheet, enlarged" className="mx-auto max-w-none" style={{ width: "min(1400px, 160vw)" }} />
          <p className="mt-2 text-center text-xs text-white/70"><ZoomIn className="mr-1 inline h-3.5 w-3.5" />Scroll to move around; click to close.</p>
        </div>
      )}
    </aside>
  );
}

/* ------------------------------------------------------- pasted breakdown */

function BreakdownModal({
  banks, onClose, onApply,
}: {
  banks: { id: number; code: string }[];
  onClose: () => void;
  onApply: (breakdown: Breakdown, keep: boolean) => void;
}) {
  const [text, setText] = useState("");
  const [keep, setKeep] = useState(false);
  const parsed = useMemo(() => parseBreakdown(text, banks), [text, banks]);
  const count = parsed.entries.reduce((n, e) => n + e.amounts.length + (e.total ? 1 : 0), 0);

  return (
    <Modal open onClose={onClose} wide title="Paste the payment breakdown"
      footer={
        <>
          <button type="button" className="btn-secondary btn-sm" onClick={onClose}>Cancel</button>
          <label className="mr-auto flex items-center gap-2 self-center text-xs text-ink-600">
            <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
            Keep the deposits already there and add these
          </label>
          <button type="button" className="btn-primary btn-sm" disabled={count === 0} onClick={() => onApply(parsed, keep)}>
            Add {count || ""} to the sheet
          </button>
        </>
      }>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="block">
          <span className="label">Paste here (from WhatsApp, Excel or a note)</span>
          <textarea className="input h-64 font-mono text-sm" autoFocus value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"BAC C$ 18000 - 19030\nBAC $ 10\nLAFISE C$ 7000\nBanpro $ 190, 235, 280, 1095\nLafise $ total 7066"} />
          <span className="mt-1 block text-xs text-ink-500">
            One bank per line. C$ / cordobas or $ / dolares sets the currency; a line without one keeps
            the line above&apos;s. A line with &quot;total&quot; sets the bank total.
          </span>
        </label>
        <div>
          <span className="label">What will be added</span>
          {parsed.entries.length === 0 ? (
            <p className="text-sm text-ink-500">Nothing recognised yet.</p>
          ) : (
            <ul className="divide-y divide-ink-100 rounded-lg border border-ink-200">
              {parsed.entries.map((e) => (
                <li key={`${e.bankId}:${e.currency}`} className="px-3 py-2 text-sm">
                  <p className="font-semibold">{e.bankCode} {e.currency === "USD" ? "$" : "C$"}</p>
                  {e.amounts.length > 0 && (
                    <p className="tabular text-ink-700">{e.amounts.map((a) => money(a, e.currency)).join(" · ")}</p>
                  )}
                  {e.total && <p className="tabular text-ink-700">Total {money(e.total, e.currency)}</p>}
                </li>
              ))}
            </ul>
          )}
          {parsed.skipped.length > 0 && (
            <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
              No bank named on: {parsed.skipped.join(" | ")}
            </p>
          )}
        </div>
      </div>
    </Modal>
  );
}
