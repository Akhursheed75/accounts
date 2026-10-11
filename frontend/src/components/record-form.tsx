"use client";

import { AlertTriangle, Banknote, Check, Landmark, Loader2, Plus, Trash2, Undo2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { SheetPhotoDrop, SheetPhotoPanel, useSheetPhotos } from "./sheet-photo";
import { Card, CurrencyTag, ErrorNote, StatusBadge, useToast } from "./ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, today } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type {
  BalanceSide, BaleType, Bank, Currency, DailyRecord, PaymentMethod, Shop,
} from "@/lib/types";

interface TransferDraft {
  key: string;
  id?: number;
  payment_method: PaymentMethod;
  bank_id: string;
  bank_account_id: string;
  currency_code: Currency;
  amount: string;
  reference: string;
  note: string;
  match_status?: string;
  direction: "CREDIT" | "DEBIT";
  bank_date: string;
}

interface ExpenseDraft {
  key: string;
  id?: number;
  category: string;
  description: string;
  currency_code: Currency;
  amount: string;
}

interface BaleDraft {
  key: string;
  id?: number;
  bale_type_id: number;
  bale_type_name: string;
  opening_qty: string;
  received_qty: string;
  sold_qty: string;
  closing_qty: string;
}

const newKey = () => Math.random().toString(36).slice(2);

type Tone = "green" | "amber" | "red" | "grey";
const ROW_TONE: Record<Tone, string> = {
  green: "border-emerald-500 bg-emerald-50",
  amber: "border-amber-500 bg-amber-50",
  red: "border-red-500 bg-red-50",
  grey: "border-ink-200 bg-ink-50/60",
};
const TEXT_TONE: Record<Tone, string> = {
  green: "text-emerald-700",
  amber: "text-amber-700",
  red: "text-red-700",
  grey: "text-ink-500",
};
const SAVED_WORDS: Record<string, string> = {
  MATCHED: "On the statement",
  POSSIBLE: "Confirm the match",
  UNMATCHED: "Not on the statement",
};
const LIVE_TONE: Record<string, Tone> = {
  FOUND: "green", SEVERAL: "amber", TAKEN: "red", NOT_FOUND: "red", NO_STATEMENT: "grey",
};
const LIVE_WORDS: Record<string, string> = {
  FOUND: "On the statement",
  SEVERAL: "On the statement twice: confirm after saving",
  TAKEN: "Already used by another shop's sheet",
  NOT_FOUND: "Not on the statement",
  NO_STATEMENT: "Statement not uploaded yet",
};

/** Only complains once something has been typed — a blank new row is not an error yet. */
function invalidAmount(raw: string): boolean {
  return raw.trim() !== "" && !(num(raw) > 0);
}

function num(value: string): number {
  const parsed = Number(cleanAmount(value));
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * People type what is on the deposit slip: "C$8,275.00", "$480", "8 275,00".
 * Rejecting those would be pedantic, so the field accepts them and tidies up
 * when you leave it. Whichever separator comes last is the decimal point.
 */
export function cleanAmount(raw: string): string {
  let text = (raw ?? "").replace(/[^\d.,-]/g, "").trim();
  if (!text) return "";
  const hasComma = text.includes(",");
  const hasDot = text.includes(".");
  if (hasComma && hasDot) {
    text =
      text.lastIndexOf(",") > text.lastIndexOf(".")
        ? text.replace(/\./g, "").replace(",", ".")
        : text.replace(/,/g, "");
  } else if (hasComma) {
    const parts = text.split(",");
    const looksLikeThousands = parts.length > 1 && parts.slice(1).every((p) => p.length === 3);
    text = looksLikeThousands ? text.replace(/,/g, "") : text.replace(",", ".");
  }
  return text;
}

export function RecordForm({ record }: { record?: DailyRecord }) {
  const router = useRouter();
  const toast = useToast();
  const { can } = useAuth();
  const editing = Boolean(record);

  // Fields of a saved sheet that this form does not edit; read loosely so the
  // form still builds against an older type definition.
  type KeptTransfer = { id: number; bank_date?: string | null; direction?: string };
  const kept = record as
    | (DailyRecord & {
        delivery_cash_usd?: string;
        delivery_transfer_usd?: string;
        commercial_invoice_cash_usd?: string;
        commercial_invoice_deposit_usd?: string;
        declared_closing_usd?: string | null;
        bank_totals?: { bank_id: number; currency_code: string; amount: string }[];
      })
    | undefined;
  const keptTransfer = (id?: number | null): KeptTransfer | undefined =>
    id ? (record?.transfers as KeptTransfer[] | undefined)?.find((t) => t.id === id) : undefined;

  const shops = useApi(() => api.get<Shop[]>("/shops"), []);
  const banks = useApi(() => api.get<Bank[]>("/banks"), []);
  const baleTypes = useApi(() => api.get<BaleType[]>("/accounting/bale-types"), []);

  const [shopId, setShopId] = useState(record ? String(record.shop_id) : "");
  const [date, setDate] = useState(record?.business_date ?? today());
  const [bales, setBales] = useState(String(record?.bale_count ?? 0));
  const [invoices, setInvoices] = useState(String(record?.invoice_count ?? 0));
  const [salesUsd, setSalesUsd] = useState(record?.total_sales_usd ?? "0.00");
  const [salesNio, setSalesNio] = useState(record?.total_sales_nio ?? "0.00");
  const [deliveryUsd, setDeliveryUsd] = useState(record?.delivery_usd ?? "0.00");
  const [deliveryNio, setDeliveryNio] = useState(record?.delivery_nio ?? "0.00");
  const [invoiceUsd, setInvoiceUsd] = useState(record?.commercial_invoice_usd ?? "0.00");
  const [invoiceNio, setInvoiceNio] = useState(record?.commercial_invoice_nio ?? "0.00");
  const [creditUsd, setCreditUsd] = useState(record?.credit_usd ?? "0.00");
  const [creditNio, setCreditNio] = useState(record?.credit_nio ?? "0.00");
  const [openUsd, setOpenUsd] = useState(record?.opening_balance_usd ?? "0.00");
  const [openNio, setOpenNio] = useState(record?.opening_balance_nio ?? "0.00");
  const [manualClose, setManualClose] = useState(record?.closing_balance_source === "MANUAL");
  const [closeUsd, setCloseUsd] = useState(record?.closing_balance_usd ?? "0.00");
  const [closeNio, setCloseNio] = useState(record?.closing_balance_nio ?? "0.00");
  const [observations, setObservations] = useState(record?.observations ?? "");
  const [status, setStatus] = useState(record?.status === "LOCKED" ? "SUBMITTED" : record?.status ?? "DRAFT");

  const [transfers, setTransfers] = useState<TransferDraft[]>(
    record?.transfers.map((t) => ({
      key: newKey(),
      id: t.id,
      payment_method: t.payment_method ?? "BANK",
      bank_id: t.bank_id ? String(t.bank_id) : "",
      bank_account_id: t.bank_account_id ? String(t.bank_account_id) : "",
      currency_code: t.currency_code,
      amount: t.amount,
      reference: t.reference ?? "",
      note: t.note,
      match_status: t.match_status,
      direction: t.direction ?? "CREDIT",
      bank_date: t.bank_date ?? "",
    })) ?? [],
  );
  const [expenses, setExpenses] = useState<ExpenseDraft[]>(
    record?.expenses.map((e) => ({
      key: newKey(),
      id: e.id,
      category: e.category,
      description: e.description,
      currency_code: e.currency_code,
      amount: e.amount,
    })) ?? [],
  );
  const [baleRows, setBaleRows] = useState<BaleDraft[]>(
    record?.bale_records.map((b) => ({
      key: newKey(),
      id: b.id,
      bale_type_id: b.bale_type_id,
      bale_type_name: b.bale_type_name ?? b.bale_type_code ?? "",
      opening_qty: String(b.opening_qty),
      received_qty: String(b.received_qty),
      sold_qty: String(b.sold_qty),
      closing_qty: String(b.closing_qty),
    })) ?? [],
  );

  // One row per bale type, matching the paper form. An older sheet saved before
  // a bale type existed gets the missing row added rather than showing a table
  // with headers and nothing under them.
  useEffect(() => {
    if (!baleTypes.data) return;
    setBaleRows((current) => {
      const present = new Set(current.map((row) => row.bale_type_id));
      const missing = baleTypes.data!.filter((type) => !present.has(type.id));
      if (missing.length === 0) return current;
      return [
        ...current,
        ...missing.map((type) => ({
          key: newKey(),
          bale_type_id: type.id,
          bale_type_name: type.name,
          opening_qty: "0",
          received_qty: "0",
          sold_qty: "0",
          closing_qty: "0",
        })),
      ];
    });
  }, [baleTypes.data]);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // Memoised so the callbacks below are not rebuilt on every keystroke.
  const bankList = useMemo(() => banks.data ?? [], [banks.data]);

  // Bank and cash are separate lines on the sheet, as they are on paper.
  const transferTotals = useMemo(() => {
    const totals = { USD: 0, NIO: 0 };
    for (const t of transfers) {
      if (t.payment_method === "BANK") totals[t.currency_code] += (t.direction === "DEBIT" ? -1 : 1) * num(t.amount);
    }
    return totals;
  }, [transfers]);

  const cashTotals = useMemo(() => {
    const totals = { USD: 0, NIO: 0 };
    for (const t of transfers) if (t.payment_method === "CASH") totals[t.currency_code] += num(t.amount);
    return totals;
  }, [transfers]);

  // The month's rate, if an administrator has set one, so the day's payments
  // can also be read as a single USD figure. Display only: nothing is saved.
  const rate = useApi(
    () => api.get<{ nio_per_usd: string | null }>("/monthly/rate", { on: date }),
    [date.slice(0, 7)],
  );
  const nioPerUsd = rate.data?.nio_per_usd ? Number(rate.data.nio_per_usd) : null;

  // Which lines make up the closing balance, as set in Settings. If they
  // cannot be read (a user without settings access), the default formula.
  const systemSettings = useApi(
    () =>
      api.get<{ balance_components: { key: string; sign: number; enabled: boolean }[] }>(
        "/settings/system",
      ),
    [],
  );
  const balanceComponents = useMemo(
    () =>
      systemSettings.data?.balance_components ?? [
        { key: "opening_balance", sign: 1, enabled: true },
        { key: "total_sales", sign: 1, enabled: true },
        { key: "total_expenses", sign: -1, enabled: true },
        { key: "total_transfers", sign: -1, enabled: true },
        { key: "total_cash", sign: -1, enabled: true },
      ],
    [systemSettings.data],
  );
  const receivedInUsd =
    nioPerUsd && nioPerUsd > 0
      ? transferTotals.USD + cashTotals.USD + (transferTotals.NIO + cashTotals.NIO) / nioPerUsd
      : null;

  // Two identical rows are usually one slip typed twice.
  const duplicateKeys = useMemo(() => {
    const seen = new Map<string, string>();
    const dupes = new Set<string>();
    for (const t of transfers) {
      const amount = num(t.amount);
      if (!(amount > 0)) continue;
      const id = `${t.payment_method}|${t.bank_id}|${t.currency_code}|${amount.toFixed(2)}|${t.reference.trim()}`;
      const first = seen.get(id);
      if (first) {
        dupes.add(first);
        dupes.add(t.key);
      } else {
        seen.set(id, t.key);
      }
    }
    return dupes;
  }, [transfers]);

  const expenseTotals = useMemo(() => {
    const totals = { USD: 0, NIO: 0 };
    for (const expense of expenses) totals[expense.currency_code] += num(expense.amount);
    return totals;
  }, [expenses]);

  // Mirrors the server's default formula so the figure updates as you type. The
  // server remains the authority and returns its own breakdown after saving.
  const computed = useMemo(
    () => ({
      USD: num(openUsd) + num(salesUsd) - expenseTotals.USD - transferTotals.USD - cashTotals.USD,
      NIO: num(openNio) + num(salesNio) - expenseTotals.NIO - transferTotals.NIO - cashTotals.NIO,
    }),
    [openUsd, openNio, salesUsd, salesNio, expenseTotals, transferTotals, cashTotals],
  );

  // The paper sheet closes in dollars only: every cordoba amount is converted
  // at the month's rate before it is added or subtracted, following the
  // components switched on in Settings (delivery and credit included). Without
  // a rate there is no honest single figure, so null.
  const computedUsdTotal = useMemo(() => {
    if (!nioPerUsd || nioPerUsd <= 0) return null;
    const values: Record<string, { USD: number; NIO: number }> = {
      opening_balance: { USD: num(openUsd), NIO: num(openNio) },
      total_sales: { USD: num(salesUsd), NIO: num(salesNio) },
      total_expenses: expenseTotals,
      total_transfers: transferTotals,
      total_cash: cashTotals,
      delivery: {
        USD: num(deliveryUsd) + num(kept?.delivery_cash_usd ?? "0") + num(kept?.delivery_transfer_usd ?? "0"),
        NIO: num(deliveryNio),
      },
      credit: { USD: num(creditUsd), NIO: num(creditNio) },
      commercial_invoice: {
        USD:
          num(invoiceUsd) +
          num(kept?.commercial_invoice_cash_usd ?? "0") +
          num(kept?.commercial_invoice_deposit_usd ?? "0"),
        NIO: num(invoiceNio),
      },
    };
    let total = 0;
    for (const c of balanceComponents) {
      if (!c.enabled || !c.sign) continue;
      const v = values[c.key];
      if (v) total += c.sign * (v.USD + v.NIO / nioPerUsd);
    }
    return total;
  }, [
    nioPerUsd, balanceComponents, openUsd, openNio, salesUsd, salesNio, expenseTotals,
    transferTotals, cashTotals, deliveryUsd, deliveryNio, creditUsd, creditNio,
    invoiceUsd, invoiceNio, kept,
  ]);

  // Focus moves to the amount of whichever row was just created, so a second
  // deposit is "Enter, type, Enter" rather than a reach for the mouse.
  const amountInputs = useRef<Record<string, HTMLInputElement | null>>({});
  const [focusRow, setFocusRow] = useState<string | null>(null);

  useEffect(() => {
    if (!focusRow) return;
    amountInputs.current[focusRow]?.focus();
    setFocusRow(null);
  }, [focusRow, transfers]);

  const addTransfer = useCallback(
    (method?: PaymentMethod) => {
      const key = newKey();
      setTransfers((rows) => {
        // Most days a shop banks into the same place twice, so a new row starts
        // from the previous one rather than from the top of the list — unless
        // the button pressed says which kind of payment it is.
        const previous = rows[rows.length - 1];
        const paymentMethod = method ?? previous?.payment_method ?? "BANK";
        const lastBank = [...rows].reverse().find((r) => r.payment_method === "BANK");
        return [
          ...rows,
          {
            key,
            payment_method: paymentMethod,
            bank_id:
              paymentMethod === "CASH"
                ? ""
                : lastBank?.bank_id || (bankList[0] ? String(bankList[0].id) : ""),
            bank_account_id:
              paymentMethod === "CASH" ? "" : (lastBank?.bank_account_id ?? ""),
            currency_code: previous?.currency_code ?? "USD",
            amount: "",
            reference: "",
            note: "",
            direction: "CREDIT",
            bank_date: "",
          },
        ];
      });
      setFocusRow(key);
    },
    [bankList],
  );

  function updateTransfer(key: string, patch: Partial<TransferDraft>) {
    setTransfers((rows) =>
      rows.map((row) => {
        if (row.key !== key) return row;
        const next = { ...row, ...patch };
        // A changed bank, currency or amount is a different payment: its old
        // bank match no longer says anything, so it is checked again.
        const changed =
          next.payment_method !== row.payment_method || next.bank_id !== row.bank_id
          || next.currency_code !== row.currency_code || num(next.amount) !== num(row.amount)
          || next.direction !== row.direction || next.bank_date !== row.bank_date;
        return changed ? { ...next, match_status: undefined } : next;
      }),
    );
  }

  /** "185-1510", "185 1510" or a pasted list: one row per payment, same bank and currency. */
  function splitInto(key: string, raw: string): boolean {
    const parts = raw
      .split(/[\s;/+]+|,(?=\s)|(?<=\d)\s*-\s*(?=\d)/)
      .map((p) => cleanAmount(p))
      .filter((p) => num(p) > 0);
    if (parts.length < 2) return false;
    const lastKey = newKey();
    setTransfers((rows) => {
      const i = rows.findIndex((r) => r.key === key);
      if (i < 0) return rows;
      const row = rows[i];
      const extra = parts.slice(1).map((amount, n) => ({
        ...row, key: n === parts.length - 2 ? lastKey : newKey(), id: undefined,
        amount, reference: "", note: "", match_status: undefined, bank_date: "",
      }));
      const first = { ...row, amount: parts[0], match_status: num(parts[0]) === num(row.amount) ? row.match_status : undefined };
      return [...rows.slice(0, i), first, ...extra, ...rows.slice(i + 1)];
    });
    setFocusRow(lastKey);
    return true;
  }

  /** "-" after an amount, as written on paper: the next payment, same bank and currency. */
  function nextLike(key: string) {
    const fresh = newKey();
    setTransfers((rows) => {
      const i = rows.findIndex((r) => r.key === key);
      if (i < 0) return rows;
      const row = rows[i];
      const added = { ...row, key: fresh, id: undefined, amount: "", reference: "", note: "", match_status: undefined, bank_date: "" };
      return [...rows.slice(0, i + 1), added, ...rows.slice(i + 1)];
    });
    setFocusRow(fresh);
  }

  /* Green while typing: each bank payment is checked against the uploaded
     statements as it is entered, before anything is saved. */
  const [live, setLive] = useState<Record<string, { status: string; description: string | null }>>({});
  const liveSignature = JSON.stringify([
    date, record?.id,
    transfers.map((t) => [t.key, t.payment_method, t.bank_id, t.currency_code, num(t.amount), Boolean(t.match_status), t.direction, t.bank_date]),
  ]);
  useEffect(() => {
    const bankRows = transfers.filter((t) => t.payment_method === "BANK" && t.bank_id && num(t.amount) > 0);
    const saved = bankRows.filter((t) => t.match_status);
    const fresh = bankRows.filter((t) => !t.match_status);
    if (!fresh.length || !date) {
      setLive({});
      return;
    }
    const line = (t: TransferDraft) => ({
      bank_id: Number(t.bank_id), currency_code: t.currency_code, amount: cleanAmount(t.amount),
      bank_date: t.bank_date || null, direction: t.direction,
    });
    const timer = setTimeout(async () => {
      try {
        const answer = await api.post<{ details: { status: string; description: string | null }[] }>(
          "/accounting/daily/preview-match",
          { business_date: date, record_id: record?.id ?? null, details: [...saved, ...fresh].map(line), totals: [] },
        );
        const out: Record<string, { status: string; description: string | null }> = {};
        fresh.forEach((t, i) => { out[t.key] = answer.details[saved.length + i]; });
        setLive(out);
      } catch {
        /* the colours just stay as they were */
      }
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveSignature]);

  /** green / amber / red / grey for one payment row, and the words for it. */
  function rowState(t: TransferDraft): { tone: Tone; words: string } | null {
    if (t.payment_method !== "BANK" || !(num(t.amount) > 0) || !t.bank_id) return null;
    if (t.match_status) {
      const tone: Tone = t.match_status === "MATCHED" ? "green"
        : t.match_status === "POSSIBLE" ? "amber"
          : t.match_status === "UNMATCHED" ? "red" : "grey";
      return { tone, words: SAVED_WORDS[t.match_status] ?? t.match_status.toLowerCase() };
    }
    const l = live[t.key];
    if (!l) return { tone: "grey", words: "Checking…" };
    return { tone: LIVE_TONE[l.status] ?? "grey", words: LIVE_WORDS[l.status] ?? l.status };
  }
  const liveCount = transfers.filter((t) => rowState(t)?.tone === "green").length;
  const bankCount = transfers.filter((t) => rowState(t)).length;

  const [photoError, setPhotoError] = useState<unknown>(null);
  const sheetPhotos = useSheetPhotos(setPhotoError);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    const badTransfer = transfers.find((t) => !(num(t.amount) > 0));
    if (badTransfer) {
      setError(new Error("Every payment needs an amount greater than zero."));
      return;
    }
    if (transfers.some((t) => t.payment_method === "BANK" && !t.bank_id)) {
      setError(new Error("Choose the bank for every bank payment, or mark it as cash."));
      return;
    }
    if (!shopId) {
      setError(new Error("Choose a shop."));
      return;
    }

    const payload = {
      shop_id: Number(shopId),
      business_date: date,
      bale_count: Number(bales) || 0,
      invoice_count: Number(invoices) || 0,
      total_sales_usd: salesUsd || "0",
      total_sales_nio: salesNio || "0",
      delivery_usd: deliveryUsd || "0",
      delivery_nio: deliveryNio || "0",
      commercial_invoice_usd: invoiceUsd || "0",
      commercial_invoice_nio: invoiceNio || "0",
      credit_usd: creditUsd || "0",
      credit_nio: creditNio || "0",
      opening_balance_usd: openUsd || "0",
      opening_balance_nio: openNio || "0",
      closing_balance_usd: manualClose ? closeUsd || "0" : null,
      closing_balance_nio: manualClose ? closeNio || "0" : null,
      closing_balance_source: manualClose ? "MANUAL" : "COMPUTED",
      observations,
      status,
      // Fields this form does not show are sent back as they were. The API
      // resets anything left out to zero, so without these a save here
      // silently wiped the delivery split, the bank totals and the written
      // closing balance.
      delivery_cash_usd: kept?.delivery_cash_usd ?? "0",
      delivery_transfer_usd: kept?.delivery_transfer_usd ?? "0",
      commercial_invoice_cash_usd: kept?.commercial_invoice_cash_usd ?? "0",
      commercial_invoice_deposit_usd: kept?.commercial_invoice_deposit_usd ?? "0",
      declared_closing_usd: kept?.declared_closing_usd ?? null,
      bank_totals: (kept?.bank_totals ?? []).map((b) => ({
        bank_id: b.bank_id,
        currency_code: b.currency_code,
        amount: b.amount,
      })),
      transfers: transfers.map((t) => ({
        id: t.id,
        payment_method: t.payment_method,
        bank_id: t.payment_method === "CASH" ? null : Number(t.bank_id),
        bank_account_id:
          t.payment_method === "CASH" || !t.bank_account_id ? null : Number(t.bank_account_id),
        currency_code: t.currency_code,
        amount: cleanAmount(t.amount),
        reference: t.reference || null,
        note: t.note,
        direction: t.payment_method === "CASH" ? "CREDIT" : t.direction,
        bank_date: t.bank_date || null,
      })),
      expenses: expenses.map((e) => ({
        id: e.id,
        category: e.category || "GENERAL",
        description: e.description,
        currency_code: e.currency_code,
        amount: e.amount || "0",
      })),
      photo_ids: sheetPhotos.ids,
      bale_records: baleRows.map((b) => ({
        id: b.id,
        bale_type_id: b.bale_type_id,
        opening_qty: Number(b.opening_qty) || 0,
        received_qty: Number(b.received_qty) || 0,
        sold_qty: Number(b.sold_qty) || 0,
        closing_qty: Number(b.closing_qty) || 0,
      })),
    };

    setSaving(true);
    try {
      const saved = record
        ? await api.put<DailyRecord>(`/accounting/daily/${record.id}`, payload)
        : await api.post<DailyRecord>("/accounting/daily", payload);
      toast.push("ok", editing ? "Sheet saved." : "Sheet created and matched against the banks.");
      router.push(`/accounting/${saved.id}`);
      router.refresh();
    } catch (err) {
      setError(err);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setSaving(false);
    }
  }

  const readOnly = record?.status === "LOCKED" && !can("accounting.lock");

  return (
    <div className={sheetPhotos.photos.length ? "grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]" : ""}>
    {sheetPhotos.photos.length > 0 && <SheetPhotoPanel photos={sheetPhotos.photos} />}
    <form onSubmit={submit} className="min-w-0 space-y-4 pb-24">
      <ErrorNote error={error ?? photoError} />
      {!readOnly && (
        <SheetPhotoDrop hasPhoto={sheetPhotos.photos.length > 0} uploading={sheetPhotos.uploading}
          onFile={sheetPhotos.add} />
      )}

      {readOnly && (
        <div className="rounded-lg border border-ink-300 bg-ink-100 px-3 py-2 text-sm text-ink-700">
          This sheet is locked. Ask an administrator to unlock it before editing.
        </div>
      )}

      <Card title="A · Daily information">
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block">
            <span className="label">Shop</span>
            <select
              className="input"
              value={shopId}
              disabled={editing || readOnly}
              onChange={(e) => setShopId(e.target.value)}
              required
            >
              <option value="">Choose a shop…</option>
              {(shops.data ?? []).map((shop) => (
                <option key={shop.id} value={shop.id}>
                  {shop.name} {shop.city_name ? `— ${shop.city_name}` : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Date</span>
            <input
              type="date"
              className="input"
              value={date}
              disabled={editing || readOnly}
              max={today()}
              onChange={(e) => setDate(e.target.value)}
              required
            />
          </label>
          <label className="block">
            <span className="label">Status</span>
            <select
              className="input"
              value={status}
              disabled={readOnly}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="DRAFT">Draft — still being entered</option>
              <option value="SUBMITTED">Submitted — ready for reconciliation</option>
            </select>
          </label>
        </div>
      </Card>

      <Card title="B · Sales summary">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MoneyField label="Total sales (USD)" value={salesUsd} onChange={setSalesUsd} disabled={readOnly} currency="USD" />
          <MoneyField label="Total sales (C$)" value={salesNio} onChange={setSalesNio} disabled={readOnly} currency="NIO" />
          <IntField label="Quantity of bales" value={bales} onChange={setBales} disabled={readOnly} />
          <IntField label="Number of invoices" value={invoices} onChange={setInvoices} disabled={readOnly} />
        </div>
      </Card>

      <Card
        title="C · Payments received"
        description="One row per bank deposit. Cash taken at the shop goes in as cash — it is matched to the bank deposit later."
        actions={
          !readOnly && (
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn-secondary btn-sm" onClick={() => addTransfer("BANK")}>
                <Landmark className="h-3.5 w-3.5" />
                Add bank payment
              </button>
              <button type="button" className="btn-secondary btn-sm" onClick={() => addTransfer("CASH")}>
                <Banknote className="h-3.5 w-3.5" />
                Add cash
              </button>
            </div>
          )
        }
      >
        {transfers.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-5 text-center">
            <p className="text-sm text-ink-500">No payments recorded for this day yet.</p>
            {!readOnly && (
              <div className="flex flex-wrap justify-center gap-2">
                <button type="button" className="btn-primary btn-sm" onClick={() => addTransfer("BANK")}>
                  <Landmark className="h-3.5 w-3.5" />
                  Add bank payment
                </button>
                <button type="button" className="btn-secondary btn-sm" onClick={() => addTransfer("CASH")}>
                  <Banknote className="h-3.5 w-3.5" />
                  Add cash
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {transfers.map((transfer, index) => {
              const cash = transfer.payment_method === "CASH";
              const bank = bankList.find((b) => String(b.id) === transfer.bank_id);
              const accounts = (bank?.accounts ?? []).filter(
                (a) => a.currency_code === transfer.currency_code,
              );
              const duplicate = duplicateKeys.has(transfer.key);
              const state = rowState(transfer);
              return (
                <div
                  key={transfer.key}
                  className={`rounded-lg border p-3 ${
                    cash ? "border-sky-200 bg-sky-50/50" : state ? ROW_TONE[state.tone] : "border-ink-200 bg-ink-50/60"
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <span className="tabular w-5 text-xs font-semibold text-ink-400">{index + 1}</span>

                    {/* One click picks where the money went: a bank, or cash. */}
                    <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Paid by">
                      {bankList.map((b) => {
                        const active = !cash && transfer.bank_id === String(b.id);
                        return (
                          <button
                            key={b.id}
                            type="button"
                            role="radio"
                            aria-checked={active}
                            disabled={readOnly}
                            onClick={() =>
                              updateTransfer(transfer.key, {
                                payment_method: "BANK",
                                bank_id: String(b.id),
                                bank_account_id: "",
                              })
                            }
                            className={`rounded-md border px-2 py-1 text-xs font-semibold transition ${
                              active
                                ? "border-brand-600 bg-brand-600 text-white"
                                : "border-ink-300 bg-surface text-ink-700 hover:bg-ink-100"
                            }`}
                          >
                            {b.code}
                          </button>
                        );
                      })}
                      <button
                        type="button"
                        role="radio"
                        aria-checked={cash}
                        disabled={readOnly}
                        onClick={() =>
                          updateTransfer(transfer.key, {
                            payment_method: "CASH",
                            bank_id: "",
                            bank_account_id: "",
                          })
                        }
                        className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-semibold transition ${
                          cash
                            ? "border-sky-600 bg-sky-600 text-white"
                            : "border-ink-300 bg-surface text-ink-700 hover:bg-ink-100"
                        }`}
                      >
                        <Banknote className="h-3.5 w-3.5" />
                        Cash
                      </button>
                      {!cash && (
                        <button
                          type="button"
                          aria-pressed={transfer.direction === "DEBIT"}
                          disabled={readOnly}
                          title="Money paid back out of the bank, matched to the debit on the statement"
                          onClick={() =>
                            updateTransfer(transfer.key, {
                              direction: transfer.direction === "DEBIT" ? "CREDIT" : "DEBIT",
                            })
                          }
                          className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-semibold transition ${
                            transfer.direction === "DEBIT"
                              ? "border-violet-600 bg-violet-600 text-white"
                              : "border-ink-300 bg-surface text-ink-700 hover:bg-ink-100"
                          }`}
                        >
                          <Undo2 className="h-3.5 w-3.5" />
                          Refund
                        </button>
                      )}
                    </div>

                    {/* Currency as a two-way switch: the choice is always one of two. */}
                    <div className="inline-flex overflow-hidden rounded-md border border-ink-300" role="radiogroup" aria-label="Currency">
                      {(["USD", "NIO"] as const).map((code) => (
                        <button
                          key={code}
                          type="button"
                          role="radio"
                          aria-checked={transfer.currency_code === code}
                          disabled={readOnly}
                          onClick={() =>
                            updateTransfer(transfer.key, { currency_code: code, bank_account_id: "" })
                          }
                          className={`px-2.5 py-1 text-xs font-semibold transition ${
                            transfer.currency_code === code
                              ? "bg-ink-800 text-white"
                              : "bg-surface text-ink-600 hover:bg-ink-100"
                          }`}
                        >
                          {code === "USD" ? "$ USD" : "C$"}
                        </button>
                      ))}
                    </div>

                    <div className="relative min-w-[8rem] flex-1 sm:max-w-[12rem]">
                      <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-ink-400">
                        {transfer.direction === "DEBIT" && !cash ? "−" : ""}
                        {transfer.currency_code === "USD" ? "$" : "C$"}
                      </span>
                      <input
                        ref={(el) => {
                          amountInputs.current[transfer.key] = el;
                        }}
                        className={`input tabular pl-8 text-base font-medium ${
                          invalidAmount(transfer.amount) ? "border-red-500 focus:border-red-500" : ""
                        }`}
                        inputMode="decimal"
                        value={transfer.amount}
                        disabled={readOnly}
                        aria-label={`Amount for payment ${index + 1}`}
                        onChange={(e) => {
                          if (!splitInto(transfer.key, e.target.value)) {
                            updateTransfer(transfer.key, { amount: e.target.value });
                          }
                        }}
                        onPaste={(e) => {
                          if (splitInto(transfer.key, e.clipboardData.getData("text"))) e.preventDefault();
                        }}
                        onBlur={(e) =>
                          updateTransfer(transfer.key, { amount: cleanAmount(e.target.value) })
                        }
                        onKeyDown={(e) => {
                          if (e.key === "-" && num(transfer.amount) > 0 && !readOnly) {
                            e.preventDefault();
                            updateTransfer(transfer.key, { amount: cleanAmount(transfer.amount) });
                            nextLike(transfer.key);
                            return;
                          }
                          if (e.key !== "Enter") return;
                          // Enter would otherwise submit the whole sheet; here it
                          // means "this one is done, give me another row".
                          e.preventDefault();
                          updateTransfer(transfer.key, { amount: cleanAmount(transfer.amount) });
                          if (num(transfer.amount) > 0 && !readOnly) addTransfer();
                        }}
                        placeholder="0.00"
                        aria-invalid={invalidAmount(transfer.amount)}
                      />
                    </div>

                    <div className="ml-auto flex items-center gap-2">
                      {state ? (
                        <span className={`inline-flex items-center gap-1 text-xs font-semibold ${TEXT_TONE[state.tone]}`}>
                          {state.tone === "green" ? <Check className="h-4 w-4" /> : state.tone === "red" ? <X className="h-4 w-4" /> : null}
                          {state.words}
                        </span>
                      ) : (
                        transfer.match_status && <StatusBadge status={transfer.match_status} />
                      )}
                      {!readOnly && (
                        <button
                          type="button"
                          className="btn-ghost btn-sm text-red-600"
                          onClick={() =>
                            setTransfers((rows) => rows.filter((r) => r.key !== transfer.key))
                          }
                          aria-label={`Remove payment ${index + 1}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="mt-2 grid gap-2 sm:grid-cols-4 sm:pl-8">
                    {!cash && (
                      <label className="flex items-center gap-1.5 text-xs text-ink-500" title="The day the bank statement shows it, when that is not this sheet's day">
                        <span className="shrink-0">Bank date</span>
                        <input
                          type="date"
                          className="input py-1 text-xs"
                          value={transfer.bank_date}
                          disabled={readOnly}
                          aria-label={`Bank date for payment ${index + 1}`}
                          onChange={(e) => updateTransfer(transfer.key, { bank_date: e.target.value })}
                        />
                      </label>
                    )}
                    {!cash && (
                      <select
                        className="input py-1.5 text-xs"
                        value={transfer.bank_account_id}
                        disabled={readOnly || accounts.length === 0}
                        aria-label="Account"
                        onChange={(e) =>
                          updateTransfer(transfer.key, { bank_account_id: e.target.value })
                        }
                      >
                        <option value="">Any {transfer.currency_code === "USD" ? "$" : "C$"} account</option>
                        {accounts.map((account) => (
                          <option key={account.id} value={account.id}>
                            {account.label}
                          </option>
                        ))}
                      </select>
                    )}
                    <input
                      className="input py-1.5 text-xs"
                      value={transfer.reference}
                      disabled={readOnly}
                      aria-label="Reference"
                      onChange={(e) => updateTransfer(transfer.key, { reference: e.target.value })}
                      placeholder={cash ? "Receipt no. (optional)" : "Deposit slip no."}
                    />
                    <input
                      className={`input py-1.5 text-xs ${cash ? "sm:col-span-3" : ""}`}
                      value={transfer.note}
                      disabled={readOnly}
                      aria-label="Note"
                      onChange={(e) => updateTransfer(transfer.key, { note: e.target.value })}
                      placeholder={cash ? "Who paid, or a note" : "Note (optional)"}
                    />
                  </div>

                  {invalidAmount(transfer.amount) && (
                    <p className="mt-1 text-xs text-red-600 sm:pl-8">The amount needs to be more than zero.</p>
                  )}
                  {duplicate && (
                    <p className="mt-1 flex items-center gap-1 text-xs text-amber-700 sm:pl-8">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      Same amount entered twice — check it is not the same slip.
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {!readOnly && transfers.length > 0 && (
          <p className="mt-2 text-xs text-ink-500">
            Type the breakdown as on paper, <kbd className="rounded border border-ink-300 px-1">185-1510</kbd>,
            or paste a list: each amount becomes its own row with the same bank and currency, and turns
            green as soon as the uploaded statement shows it ({liveCount} of {bankCount} found).
            <kbd className="rounded border border-ink-300 px-1">Enter</kbd> also starts the next row. Enter the day&apos;s cash as one
            line per currency — the amount the shop will take to the bank — so it can be matched to
            that deposit.
          </p>
        )}

        <div className="mt-3 grid gap-2 border-t border-ink-200 pt-3 text-sm sm:grid-cols-3">
          <div>
            <p className="text-xs text-ink-500">
              <Landmark className="mr-1 inline h-3.5 w-3.5" />
              Bank payments
            </p>
            <p className="tabular font-medium">
              {money(transferTotals.USD, "USD")} · {money(transferTotals.NIO, "NIO")}
            </p>
          </div>
          <div>
            <p className="text-xs text-ink-500">
              <Banknote className="mr-1 inline h-3.5 w-3.5" />
              Cash
            </p>
            <p className="tabular font-medium">
              {money(cashTotals.USD, "USD")} · {money(cashTotals.NIO, "NIO")}
            </p>
          </div>
          <div>
            <p className="text-xs text-ink-500">Total received in USD</p>
            {receivedInUsd !== null ? (
              <p className="tabular font-semibold">
                {money(receivedInUsd, "USD")}
                <span className="ml-1 text-xs font-normal text-ink-500">
                  at C${nioPerUsd} per $1
                </span>
              </p>
            ) : (
              <p className="text-xs text-ink-500">Shown once this month&apos;s exchange rate is set.</p>
            )}
          </div>
        </div>
      </Card>

      <Card
        title="D · Expenses"
        actions={
          !readOnly && (
            <button
              type="button"
              className="btn-secondary btn-sm"
              onClick={() =>
                setExpenses((rows) => [
                  ...rows,
                  { key: newKey(), category: "GENERAL", description: "", currency_code: "USD", amount: "" },
                ])
              }
            >
              <Plus className="h-3.5 w-3.5" />
              Add expense
            </button>
          )
        }
      >
        {expenses.length === 0 ? (
          <p className="py-3 text-sm text-ink-500">No expenses recorded.</p>
        ) : (
          <div className="space-y-2">
            {expenses.map((expense) => (
              <div
                key={expense.key}
                className="grid gap-2 rounded-lg border border-ink-200 bg-ink-50/60 p-3 sm:grid-cols-12"
              >
                <label className="sm:col-span-3">
                  <span className="label">Category</span>
                  <input
                    className="input"
                    value={expense.category}
                    disabled={readOnly}
                    onChange={(e) =>
                      setExpenses((rows) =>
                        rows.map((r) => (r.key === expense.key ? { ...r, category: e.target.value } : r)),
                      )
                    }
                  />
                </label>
                <label className="sm:col-span-5">
                  <span className="label">Description</span>
                  <input
                    className="input"
                    value={expense.description}
                    disabled={readOnly}
                    onChange={(e) =>
                      setExpenses((rows) =>
                        rows.map((r) => (r.key === expense.key ? { ...r, description: e.target.value } : r)),
                      )
                    }
                  />
                </label>
                <label className="sm:col-span-2">
                  <span className="label">Currency</span>
                  <select
                    className="input"
                    value={expense.currency_code}
                    disabled={readOnly}
                    onChange={(e) =>
                      setExpenses((rows) =>
                        rows.map((r) =>
                          r.key === expense.key ? { ...r, currency_code: e.target.value as Currency } : r,
                        ),
                      )
                    }
                  >
                    <option value="USD">USD $</option>
                    <option value="NIO">C$</option>
                  </select>
                </label>
                <label className="sm:col-span-1">
                  <span className="label">Amount</span>
                  <input
                    className="input tabular"
                    inputMode="decimal"
                    value={expense.amount}
                    disabled={readOnly}
                    onChange={(e) =>
                      setExpenses((rows) =>
                        rows.map((r) => (r.key === expense.key ? { ...r, amount: e.target.value } : r)),
                      )
                    }
                  />
                </label>
                <div className="flex items-end sm:col-span-1">
                  {!readOnly && (
                    <button
                      type="button"
                      className="btn-ghost btn-sm text-red-600"
                      onClick={() => setExpenses((rows) => rows.filter((r) => r.key !== expense.key))}
                      aria-label="Remove expense"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-4 border-t border-ink-200 pt-3 text-sm">
          <span className="text-ink-500">Total expenses</span>
          <span className="tabular font-medium">
            <CurrencyTag code="USD" /> {money(expenseTotals.USD, "USD")}
          </span>
          <span className="tabular font-medium">
            <CurrencyTag code="NIO" /> {money(expenseTotals.NIO, "NIO")}
          </span>
        </div>
      </Card>

      <Card title="E · Bales and balances">
        <div className="table-scroll mb-4">
          <table className="w-full min-w-[520px]">
            <thead>
              <tr>
                <th className="th">Bale type</th>
                <th className="th text-right">Opening</th>
                <th className="th text-right">Received</th>
                <th className="th text-right">Sold</th>
                <th className="th text-right">Closing</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {baleRows.map((row) => (
                <tr key={row.key}>
                  <td className="td font-medium">{row.bale_type_name}</td>
                  {(["opening_qty", "received_qty", "sold_qty", "closing_qty"] as const).map((field) => (
                    <td key={field} className="td text-right">
                      <input
                        className="input tabular w-20 text-right"
                        inputMode="numeric"
                        value={row[field]}
                        disabled={readOnly}
                        onChange={(e) =>
                          setBaleRows((rows) =>
                            rows.map((r) => (r.key === row.key ? { ...r, [field]: e.target.value } : r)),
                          )
                        }
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MoneyField label="Starting balance (USD)" value={openUsd} onChange={setOpenUsd} disabled={readOnly} currency="USD" />
          <MoneyField label="Starting balance (C$)" value={openNio} onChange={setOpenNio} disabled={readOnly} currency="NIO" />
          <MoneyField label="Delivery (USD)" value={deliveryUsd} onChange={setDeliveryUsd} disabled={readOnly} currency="USD" />
          <MoneyField label="Delivery (C$)" value={deliveryNio} onChange={setDeliveryNio} disabled={readOnly} currency="NIO" />
          <MoneyField label="Commercial invoice (USD)" value={invoiceUsd} onChange={setInvoiceUsd} disabled={readOnly} currency="USD" />
          <MoneyField label="Commercial invoice (C$)" value={invoiceNio} onChange={setInvoiceNio} disabled={readOnly} currency="NIO" />
          <MoneyField label="Credit (USD)" value={creditUsd} onChange={setCreditUsd} disabled={readOnly} currency="USD" />
          <MoneyField label="Credit (C$)" value={creditNio} onChange={setCreditNio} disabled={readOnly} currency="NIO" />
        </div>

        <div className="mt-4 rounded-lg border border-ink-200 bg-ink-50 p-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={manualClose}
              disabled={readOnly}
              onChange={(e) => setManualClose(e.target.checked)}
            />
            Enter the closing balance by hand instead of calculating it
          </label>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <span className="label">
                Closing balance (USD{nioPerUsd ? `, C$ converted at ${nioPerUsd}` : ""})
              </span>
              {manualClose ? (
                <input
                  className="input tabular"
                  inputMode="decimal"
                  value={closeUsd}
                  disabled={readOnly}
                  onChange={(e) => { setCloseUsd(e.target.value); setCloseNio("0"); }}
                />
              ) : (
                <p className="tabular rounded-lg border border-dashed border-ink-300 px-3 py-2 text-sm">
                  {computedUsdTotal === null
                    ? "Set this month's exchange rate to see the closing balance"
                    : money(computedUsdTotal, "USD")}
                </p>
              )}
            </div>
          </div>
          <p className="mt-2 text-xs text-ink-500">
            Starting balance + sales − expenses − bank payments − cash received. The exact
            components are configurable in Settings, and the saved sheet shows the calculation
            step by step.
          </p>
        </div>
      </Card>

      <Card title="F · Observations">
        <textarea
          className="input min-h-[90px]"
          value={observations}
          disabled={readOnly}
          onChange={(e) => setObservations(e.target.value)}
          placeholder="Anything unusual about this day…"
        />
      </Card>

      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-ink-200 bg-surface/95 px-4 py-3 backdrop-blur lg:pl-64">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-ink-500">
            <span className="hidden sm:inline">Review &amp; save · </span>
            {transfers.length} {transfers.length === 1 ? "payment" : "payments"} ·{" "}
            {receivedInUsd !== null
              ? `${money(receivedInUsd, "USD")} received`
              : `${money(transferTotals.USD + cashTotals.USD, "USD")} / ${money(
                  transferTotals.NIO + cashTotals.NIO,
                  "NIO",
                )} received`}
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn-secondary btn-sm" onClick={() => router.back()}>
              Cancel
            </button>
            <button type="submit" className="btn-primary btn-sm" disabled={saving || readOnly}>
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              {editing ? "Save changes" : "Create sheet"}
            </button>
          </div>
        </div>
      </div>
    </form>
    </div>
  );
}

function MoneyField({
  label, value, onChange, disabled, currency,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  currency: Currency;
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <div className="relative">
        <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-ink-400">
          {currency === "USD" ? "$" : "C$"}
        </span>
        <input
          className="input tabular pl-8"
          inputMode="decimal"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          placeholder="0.00"
        />
      </div>
    </label>
  );
}

function IntField({
  label, value, onChange, disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <input
        className="input tabular"
        inputMode="numeric"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value.replace(/[^0-9]/g, ""))}
      />
    </label>
  );
}

export function BalanceBreakdown({ balance }: { balance: Record<string, BalanceSide> }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {(["USD", "NIO"] as const).map((currency) => {
        const side = balance[currency];
        if (!side) return null;
        return (
          <div key={currency} className="rounded-lg border border-ink-200 p-3">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-500">
              {currency === "USD" ? "US dollars" : "Cordobas"}
            </p>
            <table className="w-full text-sm">
              <tbody>
                {side.steps.map((step) => (
                  <tr key={step.key}>
                    <td className="py-1 text-ink-600">
                      {step.sign < 0 ? "−" : "+"} {step.label}
                    </td>
                    <td className="tabular py-1 text-right">{money(step.amount, currency)}</td>
                  </tr>
                ))}
                <tr className="border-t border-ink-200">
                  <td className="py-1.5 font-medium">Closing balance</td>
                  <td className="tabular py-1.5 text-right font-semibold">
                    {money(side.entered, currency)}
                  </td>
                </tr>
              </tbody>
            </table>
            {!side.matches && (
              <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800">
                Entered by hand. The formula gives {money(side.computed, currency)} — a difference
                of {money(side.difference, currency)}.
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
