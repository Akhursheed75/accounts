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
  X, ZoomIn,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ErrorNote, Modal, StatusBadge, useToast } from "./ui";
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

  /* ------------------------------------------- green while typing */
  const live = useLiveMatch({
    date, recordId: record?.id, details, totals, enabled: Boolean(banks.data),
  });

  /** Colour of one deposit: saved deposits use the bank match the server made,
   *  anything typed since is checked live against the uploaded statements. */
  const chipTone = (chip: Chip): { tone: string; note: string } => {
    if (chip.id && chip.status) {
      return { tone: chip.status, note: CELL_WORDS[chip.status] ?? chip.status.replace(/_/g, " ").toLowerCase() };
    }
    const l = live.details[chip.key];
    if (!l) return { tone: "NEW", note: "Checking…" };
    return { tone: LIVE_TONE[l.status], note: LIVE_WORDS[l.status] + (l.description ? ` · ${l.description}` : "") };
  };

  const cellTone = (bankId: number, code: Currency): { tone: string | null; note: string } => {
    const key = cellKey(bankId, code);
    const value = totals[key] ?? "";
    const chips = details[key] ?? [];
    const saved = cells[key];
    const savedTotal = record?.bank_totals.find((t) => cellKey(t.bank_id, t.currency_code) === key)?.amount ?? "";
    const savedChips = record?.transfers.filter(
      (t) => t.source === "SHEET" && t.payment_method === "BANK" && t.bank_id !== null && cellKey(t.bank_id, t.currency_code) === key,
    ) ?? [];
    const dirty = value !== savedTotal || chips.some((c) => !c.id) || chips.length !== savedChips.length;
    if (!value && !chips.length) return { tone: null, note: "" };
    if (saved && !dirty) return { tone: saved.status, note: CELL_WORDS[saved.status] ?? saved.status };
    if (chips.length) {
      const listed = sumChips(chips);
      if (value && Math.abs(listed - num(value)) >= 0.005) {
        return { tone: "DIFFERENT", note: `Detail adds to ${money(listed, code)}` };
      }
      const tones = chips.map((c) => chipTone(c).tone);
      if (tones.every((t) => t === "MATCHED")) return { tone: "MATCHED", note: "On the statement" };
      if (tones.some((t) => t === "NEW")) return { tone: "NEW", note: "Checking…" };
      if (tones.every((t) => t === "WAITING")) return { tone: "WAITING", note: LIVE_WORDS.NO_STATEMENT };
      if (tones.some((t) => t === "UNMATCHED")) return { tone: "UNMATCHED", note: "Some deposits not on the statement" };
      return { tone: "POSSIBLE", note: "Confirm the match after saving" };
    }
    const l = live.totals[key];
    if (!l) return { tone: "NEW", note: "Checking…" };
    return { tone: LIVE_TONE[l.status], note: LIVE_TOTAL_WORDS[l.status] };
  };

  const addDeposits = (key: string, raw: string) => {
    const parts = splitAmounts(raw);
    if (!parts.length) return;
    setDetails((d) => {
      const next = [...(d[key] ?? []), ...parts.map((amount) => ({ key: newKey(), amount }))];
      setTotals((t) => (t[key] ? t : { ...t, [key]: sumChips(next).toFixed(2) }));
      return { ...d, [key]: next };
    });
  };
  const removeDeposit = (key: string, chipKey: string) =>
    setDetails((d) => ({ ...d, [key]: (d[key] ?? []).filter((c) => c.key !== chipKey) }));

  // Paper order: BAC, LAFISE, BANPRO, FICHOSA, then anything else.
  const ORDER = ["BAC", "LAFISE", "BANPRO", "FICHOSA", "FICOHSA"];
  const paperBanks = [...bankList].sort(
    (a, b) => (ORDER.indexOf(a.code) + 1 || 99) - (ORDER.indexOf(b.code) + 1 || 99),
  );
  const detailBanks = paperBanks.filter(
    (b) => !["FICHOSA", "FICOHSA"].includes(b.code)
      || (details[cellKey(b.id, "USD")]?.length || details[cellKey(b.id, "NIO")]?.length),
  );
  const ficohsa = paperBanks.find((b) => ["FICHOSA", "FICOHSA"].includes(b.code));
  const [showFicohsaDetail, setShowFicohsaDetail] = useState(false);

  const soldTotal = baleRows.reduce(
    (s, b) => s + Math.max((Number(b.opening) || 0) + (Number(b.received) || 0) - (Number(b.closing) || 0), 0), 0,
  );

  /* ============================================================== layout */
  return (
    <div className={hasPhoto ? "grid gap-4 xl:grid-cols-[minmax(0,4fr)_minmax(0,7fr)]" : ""}>
      {hasPhoto && (
        <PhotoPanel
          photos={photos}
          readerAvailable={Boolean(reader.data?.available)}
          reading={reading}
          onReread={rereadPhoto}
        />
      )}

      <form onSubmit={save} className="min-w-0 space-y-3 pb-24">
        <ErrorNote error={error} />

        {!readOnly && (
          <PhotoDrop
            hasPhoto={hasPhoto}
            reading={reading}
            readerAvailable={Boolean(reader.data?.available)}
            onFile={addPhoto}
          />
        )}

        {fromPhoto && checks.length > 0 && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <p className="flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4" /> Worth a second look</p>
            <ul className="mt-1 list-disc pl-6 text-xs">{checks.map((c) => <li key={c}>{c}</li>)}</ul>
          </div>
        )}

        {readOnly && (
          <div className="rounded-lg border border-ink-300 bg-ink-100 px-3 py-2 text-sm text-ink-700">
            This sheet is locked. Ask an administrator to unlock it before editing.
          </div>
        )}

        {/* toolbar: things the paper does not have */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Legend />
          <div className="flex flex-wrap items-center gap-2">
            <select className="input w-auto py-1 text-xs" value={status} disabled={readOnly}
              onChange={(e) => setStatus(e.target.value)} aria-label="Status">
              <option value="SUBMITTED">Submitted</option>
              <option value="DRAFT">Draft</option>
            </select>
            {record && can("reconciliation.match") && <RecheckButton recordId={record.id} onDone={onSaved} />}
          </div>
        </div>

        {/* ============================== the paper ============================== */}
        <div className="paper-sheet overflow-x-auto rounded-sm bg-white text-neutral-900 shadow-md ring-1 ring-neutral-300">
          <div className="min-w-[720px] px-5 pb-6 pt-5">
            {/* date + CLOSING CASH <shop> */}
            <div className="mb-3 flex items-end justify-between gap-4">
              <input type="date" className="paper-input w-44 border-b-2 border-neutral-800 text-lg font-semibold"
                value={date} max={today()} disabled={editing || readOnly}
                onChange={(e) => setDate(e.target.value)} required aria-label="Date" />
              <div className="flex items-end gap-3">
                <span className="pb-1 text-sm font-bold tracking-wide">CLOSING CASH</span>
                <select className="paper-input w-56 border-b-2 border-neutral-800 text-xl font-semibold"
                  value={shopId} disabled={editing || readOnly} onChange={(e) => setShopId(e.target.value)}
                  required aria-label="Shop">
                  <option value="">choose the shop…</option>
                  {(shops.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-[1.35fr_1fr_1fr_0.75fr_0.75fr] border-l border-t border-neutral-800 text-[13px]">
              {/* header boxes */}
              <P head>QUANTITY OF BALES</P><P head center>TOTAL SALES $</P><P head center>OTHER BALANCES $</P>
              <P head center>TOTAL</P><P head center>INVOICES</P>
              <P><Num label="Quantity of bales" value={bales} onChange={setBales} disabled={readOnly} integer center /></P>
              <P><Num label="Total sales $" value={sales} onChange={setSales} disabled={readOnly} center /></P>
              <P><Num label="Other balances $" value={other} onChange={setOther} disabled={readOnly} center /></P>
              <P center><span className="tabular text-base font-semibold">{headerTotal ? fmt(headerTotal) : ""}</span></P>
              <P><Num label="Invoices" value={invoices} onChange={setInvoices} disabled={readOnly} integer center /></P>
              <Bar />

              {/* cash received */}
              <P /><P /><P /><P head center>TOTAL$</P><P />
              <P className="row-span-2 !items-center justify-center border-2 border-neutral-800 font-medium">CASH RECEIVED</P>
              <P className="col-span-2"><span className="w-7 text-xs font-semibold">C$</span><Num label="Cash received C$" value={cashNio} onChange={setCashNio} disabled={readOnly} /></P>
              <P className="row-span-2" center><span className="tabular font-semibold">{num(cashNio) || num(cashUsd) ? usd(cashTotal) : ""}</span></P>
              <P className="row-span-2">{record && (num(cashNio) > 0 || num(cashUsd) > 0) && <CashStatus record={record} />}</P>
              <P className="col-span-2"><span className="w-7 text-xs font-semibold">$</span><Num label="Cash received $" value={cashUsd} onChange={setCashUsd} disabled={readOnly} /></P>

              {/* commercial invoice */}
              <P head>COMERCIAL INVOICE</P><P head center>CASH</P><P head center>DEPOSIT</P><P head center>TOTAL$</P><P />
              <P /><P><Num value={ciCash} onChange={setCiCash} disabled={readOnly} center /></P>
              <P><Num value={ciDeposit} onChange={setCiDeposit} disabled={readOnly} center /></P>
              <P center><span className="tabular font-semibold">{num(ciCash) + num(ciDeposit) ? fmt(num(ciCash) + num(ciDeposit)) : ""}</span></P><P />

              {/* transfers */}
              <P head>TRANSFERS</P><P head center>$</P><P head center>C$</P><P head center>TOTAL$</P><P />
              {paperBanks.map((bank) => {
                const u = cellKey(bank.id, "USD");
                const n = cellKey(bank.id, "NIO");
                const rowUsd = totals[u] ? num(totals[u]) : sumChips(details[u]);
                const rowNio = totals[n] ? num(totals[n]) : sumChips(details[n]);
                const pickable = (["USD", "NIO"] as const).map((code) => {
                  const c = cells[cellKey(bank.id, code)];
                  return c && c.total_id && c.status !== "MATCHED" && c.status !== "WAITING"
                    && c.lines.every((l) => l.source !== "SHEET") && totals[cellKey(bank.id, code)] === record?.bank_totals.find((t) => t.id === c.total_id)?.amount
                    ? { code, cell: c } : null;
                }).filter(Boolean) as { code: Currency; cell: BankCell }[];
                return (
                  <Fragment key={bank.id}>
                    <P className="font-medium">{bank.code === "FICOHSA" ? "FICHOSA" : bank.code}</P>
                    {(["USD", "NIO"] as const).map((code) => {
                      const key = cellKey(bank.id, code);
                      const { tone, note } = cellTone(bank.id, code);
                      return (
                        <P key={code} tone={tone} title={note}>
                          <Num label={`${bank.code} ${code === "USD" ? "$" : "C$"}`} value={totals[key] ?? ""} center disabled={readOnly}
                            onChange={(v) => setTotals((t) => ({ ...t, [key]: v }))} />
                          {tone === "MATCHED" && <Check className="h-4 w-4 shrink-0 text-emerald-700" />}
                        </P>
                      );
                    })}
                    <P center><span className="tabular">{rowUsd || rowNio ? usd(toUsd(rowUsd, rowNio, nioPerUsd)) : ""}</span></P>
                    <P className="text-[11px]">
                      {pickable.map(({ code, cell }) => (
                        <PickButton key={code} recordId={record!.id} cell={cell} currency={code} onDone={onSaved} />
                      ))}
                    </P>
                  </Fragment>
                );
              })}

              {/* expenses */}
              <P className="font-medium">TOTAL EXPENSES</P>
              <P className="col-span-2 !block py-1">
                <ExpenseLine expenses={expenses} setExpenses={setExpenses} disabled={readOnly} />
              </P>
              <P center><span className="tabular font-semibold">{expenses.length ? usd(expenseTotal) : ""}</span></P><P />

              {/* delivery */}
              <P /><P head center>CASH</P><P head center>TRANSFERS</P><P /><P />
              <P className="font-medium">DELIVERY</P>
              <P><Num value={delCash} onChange={setDelCash} disabled={readOnly} center /></P>
              <P><Num value={delTransfer} onChange={setDelTransfer} disabled={readOnly} center /></P>
              <P /><P />
              <Bar>
                {!readOnly && (
                  <button type="button" onClick={() => setPasting(true)}
                    className="ml-auto inline-flex items-center gap-1 rounded bg-white/90 px-2 py-0.5 text-[11px] font-semibold text-neutral-900 hover:bg-white">
                    <ClipboardPaste className="h-3 w-3" /> Paste payment breakdown
                  </button>
                )}
              </Bar>

              {/* detail rows */}
              {detailBanks.map((bank, i) => (
                <Fragment key={bank.id}>
                  {i > 0 && <Spacer />}
                  {(["USD", "NIO"] as const).map((code) => {
                    const key = cellKey(bank.id, code);
                    const name = bank.code === "FICOHSA" ? "FICHOSA" : bank.code;
                    const label = bank.code === "BANPRO" || bank.code === "FICHOSA" || bank.code === "FICOHSA"
                      ? `${name} ${code === "USD" ? "$" : "C$"}`
                      : `${name} DETAIL ${code === "USD" ? "$" : "C$"}`;
                    const fromStatement = (cells[key]?.lines ?? []).filter((l) => l.source !== "SHEET");
                    return (
                      <Fragment key={code}>
                        <P className="font-medium">{label}</P>
                        <P className="col-span-4 !flex-wrap gap-1 py-1">
                          <DepositChips
                            chips={details[key] ?? []} currency={code} disabled={readOnly}
                            tone={chipTone} fromStatement={fromStatement}
                            total={totals[key]}
                            onAdd={(raw) => addDeposits(key, raw)}
                            onRemove={(chipKey) => removeDeposit(key, chipKey)}
                          />
                        </P>
                      </Fragment>
                    );
                  })}
                </Fragment>
              ))}
              {ficohsa && !detailBanks.includes(ficohsa) && !readOnly && (
                <P className="col-span-5 !py-0.5">
                  {showFicohsaDetail ? null : (
                    <button type="button" className="text-[11px] font-medium text-neutral-500 hover:text-neutral-900"
                      onClick={() => { setShowFicohsaDetail(true); addDeposits(cellKey(ficohsa.id, "NIO"), ""); }}>
                      + FICHOSA detail
                    </button>
                  )}
                </P>
              )}
              {ficohsa && showFicohsaDetail && !detailBanks.includes(ficohsa) && (["USD", "NIO"] as const).map((code) => {
                const key = cellKey(ficohsa.id, code);
                return (
                  <Fragment key={code}>
                    <P className="font-medium">FICHOSA {code === "USD" ? "$" : "C$"}</P>
                    <P className="col-span-4 !flex-wrap gap-1 py-1">
                      <DepositChips chips={details[key] ?? []} currency={code} disabled={readOnly} tone={chipTone}
                        fromStatement={[]} total={totals[key]}
                        onAdd={(raw) => addDeposits(key, raw)} onRemove={(chipKey) => removeDeposit(key, chipKey)} />
                    </P>
                  </Fragment>
                );
              })}
              <Spacer />

              {/* credit / observations */}
              <P className="justify-center font-bold">CREDIT</P>
              <P><Num value={credit} onChange={setCredit} disabled={readOnly} prefix="$" /></P>
              <P className="col-span-3" />
              <P className="justify-center font-bold">OBSERVATIONS</P>
              <P className="col-span-4">
                <input className="paper-input w-full" value={observations} disabled={readOnly}
                  onChange={(e) => setObservations(e.target.value)} aria-label="Observations" />
              </P>
              <Spacer />

              {/* bales */}
              <P />
              {baleRows.map((b) => <P key={b.key} head center>{b.name}</P>)}
              {Array.from({ length: Math.max(4 - baleRows.length, 0) }).map((_, i) => <P key={i} />)}
              {([
                ["opening", "BALES QUANTITY"],
                ["received", "+ RECEIVED"],
                ["closing", "AFTER CLOSING"],
              ] as const).map(([field, label]) => (
                <Fragment key={field}>
                  <P className={field === "received" ? "text-neutral-500" : "font-medium"}>{label}</P>
                  {baleRows.map((b) => (
                    <P key={b.key}>
                      <Num value={b[field]} integer center disabled={readOnly}
                        onChange={(v) => setBaleRows((r) => r.map((x) => (x.key === b.key ? { ...x, [field]: v } : x)))} />
                    </P>
                  ))}
                  {Array.from({ length: Math.max(4 - baleRows.length, 0) }).map((_, i) => <P key={i} />)}
                </Fragment>
              ))}
              <P className="text-neutral-500">sold</P>
              {baleRows.map((b) => (
                <P key={b.key} center className="text-neutral-500">
                  <span className="tabular">{Math.max((Number(b.opening) || 0) + (Number(b.received) || 0) - (Number(b.closing) || 0), 0)}</span>
                </P>
              ))}
              <P className="col-span-2 text-[11px] text-amber-700">
                {bales && baleRows.some((b) => b.opening) && soldTotal !== Number(bales)
                  ? `Sold adds to ${soldTotal}, quantity of bales says ${bales}` : ""}
              </P>
              <Spacer />

              {/* balances */}
              <P className="font-medium">STARTING BALANCE</P>
              <P><span className="tabular px-1 text-base">{other ? fmt(num(other)) : ""}</span></P>
              <P className="col-span-3" />
              <P className="font-medium">CLOSING BALANCE</P>
              <P><Num label="Closing balance" value={closing} onChange={setClosing} disabled={readOnly} /></P>
              <P className="col-span-3 text-xs text-neutral-600">
                calculated {usd(computedClosing)}
                {computedClosing !== null && closing.trim() !== "" && Math.abs(num(closing) - computedClosing) >= 1 && (
                  <span className="ml-2 font-semibold text-amber-700">
                    differs by {money(num(closing) - computedClosing, "USD")}
                  </span>
                )}
              </P>
            </div>
            {!nioPerUsd && (
              <p className="mt-2 text-xs text-amber-700">
                No exchange rate for this month yet, so C$ amounts are not converted into TOTAL$.
                An administrator sets it in Monthly records.
              </p>
            )}
          </div>
        </div>

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
                setTotals((t) => {
                  const out = { ...t };
                  for (const e of breakdown.entries) {
                    const key = cellKey(e.bankId, e.currency);
                    if (e.total) out[key] = e.total;
                    else if (e.amounts.length) {
                      const before = sumChips(d[key]);
                      const was = num(t[key]);
                      // A total that simply added up the deposits keeps adding them up.
                      if (!t[key] || (keep && Math.abs(was - before) < 0.005) || !keep) {
                        out[key] = sumChips(next[key]).toFixed(2);
                      }
                    }
                  }
                  return out;
                });
                return next;
              });
              setPasting(false);
              toast.push("ok", "Added. Each payment turns green when the uploaded statements show it.");
            }}
          />
        )}

        <div className="fixed inset-x-0 bottom-0 z-20 border-t border-ink-200 bg-surface/95 px-4 py-3 backdrop-blur lg:pl-64">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
            <div className="text-xs text-ink-500">
              Transfers {usd(transferUsd.total)} · Expenses {usd(expenseTotal)} · Closing {usd(computedClosing)}
              {live.counts.total > 0 && (
                <span className="ml-2 font-medium text-emerald-700">
                  · {live.counts.found} of {live.counts.total} new payments on the statements
                </span>
              )}
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

/** Plain number as written on paper: 1,509 or 1,008.11 */
function fmt(value: number) {
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** "18000-19030", "18000 19030", "18,000, 19,030" or one per line: each is a deposit. */
function splitAmounts(raw: string): string[] {
  return raw
    .split(/[\s;/+]+|,(?=\s)|(?<=\d)\s*-\s*(?=\d)/)
    .map((p) => cleanAmount(p))
    .filter((p) => num(p) > 0);
}

/* live statuses from /accounting/daily/preview-match */
type LiveStatus = "FOUND" | "SEVERAL" | "TAKEN" | "NOT_FOUND" | "NO_STATEMENT" | "AMBIGUOUS" | "LISTED";

const LIVE_TONE: Record<LiveStatus, string> = {
  FOUND: "MATCHED",
  SEVERAL: "POSSIBLE",
  AMBIGUOUS: "POSSIBLE",
  TAKEN: "UNMATCHED",
  NOT_FOUND: "UNMATCHED",
  NO_STATEMENT: "WAITING",
  LISTED: "NEW",
};

const LIVE_WORDS: Record<LiveStatus, string> = {
  FOUND: "On the statement",
  SEVERAL: "On the statement more than once: confirm which after saving",
  AMBIGUOUS: "",
  TAKEN: "Already matched to another shop's sheet",
  NOT_FOUND: "Not on the statement",
  NO_STATEMENT: "That bank's statement is not uploaded yet",
  LISTED: "",
};

const LIVE_TOTAL_WORDS: Record<LiveStatus, string> = {
  FOUND: "The statement's lines add up to it",
  SEVERAL: "",
  AMBIGUOUS: "Several sets of lines add up to it: choose them after saving",
  TAKEN: "",
  NOT_FOUND: "No set of the day's lines adds up to it",
  NO_STATEMENT: "That bank's statement is not uploaded yet",
  LISTED: "",
};

interface LiveResult {
  details: Record<string, { status: LiveStatus; description: string | null }>;
  totals: Record<string, { status: LiveStatus }>;
  counts: { found: number; total: number };
}

function useLiveMatch({
  date, recordId, details, totals, enabled,
}: {
  date: string;
  recordId?: number;
  details: Record<string, Chip[]>;
  totals: Record<string, string>;
  enabled: boolean;
}): LiveResult {
  const [result, setResult] = useState<LiveResult>({ details: {}, totals: {}, counts: { found: 0, total: 0 } });
  const signature = JSON.stringify([
    date, recordId,
    Object.entries(details).map(([k, chips]) => [k, chips.filter((c) => !c.id).map((c) => [c.key, c.amount])]),
    Object.entries(totals),
  ]);

  useEffect(() => {
    if (!enabled || !date) return;
    const fresh: { key: string; bank_id: number; currency_code: string; amount: string }[] = [];
    for (const [cell, chips] of Object.entries(details)) {
      const [bankId, code] = cell.split(":");
      for (const chip of chips) {
        if (chip.id || !(num(chip.amount) > 0)) continue;
        fresh.push({ key: chip.key, bank_id: Number(bankId), currency_code: code, amount: cleanAmount(chip.amount) });
      }
    }
    const totalCells = Object.entries(totals)
      .filter(([, v]) => num(v) > 0)
      .map(([cell, v]) => {
        const [bankId, code] = cell.split(":");
        return { key: cell, bank_id: Number(bankId), currency_code: code, amount: cleanAmount(v) };
      });
    // Saved deposits are part of the day too: send them so new ones never take their lines.
    const savedChips: { bank_id: number; currency_code: string; amount: string }[] = [];
    for (const [cell, chips] of Object.entries(details)) {
      const [bankId, code] = cell.split(":");
      for (const chip of chips) if (chip.id) savedChips.push({ bank_id: Number(bankId), currency_code: code, amount: cleanAmount(chip.amount) });
    }
    if (!fresh.length && !totalCells.length) {
      setResult({ details: {}, totals: {}, counts: { found: 0, total: 0 } });
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const answer = await api.post<{
          details: { status: LiveStatus; description: string | null }[];
          totals: { status: LiveStatus }[];
        }>("/accounting/daily/preview-match", {
          business_date: date,
          record_id: recordId ?? null,
          details: [...savedChips, ...fresh.map(({ bank_id, currency_code, amount }) => ({ bank_id, currency_code, amount }))],
          totals: totalCells.map(({ bank_id, currency_code, amount }) => ({ bank_id, currency_code, amount })),
        });
        const d: LiveResult["details"] = {};
        fresh.forEach((f, i) => { d[f.key] = answer.details[savedChips.length + i]; });
        const t: LiveResult["totals"] = {};
        totalCells.forEach((c, i) => { t[c.key] = answer.totals[i]; });
        setResult({
          details: d, totals: t,
          counts: { found: fresh.filter((f) => d[f.key]?.status === "FOUND").length, total: fresh.length },
        });
      } catch {
        /* a failed check just leaves the colours as they were */
      }
    }, 500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, enabled]);

  return result;
}

/** One cell of the paper grid. */
function P({
  children, head, center, className = "", tone, title,
}: {
  children?: React.ReactNode;
  head?: boolean;
  center?: boolean;
  className?: string;
  tone?: string | null;
  title?: string;
}) {
  return (
    <div
      title={title}
      className={`flex min-h-[2.1rem] items-center border-b border-r border-neutral-800 px-1.5 ${
        head ? "text-[12px] font-semibold uppercase" : ""} ${center ? "justify-center text-center" : ""} ${
        tone ? PAPER_TONE[tone] ?? "" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

const PAPER_TONE: Record<string, string> = {
  MATCHED: "bg-emerald-100 ring-2 ring-inset ring-emerald-500",
  POSSIBLE: "bg-amber-100 ring-2 ring-inset ring-amber-500",
  UNMATCHED: "bg-red-100 ring-2 ring-inset ring-red-500",
  DIFFERENT: "bg-red-100 ring-2 ring-inset ring-red-500",
  WAITING: "bg-neutral-100",
  NEW: "",
};

function Bar({ children }: { children?: React.ReactNode }) {
  return (
    <div className="col-span-5 flex min-h-[1rem] items-center border-b border-r border-neutral-800 bg-neutral-800 px-2 py-0.5">
      {children}
    </div>
  );
}

function Spacer() {
  return <div className="col-span-5 h-4 border-b border-r border-neutral-800" />;
}

function Num({
  value, onChange, disabled, integer, center, prefix, label,
}: {
  label?: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  integer?: boolean;
  center?: boolean;
  prefix?: string;
}) {
  return (
    <span className="flex w-full items-center">
      {prefix && <span className="text-xs text-neutral-500">{prefix}</span>}
      <input
        aria-label={label}
        className={`paper-input tabular w-full text-base ${center ? "text-center" : ""}`}
        inputMode={integer ? "numeric" : "decimal"}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(integer ? e.target.value.replace(/[^0-9]/g, "") : e.target.value)}
        onBlur={(e) => !integer && e.target.value && onChange(cleanAmount(e.target.value))}
      />
    </span>
  );
}

function Legend() {
  const items: [string, string][] = [
    ["bg-emerald-100 ring-emerald-500", "on the statement"],
    ["bg-amber-100 ring-amber-500", "confirm"],
    ["bg-red-100 ring-red-500", "not found"],
    ["bg-neutral-100 ring-neutral-300", "statement not uploaded"],
  ];
  return (
    <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-500">
      {items.map(([c, label]) => (
        <span key={label} className="inline-flex items-center gap-1">
          <span className={`inline-block h-3 w-3 rounded-sm ring-2 ring-inset ${c}`} /> {label}
        </span>
      ))}
    </div>
  );
}

/** TOTAL EXPENSES: written as on paper, "Kike 10,388 – Lenin 1,113 – Offload 100". */
function ExpenseLine({
  expenses, setExpenses, disabled,
}: {
  expenses: ExpenseRow[];
  setExpenses: React.Dispatch<React.SetStateAction<ExpenseRow[]>>;
  disabled?: boolean;
}) {
  const update = (key: string, patch: Partial<ExpenseRow>) =>
    setExpenses((r) => r.map((x) => (x.key === key ? { ...x, ...patch } : x)));
  return (
    <div className="flex flex-wrap items-end gap-x-2 gap-y-1">
      {expenses.map((e) => (
        <span key={e.key} className="inline-flex flex-col rounded border border-neutral-300 px-1">
          <input className="paper-input w-24 text-[11px] text-neutral-600" placeholder="for…" value={e.description}
            disabled={disabled} onChange={(ev) => update(e.key, { description: ev.target.value })} />
          <span className="flex items-center gap-0.5">
            <button type="button" disabled={disabled} title="Switch $ / C$"
              className="rounded px-0.5 text-[11px] font-semibold text-neutral-500 hover:bg-neutral-100"
              onClick={() => update(e.key, { currency_code: e.currency_code === "USD" ? "NIO" : "USD" })}>
              {e.currency_code === "USD" ? "$" : "C$"}
            </button>
            <input className="paper-input tabular w-20 text-sm" inputMode="decimal" value={e.amount} disabled={disabled}
              onChange={(ev) => update(e.key, { amount: ev.target.value })}
              onBlur={(ev) => ev.target.value && update(e.key, { amount: cleanAmount(ev.target.value) })} />
            {!disabled && (
              <button type="button" aria-label="Remove expense" className="text-neutral-400 hover:text-red-600"
                onClick={() => setExpenses((r) => r.filter((x) => x.key !== e.key))}>
                <X className="h-3 w-3" />
              </button>
            )}
          </span>
        </span>
      ))}
      {!disabled && (
        <button type="button" className="mb-0.5 inline-flex items-center gap-0.5 text-[11px] font-medium text-neutral-500 hover:text-neutral-900"
          onClick={() => setExpenses((r) => [...r, { key: newKey(), description: "", currency_code: "NIO", amount: "" }])}>
          <Plus className="h-3 w-3" /> expense
        </button>
      )}
    </div>
  );
}

/** A DETAIL row: each deposit a chip, coloured green as soon as the statement shows it. */
function DepositChips({
  chips, currency, disabled, tone, fromStatement, total, onAdd, onRemove,
}: {
  chips: Chip[];
  currency: Currency;
  disabled?: boolean;
  tone: (chip: Chip) => { tone: string; note: string };
  fromStatement: { transfer_id: number; amount: string; status: string; bank_description: string | null }[];
  total?: string;
  onAdd: (raw: string) => void;
  onRemove: (chipKey: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const sum = sumChips(chips) + fromStatement.reduce((s, l) => s + num(l.amount), 0);
  const mismatch = chips.length > 0 && num(total) > 0 && Math.abs(sumChips(chips) - num(total)) >= 0.005;
  return (
    <>
      {chips.map((chip) => {
        const t = tone(chip);
        return (
          <span key={chip.key} title={t.note}
            className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-sm tabular ${CHIP_TONE[t.tone] ?? CHIP_TONE.NEW}`}>
            {t.tone === "MATCHED" && <Check className="h-3.5 w-3.5" />}
            {fmt(num(chip.amount))}
            {!disabled && (
              <button type="button" aria-label="Remove payment" className="opacity-50 hover:opacity-100"
                onClick={() => onRemove(chip.key)}>
                <X className="h-3 w-3" />
              </button>
            )}
          </span>
        );
      })}
      {fromStatement.map((line) => (
        <span key={line.transfer_id} title={`From the statement: ${line.bank_description ?? ""}`}
          className={`inline-flex items-center gap-1 rounded border border-dashed px-1.5 py-0.5 text-sm tabular ${CHIP_TONE[line.status] ?? CHIP_TONE.NEW}`}>
          <Check className="h-3.5 w-3.5" /> {fmt(num(line.amount))}
        </span>
      ))}
      {!disabled && (
        <input
          aria-label="Add payments"
          className="paper-input tabular w-40 border-b border-dashed border-neutral-400 text-sm"
          inputMode="decimal"
          placeholder={chips.length ? "+ more (paste a list)" : "type or paste amounts"}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onPaste={(e) => {
            const text = e.clipboardData.getData("text");
            if (text.trim()) {
              e.preventDefault();
              onAdd(text);
              setDraft("");
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onAdd(draft);
              setDraft("");
            }
          }}
          onBlur={() => {
            if (draft) {
              onAdd(draft);
              setDraft("");
            }
          }}
        />
      )}
      {(chips.length > 0 || fromStatement.length > 0) && (
        <span className={`ml-auto text-xs tabular ${mismatch ? "font-semibold text-red-700" : "text-neutral-500"}`}>
          = {money(sum, currency)}
          {mismatch && ` (TRANSFERS says ${money(num(total), currency)})`}
        </span>
      )}
    </>
  );
}

const CHIP_TONE: Record<string, string> = {
  MATCHED: "border-emerald-600 bg-emerald-100 text-emerald-900",
  POSSIBLE: "border-amber-500 bg-amber-100 text-amber-900",
  UNMATCHED: "border-red-500 bg-red-100 text-red-800",
  DIFFERENT: "border-red-500 bg-red-100 text-red-800",
  PENDING_DEPOSIT: "border-sky-500 bg-sky-50 text-sky-800",
  WAITING: "border-neutral-300 bg-neutral-100 text-neutral-600",
  NEW: "border-neutral-400 bg-white text-neutral-900",
};

function CashStatus({ record }: { record: DailyRecord }) {
  const cash = record.transfers.filter((t) => t.payment_method === "CASH");
  if (!cash.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {cash.map((t) => <StatusBadge key={t.id} status={t.match_status} />)}
    </div>
  );
}

/** For a bank total with no listed deposits that the day's lines can't settle on their own. */
function PickButton({
  recordId, cell, currency, onDone,
}: {
  recordId: number;
  cell: BankCell;
  currency: Currency;
  onDone?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="block font-medium text-blue-700 hover:underline" onClick={() => setOpen(true)}>
        choose lines {currency === "USD" ? "$" : "C$"}
      </button>
      {open && cell.total_id && (
        <PickLinesModal recordId={recordId} totalId={cell.total_id} currency={currency}
          onClose={() => setOpen(false)} onDone={() => { setOpen(false); onDone?.(); }} />
      )}
    </>
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
              ? "Drop it here, choose it, or paste it (Ctrl+V). The amounts are read into the sheet for you to check."
              : "Drop it here, choose it, or paste it (Ctrl+V). It stays beside the sheet while you type it in."}
            {" "}It is deleted when you save.
          </p>
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
  const [keep, setKeep] = useState(true);
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
