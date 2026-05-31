"use client";

import { Suspense } from "react";

import { CompareView } from "@/components/finsight/compare-view";

export default function ComparePage() {
  return (
    <Suspense fallback={null}>
      <CompareView />
    </Suspense>
  );
}
