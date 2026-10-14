// API requests are intercepted by server.mjs before Next's rewrite handler.
// No build-time private hostname or runtime TypeScript loader is needed.
const config = { reactStrictMode: true };
export default config;
