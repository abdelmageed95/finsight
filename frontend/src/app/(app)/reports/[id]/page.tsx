"use client";

import { use, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Legacy /reports/[id] route — looks up the report's ticker, then redirects
 * to /workspace/[ticker]?tab=research&job=[id]. Falls back to /home if the
 * report can't be found.
 */
export default function ReportLegacyRedirect({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();

  const { data, error, isLoading } = useQuery({
    queryKey: ["report", id],
    queryFn: () => api.report(id),
    retry: false,
  });

  useEffect(() => {
    if (data?.ticker) {
      router.replace(`/workspace/${data.ticker}?tab=research&job=${id}`);
    } else if (error) {
      router.replace("/home");
    }
  }, [data, error, id, router]);

  return (
    <div className="flex flex-1 items-center justify-center p-10">
      <div className="flex items-center gap-2 text-sm text-[var(--color-muted)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        {isLoading ? "Loading report…" : "Redirecting…"}
      </div>
    </div>
  );
}
