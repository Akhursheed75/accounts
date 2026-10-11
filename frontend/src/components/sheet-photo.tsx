"use client";

/**
 * The photo of the paper sheet, shown beside the form while it is typed in.
 * Choose it, drop it, or paste it with Ctrl+V. It is only a reference: the
 * server deletes it when the sheet is saved.
 */
import { Camera, ImagePlus, Loader2, Maximize2, X, ZoomIn } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { request } from "@/lib/api";
import type { PhotoUpload, SheetPhoto } from "@/lib/types";

export function useSheetPhotos(onError: (err: unknown) => void) {
  const [photos, setPhotos] = useState<SheetPhoto[]>([]);
  const [uploading, setUploading] = useState(false);

  const add = useCallback(
    async (file: File) => {
      setUploading(true);
      try {
        const body = new FormData();
        body.append("file", file);
        const result = await request<PhotoUpload>("/accounting/photos", {
          method: "POST", body, query: { read: false },
        });
        setPhotos((p) => [...p, result.photo]);
      } catch (err) {
        onError(err);
      } finally {
        setUploading(false);
      }
    },
    [onError],
  );

  return { photos, ids: photos.map((p) => p.id), add, uploading, clear: () => setPhotos([]) };
}

export function SheetPhotoDrop({
  hasPhoto, uploading, onFile,
}: {
  hasPhoto: boolean;
  uploading: boolean;
  onFile: (file: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const pick = (files: FileList | null) => {
    const file = files?.[0];
    if (file) onFile(file);
  };

  // Ctrl+V of a screenshot or a WhatsApp image anywhere on the page.
  useEffect(() => {
    function onPaste(event: ClipboardEvent) {
      const item = Array.from(event.clipboardData?.items ?? []).find((i) => i.type.startsWith("image/"));
      const file = item?.getAsFile();
      if (!file || uploading) return;
      event.preventDefault();
      onFile(new File([file], file.name || "pasted-sheet.png", { type: file.type }));
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [onFile, uploading]);

  const chooser = (
    <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" className="hidden"
      onChange={(e) => pick(e.target.files)} />
  );

  if (hasPhoto) {
    return (
      <div className="flex justify-end">
        <button type="button" className="btn-secondary btn-sm" disabled={uploading} onClick={() => input.current?.click()}>
          {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImagePlus className="h-3.5 w-3.5" />}
          Add another photo
        </button>
        {chooser}
      </div>
    );
  }
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files); }}
      className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border-2 border-dashed px-4 py-3 ${
        over ? "border-brand-500 bg-brand-50" : "border-ink-300 bg-surface"}`}
    >
      <p className="flex items-center gap-2 text-sm text-ink-700">
        {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4 text-ink-400" />}
        Photo of the paper sheet: paste it (Ctrl+V), drop it here, or choose it. It stays beside the
        form while you type, and is deleted when you save.
      </p>
      <button type="button" className="btn-secondary btn-sm" disabled={uploading} onClick={() => input.current?.click()}>
        <Camera className="h-3.5 w-3.5" /> Choose photo
      </button>
      {chooser}
    </div>
  );
}

export function SheetPhotoPanel({ photos }: { photos: SheetPhoto[] }) {
  const [index, setIndex] = useState(photos.length - 1);
  const [zoom, setZoom] = useState(false);
  useEffect(() => setIndex(photos.length - 1), [photos.length]);
  const photo = photos[Math.min(Math.max(index, 0), photos.length - 1)];
  if (!photo) return null;
  const src = `/api/v1/accounting/photos/${photo.id}/file`;
  return (
    <aside className="min-w-0">
      <div className="card sticky top-16 overflow-hidden xl:top-4">
        <div className="flex items-center justify-between gap-2 border-b border-ink-200 px-3 py-2">
          <p className="truncate text-sm font-medium">Photo of the sheet</p>
          <button type="button" className="btn-ghost btn-sm" onClick={() => setZoom(true)} aria-label="Enlarge">
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
        </div>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt="Photo of the paper sheet"
          className="max-h-[calc(100vh-8rem)] w-full cursor-zoom-in bg-ink-100 object-contain"
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
      </div>
      {zoom && (
        <div className="fixed inset-0 z-50 overflow-auto bg-ink-950/90 p-4" onClick={() => setZoom(false)}>
          <button type="button" className="fixed right-4 top-4 rounded-full bg-white/90 p-2" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src} alt="Photo of the paper sheet, enlarged" className="mx-auto max-w-none"
            style={{ width: "min(1400px, 160vw)" }} />
          <p className="mt-2 text-center text-xs text-white/70">
            <ZoomIn className="mr-1 inline h-3.5 w-3.5" />Scroll to move around; click to close.
          </p>
        </div>
      )}
    </aside>
  );
}
