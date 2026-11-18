import type { NextConfig } from "next";

// `npm run build` writes a static site to ./out, which the Python server (server.py) serves.
// `npm run dev` runs on :3000 and talks to the Python API on :8765 (see .env.development).
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  reactStrictMode: true,
};

export default nextConfig;
