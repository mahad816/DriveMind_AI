"use client";

import { DEMO_MODE } from "@/lib/demo";

import { Popover } from "@base-ui/react/popover";

import type { CitationItem } from "@/lib/api/types";
import { driveFileUrl } from "@/lib/files/utils";

type CitationPreviewProps = {
  citation: CitationItem;
  number: number;
  onOpenEvidence?: (citation: CitationItem) => void;
};

export function CitationPreview({ citation, number, onOpenEvidence }: CitationPreviewProps) {
  return (
    <Popover.Root>
      <Popover.Trigger
        type="button"
        aria-label={`View citation ${number}`}
        className="mx-0.5 inline-flex align-baseline text-xs font-semibold text-primary underline underline-offset-2 focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        [{number}]
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner sideOffset={8}>
          <Popover.Popup className="z-50 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-popover p-3 text-sm text-popover-foreground shadow-sm outline-none">
            <Popover.Title className="sr-only">Citation {number}</Popover.Title>
            <p className="font-medium break-words">{citation.filename}</p>
            <p className="mt-2 max-h-36 overflow-y-auto text-muted-foreground break-words">
              {citation.snippet}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
              {!DEMO_MODE && citation.drive_file_id ? (
                <a
                  href={driveFileUrl(citation.drive_file_id)}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-primary underline underline-offset-2"
                >
                  Open in Google Drive
                </a>
              ) : null}
              {onOpenEvidence ? (
                <button
                  type="button"
                  className="font-medium text-primary underline underline-offset-2"
                  onClick={() => onOpenEvidence(citation)}
                >
                  View full evidence
                </button>
              ) : null}
            </div>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}
