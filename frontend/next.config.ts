import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output so the Docker runtime image can stay tiny.
  output: "standalone",
  devIndicators: false,
};

export default nextConfig;
