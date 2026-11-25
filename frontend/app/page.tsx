"use client";
import { useSetupDestination } from "@/components/setup/use-setup";
import { StartupSkeleton } from "@/components/setup/startup-skeleton";

/** Resolver only: goes to setup or to a new chat based on real state. */
export default function Home() {
  useSetupDestination(true);
  return <StartupSkeleton />;
}
