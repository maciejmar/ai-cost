/** Dashboard rozmawia z bramką przez ten sam origin (/api → FastAPI), więc cookie sesji działa bez CORS. */
const GATEWAY = process.env.GATEWAY_INTERNAL_URL || "http://localhost:8090";

const nextConfig = {
  outputFileTracingRoot: import.meta.dirname,
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${GATEWAY}/api/:path*` },
      { source: "/v1/:path*", destination: `${GATEWAY}/v1/:path*` },
    ];
  },
};

export default nextConfig;
