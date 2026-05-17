import { Suspense } from "react";
import { WorkspaceView } from "@/components/finsight/workspace-view";

export default async function WorkspacePage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  return (
    <Suspense fallback={null}>
      <WorkspaceView ticker={ticker.toUpperCase()} />
    </Suspense>
  );
}
