"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

/**
 * Legacy /chat?ticker=X route — redirects to /workspace/X?tab=chat. If no
 * ticker query param is present we send users to /home so they can pick one.
 */
function ChatRedirectInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const ticker = searchParams.get("ticker");
    if (ticker) {
      const params = new URLSearchParams();
      params.set("tab", "chat");
      const q = searchParams.get("q");
      if (q) params.set("q", q);
      router.replace(`/workspace/${ticker.toUpperCase()}?${params.toString()}`);
    } else {
      router.replace("/home");
    }
  }, [router, searchParams]);

  return null;
}

export default function ChatRedirectPage() {
  return (
    <Suspense fallback={null}>
      <ChatRedirectInner />
    </Suspense>
  );
}
