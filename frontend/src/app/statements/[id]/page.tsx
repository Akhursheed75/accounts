"use client";

import { AlertTriangle, Download, Play } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/shell";
import { TransactionTable } from "@/components/transaction-table";
import { Card, EmptyState, ErrorNote, Spinner, StatusBadge, useToast } from "@/components/ui";
import { api, downloadUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { bytes, dateTime, money, shortDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Page as ApiPage, Statement, Transaction } from "@/lib/types";

export default function StatementDetailPage() {
  const params = useParams<{ id: string }>();
  const toast = useToast();
  const { can } = useAuth();
  const [busy, setBusy] = useState(false);

  const statement = useApi(() => api.get<Statement>(`/statements/${params.id}`), [params.id]);
  const transactions = useApi(
    () =>
      api.get<ApiPage<Transaction>>("/bank-transactions", {
        statement_id: params.id,
        page_size: 500,
      }),
    [params.id, statement.data?.status],
  );

  async function reprocess() {
    setBusy(true);
    try {
      await api.post(`/statements/${params.id}/process`, undefined, { background: false });
      toast.push("ok", "Reprocessed.");
      statement.reload();
      transactions.reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Processing failed.");
    } finally {
      setBusy(false);
    }
  }

  if (statement.loading && !statement.data) return <Spinner />;
  if (statement.error) return <ErrorNote error={statement.error} />;
  const data = statement.data;
  if (!data) return null;

  return (
    <>
      <PageHeader
        title={data.original_filename}
        description={`${data.bank_name} · ${data.account_label} · ${data.currency_code}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <a className="btn-secondary btn-sm" href={downloadUrl(`/statements/${data.id}/file`)} target="_blank" rel="noreferrer">
              <Download className="h-3.5 w-3.5" />
              Original PDF
            </a>
            {can("statement.upload") && (
              <button className="btn-secondary btn-sm" onClick={reprocess} disabled={busy}>
                <Play className="h-3.5 w-3.5" />
                Reprocess
              </button>
            )}
          </div>
        }
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Fact label="Status"><StatusBadge status={data.status} dot={false} /></Fact>
        <Fact label="Parser">
          {data.parser_key ?? "not detected"}
          {data.extraction_method !== "UNKNOWN" && ` · ${data.extraction_method}`}
        </Fact>
        <Fact label="Transactions">
          <span className="tabular">
            {data.transaction_count} extracted
            {data.duplicate_count > 0 && ` · ${data.duplicate_count} already known`}
          </span>
        </Fact>
        <Fact label="Period">
          {data.period_start ? `${shortDate(data.period_start)} → ${shortDate(data.period_end)}` : "—"}
        </Fact>
      </div>

      {data.error_message && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">Processing did not complete</p>
            <p className="mt-0.5">{data.error_message}</p>
          </div>
        </div>
      )}

      {data.warnings && data.warnings.length > 0 && (
        <Card className="mb-4" title="Notes from the parser">
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-700">
            {data.warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </Card>
      )}

      <Card
        title="Extracted transactions"
        description={
          data.statement_closing_balance
            ? `Statement closing balance ${money(data.statement_closing_balance, data.currency_code ?? undefined)}`
            : undefined
        }
        padded={false}
      >
        {transactions.loading && !transactions.data && <div className="p-5"><Spinner /></div>}
        {transactions.data && transactions.data.items.length === 0 && (
          <EmptyState
            title="No transactions from this file"
            description="Either the statement had no movements, or processing has not finished."
          />
        )}
        {transactions.data && transactions.data.items.length > 0 && (
          <TransactionTable rows={transactions.data.items} />
        )}
      </Card>

      <p className="mt-3 text-xs text-ink-500">
        Uploaded {dateTime(data.created_at)} · {bytes(data.file_size)}
        {data.page_count ? ` · ${data.page_count} page(s)` : ""}
      </p>
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="card card-pad">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</p>
      <div className="mt-1.5 text-sm text-ink-900">{children}</div>
    </div>
  );
}
