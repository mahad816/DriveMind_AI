"use client";

import { useEffect, useRef } from "react";
import { ArrowLeft, ArrowRight, ShieldCheck, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { DriveFileRead } from "@/lib/api/types";
import { fileTypeIcon, fileTypeLabel } from "@/lib/files/utils";
import { preparationEligibility, preparationFrame } from "@/lib/knowledge/single-file-preparation";

type Props = {
  draft: readonly DriveFileRead[];
  inventory: readonly DriveFileRead[] | null;
  disabled: boolean;
  working: boolean;
  error: string | null;
  onPrepare: () => void;
  onBack: () => void;
  onRemove?: (id: string) => void;
};

/** The queue view supplies validation and actions; this component never submits work. */
export function PreparationReview({ draft, inventory, disabled, working, error, onPrepare, onBack, onRemove }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return <section className="files-review" aria-label="Review selection" aria-busy={working}>
    <header className="files-page-header"><div><h1 ref={heading} tabIndex={-1} className="editorial-display">Review selection</h1><p>A final look before adding these documents to your knowledge base.</p></div></header>
    <div className="files-review-panel">
      <div className="files-review-heading"><h2>{draft.length} {draft.length === 1 ? "document" : "documents"} selected</h2><span>From your Google Drive</span></div>
      <p className="files-review-description">DriveMind will read these documents and prepare them for search and questions. Relevant content is processed using the configured AI services. You’ll confirm before each next document starts.</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {!inventory && <p role="status" className="text-sm text-muted-foreground">Checking authorized document details…</p>}
      <ol className="files-review-list" aria-label="Selected documents">
        {draft.map(selected => {
          const file = inventory?.find(row => row.id === selected.id);
          const reason = inventory ? !file || preparationFrame(file) !== preparationFrame(selected) ? "Document metadata changed or is unavailable. Return to Files and select it again." : preparationEligibility(file) : null;
          const Icon = fileTypeIcon(selected.mime_type);
          return <li key={selected.id}>
            <span className="files-type-icon"><Icon aria-hidden="true" className="size-4" /></span>
            <div className="min-w-0 flex-1"><h3>{selected.name}</h3><p>{fileTypeLabel(selected.mime_type)} · {selected.folder_path || "No folder information"}</p>{reason && <p className="text-destructive">Needs attention: {reason}</p>}</div>
            {onRemove && <Button variant="ghost" size="icon-sm" disabled={working} aria-label={`Remove ${selected.name} from selection`} onClick={() => onRemove(selected.id)}><X className="size-3.5" /></Button>}
          </li>;
        })}
      </ol>
      {!draft.length && <p className="text-sm text-muted-foreground">No documents selected. Go back to choose documents.</p>}
      <div className="files-review-actions"><Button variant="ghost" onClick={onBack}><ArrowLeft className="size-3.5" />Back to files</Button><Button disabled={disabled} onClick={onPrepare}>{working ? "Checking preparation…" : "Prepare documents"}<ArrowRight className="size-3.5" /></Button></div>
      <p className="files-review-trust"><ShieldCheck aria-hidden="true" className="size-3.5" />Your original Google Drive documents will not be modified.</p>
    </div>
  </section>;
}
