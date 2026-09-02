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
        description="Upload a statement PDF; the transactions are extracted and matched automatically."
        actions={
          <div className="flex gap-2">
            <button className="btn-secondary btn-sm" onClick={reload}>
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
            {can("statement.upload") && (
              <button className="btn-primary btn-sm" onClick={() => setUploadOpen(true)}>
                <Upload className="h-4 w-4" />
                Upload statement
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
          toast.push("ok", "Uploaded. Processing runs in the background.");
          reload();
        }}
      />
    </>
  );
}

function UploadModal({
  open, banks, onClose, onDone,
}: {
  open: boolean;
  banks: Bank[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [accountId, setAccountId] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const accounts = banks.flatMap((bank) =>
    bank.accounts.map((account) => ({ ...account, bank })),
  );
  const selected = accounts.find((account) => String(account.id) === accountId);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError(new Error("Choose a PDF file."));
      return;
    }
    const body = new FormData();
    body.append("bank_account_id", accountId);
    body.append("file", file);
    if (periodStart) body.append("period_start", periodStart);
    if (periodEnd) body.append("period_end", periodEnd);
    body.append("process_now", "true");

    setBusy(true);
    try {
      await api.post("/statements/upload", body);
      onDone();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Upload a bank statement"
      footer={
        <>
          <button className="btn-secondary btn-sm" onClick={onClose}>Cancel</button>
          <button className="btn-primary btn-sm" form="upload-form" type="submit" disabled={busy}>
            Upload
          </button>
        </>
      }
    >
      <form id="upload-form" onSubmit={submit} className="space-y-3">
        <label className="block">
          <span className="label">Bank account</span>
          <select
            className="input"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            required
          >
            <option value="">Choose the account this statement belongs to…</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.bank.code} — {account.label} ({account.currency_code})
              </option>
            ))}
          </select>
        </label>

        {selected && !selected.bank.parser_available && (
          <p className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
            No statement parser is configured for {selected.bank.name} yet. The file will be stored
            safely, and processing will report what is missing rather than guessing at the layout.
          </p>
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

        <label className="block">
          <span className="label">PDF file</span>
          <input ref={fileRef} type="file" accept="application/pdf,.pdf" className="input" required />
          <span className="mt-1 block text-xs text-ink-500">
            PDF only, up to 25 MB. Uploading the same file twice for one account is refused.
          </span>
        </label>

        <ErrorNote error={error} />
      </form>
    </Modal>
  );
}
