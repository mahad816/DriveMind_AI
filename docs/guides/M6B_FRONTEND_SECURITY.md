# M6B frontend dependency security maintenance

Scope: preserve accepted M6B Docker/lifecycle/proxy behavior and all application
contracts. No Railway access, deployment, provider credentials, indexing
activation, authentication rewrite or conversation/RAG changes.

## Version decisions

- Next.js and eslint-config-next: 15.5.20 → **15.5.27**, latest published stable
  15.5 patch checked against npm metadata and current reviewed advisories.
- React / React DOM: **19.2.7 unchanged**; within Next's declared React 19 peers.
- sharp: 0.34.5 → **0.35.5**. No patched 0.34 release exists. This is supported by
  Next 15.5.27's optional range `^0.34.3 || ^0.35.4` and the image's Node 22 runtime.
  No sharp override is necessary. Actual native inventory: libvips 8.18.7,
  libheif 1.23.5, librsvg 2.63.2. See
  [AVIF advisory](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4),
  [libheif advisory](https://github.com/advisories/GHSA-rgj7-g3m4-5g8c) and
  [librsvg advisory](https://github.com/advisories/GHSA-wq5f-xc86-pv6w).
- PostCSS: targeted **8.5.23** override because Next otherwise pins vulnerable
  8.4.31; keep the same PostCSS major. Updated compatible nanoid/source-map-js
  children. No change to application styles, Tailwind configuration or templates.
- shadcn **4.13.0 unchanged**, moved to devDependencies. It supplies the existing
  `shadcn/tailwind.css` import, so removing it would break builds. No scripts use
  its CLI; compiled CSS stays available after npm prunes development dependencies.
- Named advisory-bearing transitive packages were refreshed with normal npm
  resolution within parent ranges. No `npm audit fix --force`, manual lock editing
  or unrelated direct-library major upgrades. The MCP SDK's compatible minor
  refresh brings its supported newer Hono node-server dependency, build-only.

## Audit inventory (2026-10-14 snapshot)

Counts are npm's affected-package entries, including inherited dependency findings,
not counts of independent exploits. They do not prove reachability or completeness.

| Installation | Before | After |
| --- | --- | --- |
| Production lockfile | 24: 2 critical / 17 high / 5 moderate | **0** |
| All dependencies | 29: 4 critical / 19 high / 6 moderate | **11: 2 critical / 8 high / 1 moderate** |
| Built production installation | M6B reported 24 | **0**, checked after `npm ci` / build / prune |

Former production advisory-bearing package inventory (all lockfile occurrences):

| Package | Before | After | Current classification |
| --- | --- | --- | --- |
| `@hono/node-server` | 1.19.14 | 2.1.5 | build/test only |
| `@modelcontextprotocol/sdk` | 1.29.0 | 1.32.1 | build/test only |
| `@ts-morph/common` | 0.27.0 | 0.27.0 | build/test only |
| `baseline-browser-mapping` | 2.10.42 | 2.11.28 | build/test only |
| `brace-expansion` | 1.1.16, 5.0.7 | 1.1.21, 5.0.12 | build/test only |
| `braces` | 3.0.3 | 3.0.3 | build/test only |
| `browserslist` | 4.28.5 | 4.29.3 | build/test only |
| `fast-glob` | 3.3.1, 3.3.3 | 3.3.1, 3.3.3 | build/test only |
| `fast-uri` | 3.1.3 | 3.1.8 | build/test only |
| `hono` | 4.12.28 | 4.13.13 | build/test only |
| `ip-address` | 10.2.0 | 10.7.4 | build/test only |
| `js-yaml` | 4.3.0 | 4.3.2 | build/test only |
| `micromatch` | 4.0.8 | 4.0.8 | build/test only |
| `nanoid` | 3.3.15 | 3.3.20 | runtime; audit patched |
| `next` | 15.5.20 | 15.5.27 | runtime; audit patched |
| `postcss` | 8.4.31, 8.5.16 | 8.5.23 | runtime; audit patched |
| `postcss-selector-parser` | 7.1.4 | 7.1.6 | build/test only |
| `proxy-addr` | 2.0.7 | 2.0.8 | build/test only |
| `qs` | 6.15.3 | 6.16.0 | build/test only |
| `shadcn` | 4.13.0 | 4.13.0 | build/test only |
| `sharp` | 0.34.5 | 0.35.5 | runtime; audit patched |
| `source-map-js` | 1.2.1 | 1.2.2 | runtime; audit patched |
| `ts-morph` | 26.0.0 | 26.0.0 | build/test only |
| `undici` | 7.28.0 | 7.30.0 | build/test only |

## Remaining development-only findings

All following packages are excluded from the production image. Verified absence
of shadcn, proxy-addr, braces, Vitest and tinypool; production audit also confirms
no other remaining flagged runtime dependency. Build-stage installation still
has these risks and must only process trusted source/configuration in isolated,
low-privilege environments without real account credentials.

| Root issue | Severity and affected package entries | Reachability / smallest follow-up |
| --- | --- | --- |
| [braces stack exhaustion](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) | High: braces, micromatch, fast-glob, @next/eslint-plugin-next, eslint-config-next, @ts-morph/common, ts-morph, shadcn | Untrusted deeply nested glob patterns can terminate build/lint/CLI tooling. No published braces patch exists (latest 3.0.3). Current patterns are trusted repository/build input; ordinary users cannot supply them. Do not expose shadcn MCP/CLI services. Follow upstream patch or separately assess bounded glob replacement; do not fabricate a safe override. |
| [tinypool worker option pollution](https://github.com/advisories/GHSA-5gmw-xhrv-c9v3), [run option pollution](https://github.com/advisories/GHSA-85c8-ppgw-ccpr) | Critical: tinypool 1.1.1 and inherited Vitest entry | Requires attacker-controlled/polluted worker options in the test runner. Not a runtime dependency or application HTTP path. Fixed tinypool is 2.1.2, outside Vitest 3's range. Smallest supported removal is a separately tested Vitest 4.1.11+ migration; do not force a pool major beneath Vitest 3. |
| [Vitest mock redirect disclosure](https://github.com/advisories/GHSA-82fw-gwwq-j7x9) | Moderate: @vitest/mocker 3.2.7; Vitest also inherits this issue | Exposed standalone mocker/Vite WebSocket can read files. This project uses synthetic Node/jsdom `vitest run`, no public mocker/browser/API service. Never expose a watch/UI/mock server. No 3.x backport is planned; migrate to Vitest 4.1.11+ with accepted config/runner regressions separately. |

Vitest's unchanged environmentMatchGlobs configuration is deprecated; upgrading
its major would require converting the environment/project configuration and
reviewing mocks and worker behavior. That migration is deliberately not hidden
inside this production security patch.

## Verification and security controls

- Reproducible `npm ci` from the refreshed lock; full production build, lint/type
  checks and both Docker builds. Native execution on ARM64; AMD64 base manifests
  remain supported but deployed architecture execution is a live gate.
- **162 selected frontend tests passed**, covering session, account-switch, API
  adapter, mounted normal conversation,
  source panel/viewer and demo/file preview regressions. No backend indexing/RAG
  suite repeated; no real Google/OpenAI/Qdrant requests or personal data.
- Accepted 11 proxy tests retain cookie/CSRF/Origin forwarding, host-only OAuth
  cookie/redirect headers, no-store errors, >120-second response tolerance,
  absolute 180-second budget and client-disconnect cleanup. Proxy/server/runtime
  config code unchanged; private backend origin remains runtime-only.
- Actual custom server renders pages and answers process health; a synthetic
  loopback backend confirms real-server callback multi-cookie forwarding, CSRF/
  Origin rejection and truthful 202/no-store routing. Production
  optimizer successfully resizes synthetic PNG and AVIF using patched sharp.
  **AVIF need not return 400:** patched Next checks native libheif safety and can
  optimize with 1.23.5. Unsafe/unknown versions fail its decoder predicate; when
  unsafe it may return unoptimized bytes, not necessarily an HTTP error.
- SVG, malformed image bytes, invalid sizes and unapproved private-target image
  URLs are rejected. A sentinel private HTTP server receives zero requests.
- Image fixtures must be installed BEFORE Next starts (it inventories public
  assets). Use only a disposable local image, never a deployed beta:

  ```sh
  # Mount frontend/deploy read-only at /tests in a fresh local image container.
  node /tests/image-smoke.test.mjs --fixtures
  # In that container, start the server with BACKEND_URL=http://127.0.0.1:9000.
  # The test owns a synthetic backend on port 9000; use no real backend.
  DEPLOYMENT_TEST_URL=http://127.0.0.1:3000 node --test /tests/image-smoke.test.mjs
  ```

- External sensitivity controls: bypassing Next's safe-decoder predicate fails
  the unsafe-version assertion; making proxy responses public fails the private
  cache assertion. Neither mutation changes tracked code or the built image.

The deployed-image smoke suite has eight passing assertions/subtests, including
the real-server API/callback check. The source-viewer tests add three focused
cases to the 159 selected existing frontend cases (162 total).

## Deployment gate

The production dependency hold can reasonably be lifted **only after independent
acceptance of this commit**, including the documented development-only exceptions.
This is not deployment/indexing authorization and not proof against unknown
framework, native-code or application vulnerabilities. Re-audit at release time.

Railway Config-as-Code is deprecated and does not configure a newly created
project. Use the exact dashboard settings in
[the updated beta runbook](RAILWAY_PRIVATE_BETA.md); TOML files are reference only.
Verify effective source root, Dockerfile/context, start command, healthchecks,
private DNS/port, one replica, no-sleep and termination grace on an authorized
live deployment. Google callbacks/cookies, edge logs, backup/restore and actual
billing safeguards remain operational acceptance gates. No new IaC framework.
