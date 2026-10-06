"use client";

import { AlertTriangle, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { PageHeader } from "@/components/shell";
import {
  Card, EmptyState, ErrorNote, Modal, Pagination, Spinner, StatusBadge, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { bytes, dateTime, shortDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Bank, Page as ApiPage, Statement } from "@/lib/types";

export default function StatementsPage() {
  const { can } = useAuth();
  const toast = useToast();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [bankId, setBankId] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);

  const banks = useApi(() => api.get<Bank[]>("/banks"), []);
  const { data, error, loading, reload } = useApi(
    () =>
      api.get<ApiPage<Statement>>("/statements", {
        bank_id: bankId || undefined,
        status: status || undefined,
        page,
        page_size: 25,
      }),
    [bankId, status, page],
  );

  // Anything still processing settles within seconds; poll only while it does.
  const pending = (data?.items ?? []).some((s) =>
    ["UPLOADED", "PROCESSING"].includes(s.status),
  );
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(reload, 3000);
    return () => clearInterval(timer);
  }, [pending, reload]);

  return (
    <>
      <PageHeader
        title="Bank statements"
        description="Upload the day's statement PDFs (all six at once); transactions are extracted and matched to the daily sheets automatically."
        actions={
          <div className="flex gap-2">
            <button className="btn-secondary btn-sm" onClick={reload}>
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
            {can("statement.upload") && (
              <button className="btn-primary btn-sm" onClick={() => setUploadOpen(true)}>
                <Upload className="h-4 w-4" />
                Upload statements
              </button>
            )}
          </div>
        }
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="label">Bank</span>
            <select className="input" value={bankId} onChange={(e) => { setBankId(e.target.value); setPage(1); }}>
              <option value="">All banks</option>
              {(banks.data ?? []).map((bank) => (
                <option key={bank.id} value={bank.id}>{bank.name}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Processing status</span>
            <select className="input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
              <option value="">Any status</option>
              <option value="UPLOADED">Uploaded</option>
              <option value="PROCESSING">Processing</option>
              <option value="PROCESSED">Processed</option>
              <option value="PARTIALLY_PROCESSED">Partially processed</option>
              <option value="FAILED">Failed</option>
            </select>
          </label>
        </div>
      </Card>

      <ErrorNote error={error} />

      <Card padded={false}>
        {loading && !data && <div className="p-5"><Spinner /></div>}
        {data && data.items.length === 0 && (
          <EmptyState
            title="No statements uploaded"
            description="Upload a PDF exported from online banking to get started."
          />
        )}
        {data && data.items.length > 0 && (
          <>
            <ul className="divide-y divide-ink-100">
              {data.items.map((statement) => (
                <li key={statement.id} className="px-4 py-3 hover:bg-ink-50">
                  <Link href={`/statements/${statement.id}`} className="block">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{statement.original_filename}</p>
                        <p className="mt-0.5 text-xs text-ink-500">
                          {statement.bank_code} · {statement.account_label} ·{" "}
                          {statement.currency_code} · {bytes(statement.file_size)} ·{" "}
                          {dateTime(statement.created_at)}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {statement.extraction_method !== "UNKNOWN" && (
                          <span className="rounded bg-ink-100 px-1.5 py-0.5 text-[11px] font-medium text-ink-600">
                            {statement.extraction_method}
                          </span>
                        )}
                        <span className="tabular text-xs text-ink-600">
                          {statement.transaction_count} txn
                          {statement.duplicate_count > 0 && ` · ${statement.duplicate_count} dup`}
                        </span>
                        <StatusBadge status={statement.status} dot={false} />
                      </div>
                    </div>
                    {statement.error_message && (
                      <p className="mt-2 flex items-start gap-1.5 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-800">
                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                        {statement.error_message}
                      </p>
                    )}
                    {statement.warnings && statement.warnings.length > 0 && (
                      <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
                        {statement.warnings[0]}
                        {statement.warnings.length > 1 && ` (+${statement.warnings.length - 1} more)`}
                      </p>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </>
        )}
      </Card>

      <UploadModal
        open={uploadOpen}
        banks={banks.data ?? []}
        onClose={() => setUploadOpen(false)}
        onDone={() => {
          setUploadOpen(false);
          toast.push("ok", "Uploaded. Processing runs in the background; daily sheets re-check themselves.");
          reload();
        }}
      />
    </>
  );
}

type Account = Bank["accounts"][number] & { bank: Bank };

/** Guess the account from a file name such as "bac_usd.pdf" or "BANPRO cordobas.pdf". */
function guessAccount(name: string, accounts: Account[]): string {
  const n = name.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace("ficohsa", "fichosa");
  const usd = /(usd|dolar|dollar|\$)/.test(n);
  const nio = /(nio|cordoba|c\$|cs)/.test(n);
  const byBank = accounts.filter((a) => n.includes(a.bank.code.toLowerCase()));
  if (byBank.length === 0) return "";
  const currency = usd && !nio ? "USD" : nio && !usd ? "NIO" : null;
  const pick = currency ? byBank.filter((a) => a.currency_code === currency) : byBank;
  return pick.length === 1 ? String(pick[0].id) : "";
}

interface Row { file: File; accountId: string; state: "ready" | "sending" | "done" | "failed"; error?: string }

function UploadModal({
  open, banks, onClose, onDone,
}: {
  open: boolean;
  banks: Bank[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const accounts: Account[] = banks.flatMap((bank) =>
    bank.accounts.map((account) => ({ ...account, bank })),
  );

  function choose(files: FileList | null) {
    setError(null);
    setRows(Array.from(files ?? []).map((file) => ({
      file, accountId: guessAccount(file.name, accounts), state: "ready",
    })));
  }

  function setRow(index: number, patch: Partial<Row>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function close() {
    setRows([]);
    setError(null);
    if (fileRef.current) fileRef.current.value = "";
    onClose();
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (rows.length === 0) {
      setError(new Error("Choose the PDF files."));
      return;
    }
    if (rows.some((row) => !row.accountId)) {
      setError(new Error("Pick the bank account for every file."));
      return;
    }
    const used = rows.map((row) => row.accountId);
    if (new Set(used).size !== used.length) {
      setError(new Error("Two files are set to the same account — check the account column."));
      return;
    }
    setBusy(true);
    let failed = 0;
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].state === "done") continue;
      setRow(i, { state: "sending", error: undefined });
      const body = new FormData();
      body.append("bank_account_id", rows[i].accountId);
      body.append("file", rows[i].file);
      if (periodStart) body.append("period_start", periodStart);
      if (periodEnd) body.append("period_end", periodEnd);
      body.append("process_now", "true");
      try {
        await api.post("/statements/upload", body);
        setRow(i, { state: "done" });
      } catch (err) {
        failed += 1;
        setRow(i, { state: "failed", error: err instanceof Error ? err.message : "Upload failed" });
      }
    }
    setBusy(false);
    if (failed === 0) {
      setRows([]);
      if (fileRef.current) fileRef.current.value = "";
      onDone();
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Upload the day's bank statements"
      footer={
        <>
          <button className="btn-secondary btn-sm" onClick={close}>Close</button>
          <button className="btn-primary btn-sm" form="upload-form" type="submit" disabled={busy}>
            {busy ? "Uploading…" : rows.length > 1 ? `Upload ${rows.length} files` : "Upload"}
          </button>
        </>
      }
    >
      <form id="upload-form" onSubmit={submit} className="space-y-3">
        <label className="block">
          <span className="label">PDF files — choose all of them at once</span>
          <input
            ref={fileRef} type="file" accept="application/pdf,.pdf" className="input" multiple
            onChange={(e) => choose(e.target.files)}
          />
          <span className="mt-1 block text-xs text-ink-500">
            Up to 25 MB each. The account is guessed from the file name (e.g. bac_usd.pdf,
            banpro_nio.pdf) — check it before uploading. The same file twice for one account is refused.
          </span>
        </label>

        {rows.length > 0 && (
          <ul className="divide-y divide-ink-100 rounded border border-ink-200">
            {rows.map((row, index) => {
              const account = accounts.find((a) => String(a.id) === row.accountId);
              return (
                <li key={`${row.file.name}-${index}`} className="space-y-1.5 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{row.file.name}</span>
                    <span className={`shrink-0 text-xs font-medium ${
                      row.state === "done" ? "text-emerald-700"
                        : row.state === "failed" ? "text-red-700"
                          : row.state === "sending" ? "text-ink-500" : "text-ink-400"}`}>
                      {row.state === "done" ? "Uploaded" : row.state === "failed" ? "Failed"
                        : row.state === "sending" ? "Sending…" : bytes(row.file.size)}
                    </span>
                  </div>
                  <select
                    className={`input ${row.accountId ? "" : "border-amber-400"}`}
                    value={row.accountId}
                    disabled={row.state === "done" || busy}
                    onChange={(e) => setRow(index, { accountId: e.target.value })}
                  >
                    <option value="">Which account is this?</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.bank.code} — {a.label} ({a.currency_code})
                      </option>
                    ))}
                  </select>
                  {account && !account.bank.parser_available && (
                    <p className="text-xs text-amber-800">
                      No parser for {account.bank.name} yet — the file is kept, nothing is guessed.
                    </p>
                  )}
                  {row.error && <p className="text-xs text-red-700">{row.error}</p>}
                </li>
              );
            })}
          </ul>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="label">Period start (optional)</span>
            <input type="date" className="input" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">Period end (optional)</span>
            <input type="date" className="input" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
          </label>
        </div>

        <ErrorNote error={error} />
      </form>
    </Modal>
  );
}
