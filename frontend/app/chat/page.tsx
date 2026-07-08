import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function ChatPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-6 md:p-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Chat</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Answers from your indexed Drive files with citations.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Coming in Milestone 7</CardTitle>
          <CardDescription>
            The chat composer, grounded answers, and citation cards will be wired to{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">POST /api/v1/chat</code> in
            the next milestones.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          API traffic is proxied through{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">/api/v1</code> to the FastAPI
          backend. Typed client wiring arrives in Milestone 2.
        </CardContent>
      </Card>
    </div>
  );
}
