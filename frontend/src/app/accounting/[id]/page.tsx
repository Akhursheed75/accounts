"use client";

import { Lock, LockOpen, Trash2 } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { PaperSheet } from "@/components/paper-sheet";
import { PageHeader } from "@/components/shell";
import { ErrorNote, Modal, Spinner, StatusBadge, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime, money, shortDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { DailyRecord } from "@/lib/types";

export default function RecordPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { can } = useAuth();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  const { data, error, loading, reload } = useApi(
    () => api.get<DailyRecord>(`/accounting/daily/${params.id}`),
    [params.id],
  );

  async function toggleLock() {
    if (!data) return;
    setBusy(true);
    try {
      await api.post(`/accounting/daily/${data.id}/lock`, undefined, {
        unlock: data.status === "LOCKED",
      });
      toast.push("ok", data.status === "LOCKED" ? "Sheet unlocked." : "Sheet locked.");
      reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not change the lock.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!data) return;
    setBusy(true);
    try {
      await api.del(`/accounting/daily/${data.id}`);
      toast.push("ok", "Sheet archived.");
      router.push("/accounting");
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not archive the sheet.");
    } finally {
      setBusy(false);
      setConfirmDelete(false);
    }
  }

  if (loading && !data) return <Spinner />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  return (
    <>
      <PageHeader
        title={`${data.shop_name ?? "Shop"} — ${shortDate(data.business_date)}`}
        description={`Created ${dateTime(data.created_at)} · last edited ${dateTime(data.updated_at)}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={data.status} dot={false} />
            {data.is_demo && <StatusBadge status="DEMO" dot={false} />}
            {can("accounting.lock") && (
              <button className="btn-secondary btn-sm" onClick={toggleLock} disabled={busy}>
                {data.status === "LOCKED" ? (
                  <>
                    <LockOpen className="h-3.5 w-3.5" /> Unlock
                  </>
                ) : (
                  <>
                    <Lock className="h-3.5 w-3.5" /> Lock
                  </>
                )}
              </button>
            )}
            {can("accounting.delete") && (
              <button className="btn-danger btn-sm" onClick={() => setConfirmDelete(true)}>
                <Trash2 className="h-3.5 w-3.5" /> Archive
              </button>
            )}
          </div>
        }
      />

      <PaperSheet key={data.updated_at} record={data} onSaved={reload} />

      <Modal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Archive this sheet?"
        footer={
          <>
            <button className="btn-secondary btn-sm" onClick={() => setConfirmDelete(false)}>
              Cancel
            </button>
            <button className="btn-danger btn-sm" onClick={remove} disabled={busy}>
              Archive
            </button>
          </>
        }
      >
        <p className="text-sm text-ink-700">
          The sheet stops appearing in reports and dashboards. Nothing is deleted: the record, its
          payments and any reconciliation history stay in the database and in the audit log.
        </p>
        <p className="mt-2 text-sm text-ink-700">
          Sales on this sheet: {money(data.total_sales_usd, "USD")} and{" "}
          {money(data.total_sales_nio, "NIO")}.
        </p>
      </Modal>
    </>
  );
}
