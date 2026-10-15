import { redirect } from "next/navigation";
import { DEMO_MODE } from "@/lib/demo";
import { PrepareKnowledgeView } from "@/components/knowledge/prepare-knowledge-view";

export default function IndexPage() {
  if (!DEMO_MODE) redirect("/files");
  return <PrepareKnowledgeView />;
}
