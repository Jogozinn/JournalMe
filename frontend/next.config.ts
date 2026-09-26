import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  distDir:
    process.env.NEXT_DIST_DIR ??
    (process.env.NODE_ENV === "development" ? ".next-dev" : ".next"),
  output: "standalone",
  outputFileTracingRoot: process.cwd(),
  reactStrictMode: true,
};

export default nextConfig;
