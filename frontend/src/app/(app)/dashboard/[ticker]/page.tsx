import { redirect } from "next/navigation";

/**
 * Legacy /dashboard/[ticker] route — kept as a permanent redirect to the new
 * /workspace/[ticker] path so existing bookmarks and external links continue
 * to work.
 */
export default async function DashboardLegacyRedirect({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  redirect(`/workspace/${ticker.toUpperCase()}`);
}
