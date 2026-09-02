"use client";

import { PageHeader } from "@/components/shell";
import { RecordForm } from "@/components/record-form";

export default function NewRecordPage() {
  return (
    <>
      <PageHeader
        title="New daily sheet"
        description="Enter the day's figures. Bank transfers are matched automatically once saved."
      />
      <RecordForm />
    </>
  );
}
