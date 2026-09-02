"use client";

import { Loader2, Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Card, CurrencyTag, ErrorNote, StatusBadge, useToast } from "./ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money, today } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type {
  BalanceSide, BaleType, Bank, Currency, DailyRecord, Shop,
} from "@/lib/types";

interface TransferDraft {
  key: string;
  id?: number;
  bank_id: string;
  bank_account_id: string;
  currency_code: Currency;
  amount: string;
  reference: string;
  note: string;
  match_status?: string;
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
      bank_id: String(t.bank_id),
      bank_account_id: t.bank_account_id ? String(t.bank_account_id) : "",
      currency_code: t.currency_code,
      amount: t.amount,
      reference: t.reference ?? "",
      note: t.note,
      match_status: t.match_status,
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

  const transferTotals = useMemo(() => {
    const totals = { USD: 0, NIO: 0 };
    for (const transfer of transfers) totals[transfer.currency_code] += num(transfer.amount);
    return totals;
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
      USD: num(openUsd) + num(salesUsd) - expenseTotals.USD - transferTotals.USD,
      NIO: num(openNio) + num(salesNio) - expenseTotals.NIO - transferTotals.NIO,
    }),
    [openUsd, openNio, salesUsd, salesNio, expenseTotals, transferTotals],
  );

  // Focus moves to the amount of whichever row was just created, so a second
  // deposit is "Enter, type, Enter" rather than a reach for the mouse.
  const amountInputs = useRef<Record<string, HTMLInputElement | null>>({});
  const [focusRow, setFocusRow] = useState<string | null>(null);

  useEffect(() => {
    if (!focusRow) return;
    amountInputs.current[focusRow]?.focus();
    setFocusRow(null);
  }, [focusRow, transfers]);

  const addTransfer = useCallback(() => {
    const key = newKey();
    setTransfers((rows) => {
      // Most days a shop banks into the same place twice, so a new row starts
      // from the previous one rather than from the top of the list.
      const previous = rows[rows.length - 1];
      return [
        ...rows,
        {
          key,
          bank_id: previous?.bank_id || (bankList[0] ? String(bankList[0].id) : ""),
          bank_account_id: previous?.bank_account_id ?? "",
          currency_code: previous?.currency_code ?? "USD",
          amount: "",
          reference: "",
          note: "",
        },
      ];
    });
    setFocusRow(key);
  }, [bankList]);

  function updateTransfer(key: string, patch: Partial<TransferDraft>) {
    setTransfers((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    const badTransfer = transfers.find((t) => !(num(t.amount) > 0));
    if (badTransfer) {
      setError(new Error("Every bank transfer needs an amount greater than zero."));
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
      transfers: transfers.map((t) => ({
        id: t.id,
        bank_id: Number(t.bank_id),
        bank_account_id: t.bank_account_id ? Number(t.bank_account_id) : null,
        currency_code: t.currency_code,
        amount: cleanAmount(t.amount),
        reference: t.reference || null,
        note: t.note,
      })),
      expenses: expenses.map((e) => ({
        id: e.id,
        category: e.category || "GENERAL",
        description: e.description,
        currency_code: e.currency_code,
        amount: e.amount || "0",
      })),
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
    <form onSubmit={submit} className="space-y-4 pb-24">
      <ErrorNote error={error} />

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
        title="C · Bank transfers"
        description="Add one row per deposit. A bank can appear as many times as needed in a day."
        actions={
          !readOnly && (
            <button type="button" className="btn-secondary btn-sm" onClick={addTransfer}>
              <Plus className="h-3.5 w-3.5" />
              Add transfer
            </button>
          )
        }
      >
        {transfers.length === 0 ? (
          <p className="py-3 text-sm text-ink-500">
            No transfers recorded for this day yet.
          </p>
        ) : (
          <div className="space-y-3">
            {transfers.map((transfer) => {
              const bank = bankList.find((b) => String(b.id) === transfer.bank_id);
              const accounts = (bank?.accounts ?? []).filter(
                (a) => a.currency_code === transfer.currency_code,
              );
              return (
                <div
                  key={transfer.key}
                  className="grid gap-2 rounded-lg border border-ink-200 bg-ink-50/60 p-3 sm:grid-cols-12"
                >
                  <label className="sm:col-span-3">
                    <span className="label">Bank</span>
                    <select
                      className="input"
                      value={transfer.bank_id}
                      disabled={readOnly}
                      onChange={(e) =>
                        updateTransfer(transfer.key, { bank_id: e.target.value, bank_account_id: "" })
                      }
                    >
                      {bankList.map((b) => (
                        <option key={b.id} value={b.id}>
                          {b.code}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="sm:col-span-2">
                    <span className="label">Currency</span>
                    <select
                      className="input"
                      value={transfer.currency_code}
                      disabled={readOnly}
                      onChange={(e) =>
                        updateTransfer(transfer.key, {
                          currency_code: e.target.value as Currency,
                          bank_account_id: "",
                        })
                      }
                    >
                      <option value="USD">USD $</option>
                      <option value="NIO">Cordoba C$</option>
                    </select>
                  </label>
                  <label className="sm:col-span-2">
                    <span className="label">Amount</span>
                    <input
                      ref={(el) => {
                        amountInputs.current[transfer.key] = el;
                      }}
                      className={`input tabular ${
                        invalidAmount(transfer.amount) ? "border-red-500 focus:border-red-500" : ""
                      }`}
                      inputMode="decimal"
                      value={transfer.amount}
                      disabled={readOnly}
                      onChange={(e) => updateTransfer(transfer.key, { amount: e.target.value })}
                      onBlur={(e) =>
                        updateTransfer(transfer.key, { amount: cleanAmount(e.target.value) })
                      }
                      onKeyDown={(e) => {
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
                    {invalidAmount(transfer.amount) && (
                      <span className="mt-1 block text-xs text-red-600">
                        Needs to be more than zero
                      </span>
                    )}
                  </label>
                  <label className="sm:col-span-2">
                    <span className="label">Account</span>
                    <select
                      className="input"
                      value={transfer.bank_account_id}
                      disabled={readOnly || accounts.length === 0}
                      onChange={(e) =>
                        updateTransfer(transfer.key, { bank_account_id: e.target.value })
                      }
                    >
                      <option value="">Any {transfer.currency_code} account</option>
                      {accounts.map((account) => (
                        <option key={account.id} value={account.id}>
                          {account.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="sm:col-span-2">
                    <span className="label">Reference</span>
                    <input
                      className="input"
                      value={transfer.reference}
                      disabled={readOnly}
                      onChange={(e) => updateTransfer(transfer.key, { reference: e.target.value })}
                      placeholder="Deposit slip no."
                    />
                  </label>
                  <div className="flex items-end justify-between gap-2 sm:col-span-1">
                    {transfer.match_status && <StatusBadge status={transfer.match_status} />}
                    {!readOnly && (
                      <button
                        type="button"
                        className="btn-ghost btn-sm text-red-600"
                        onClick={() =>
                          setTransfers((rows) => rows.filter((r) => r.key !== transfer.key))
                        }
                        aria-label="Remove transfer"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {!readOnly && transfers.length > 0 && (
          <p className="mt-2 text-xs text-ink-500">
            Press <kbd className="rounded border border-ink-300 px-1">Enter</kbd> in the amount box
            to start another row. It keeps the same bank and currency.
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-ink-200 pt-3 text-sm">
          <span className="text-ink-500">
            Total transfers
            <span className="ml-1 text-ink-400">
              ({transfers.length} {transfers.length === 1 ? "payment" : "payments"})
            </span>
          </span>
          <span className="tabular font-medium">
            <CurrencyTag code="USD" /> {money(transferTotals.USD, "USD")}
          </span>
          <span className="tabular font-medium">
            <CurrencyTag code="NIO" /> {money(transferTotals.NIO, "NIO")}
          </span>
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
              <span className="label">Closing balance (USD)</span>
              {manualClose ? (
                <input
                  className="input tabular"
                  inputMode="decimal"
                  value={closeUsd}
                  disabled={readOnly}
                  onChange={(e) => setCloseUsd(e.target.value)}
                />
              ) : (
                <p className="tabular rounded-lg border border-dashed border-ink-300 px-3 py-2 text-sm">
                  {money(computed.USD, "USD")}
                </p>
              )}
            </div>
            <div>
              <span className="label">Closing balance (C$)</span>
              {manualClose ? (
                <input
                  className="input tabular"
                  inputMode="decimal"
                  value={closeNio}
                  disabled={readOnly}
                  onChange={(e) => setCloseNio(e.target.value)}
                />
              ) : (
                <p className="tabular rounded-lg border border-dashed border-ink-300 px-3 py-2 text-sm">
                  {money(computed.NIO, "NIO")}
                </p>
              )}
            </div>
          </div>
          <p className="mt-2 text-xs text-ink-500">
            Starting balance + sales − expenses − amounts deposited to banks. The exact
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
            Transfers {money(transferTotals.USD, "USD")} / {money(transferTotals.NIO, "NIO")}
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
