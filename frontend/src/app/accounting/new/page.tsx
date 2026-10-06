"use client";

import { PageHeader } from "@/components/shell";
import { PaperSheet } from "@/components/paper-sheet";

export default function NewRecordPage() {
  return (
    <>
      <PageHeader
        title="New daily sheet"
        description="Add the photo of the paper sheet, check the amounts it read, and save. Deposits turn green when the bank statement shows them."
      />
      <PaperSheet />
    </>
  );
}
