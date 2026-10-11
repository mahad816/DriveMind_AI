"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export function DemoHomeRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace(`/chat${window.location.search}`);
  }, [router]);

  return <p className="p-6 text-sm text-muted-foreground" role="status">Opening the public demo…</p>;
}
