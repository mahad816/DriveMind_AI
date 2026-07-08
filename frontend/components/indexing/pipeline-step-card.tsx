"use client";

import { Loader2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export type PipelineStepResultRow = {
  label: string;
  value: string | number;
};

type PipelineStepCardProps = {
  stepNumber: number;
  title: string;
  description: string;

  actionLabel: string;
  isConnected: boolean;
  isBusy: boolean;
  isLoading: boolean;
  disabledReason?: string | null;

  onRun: () => Promise<void>;

  lastMessage?: string | null;
  resultRows?: PipelineStepResultRow[] | null;
  error?: string | null;
};

export function PipelineStepCard({
  stepNumber,
  title,
  description,
  actionLabel,
  isConnected,
  isBusy,
  isLoading,
  disabledReason,
  onRun,
  lastMessage,
  resultRows,
  error,
}: PipelineStepCardProps) {
  const disabled = !isConnected || isBusy || isLoading;

  return (
    <Card className="overflow-visible">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <CardTitle className="text-base">
              <span className="mr-2 text-muted-foreground">#{stepNumber}</span>
              {title}
            </CardTitle>
            <CardDescription>{description}</CardDescription>
          </div>

          <Badge variant="outline" className="text-xs font-normal">
            {isConnected ? "Ready" : "Locked"}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {error ? (
          <Alert variant="destructive">
            <AlertTitle>Step failed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-col items-stretch gap-2">
          <Button
            type="button"
            onClick={() => void onRun()}
            disabled={disabled}
            aria-disabled={disabled}
            className="w-full"
          >
            {isLoading ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
            {actionLabel}
          </Button>

          {disabledReason ? (
            <span className="text-xs text-muted-foreground">{disabledReason}</span>
          ) : null}
        </div>

        {lastMessage ? (
          <div className="space-y-2">
            <p className="text-sm font-medium">{lastMessage}</p>

            {resultRows && resultRows.length > 0 ? (
              <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                {resultRows.map((row) => (
                  <div key={row.label} className="flex items-center justify-between gap-3">
                    <span>{row.label}</span>
                    <span className="font-medium text-foreground">{row.value}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

