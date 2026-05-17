"use client";

import { useSearchParams } from "next/navigation";
import { ChatView } from "@/components/finsight/chat-view";

interface Props {
  ticker: string;
}

/**
 * Workspace Chat tab — wraps the existing ChatView, scoped to the current
 * ticker. Reads `?q=` from the URL so the Overview tab can pre-fill a
 * question chip into the chat input.
 */
export function WorkspaceChat({ ticker }: Props) {
  const params = useSearchParams();
  const initialQuestion = params.get("q") ?? undefined;
  return <ChatView initialTicker={ticker} initialQuestion={initialQuestion} />;
}
