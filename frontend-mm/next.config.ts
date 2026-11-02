import type { NextConfig } from 'next';

/**
 * A static export: `npm run build` writes ./out, which S3 + CloudFront serve at its CloudFront address. Every agent is a native module of this app
 * (src/features/<id>/, its own lazy chunk); its API calls go to /agents/<id>/api/..., which CloudFront proxies to the agent's live API.
 */
const config: NextConfig = { reactStrictMode: true, output: 'export', images: { unoptimized: true } };

export default config;
