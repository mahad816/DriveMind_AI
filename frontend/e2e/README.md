# Browser journeys (synthetic data only)

These scripts drive headless Chromium (Playwright, a fresh isolated profile per journey) against the synthetic backend in `stub/`. All data is fictional; nothing reaches Google, OpenAI, Railway or a real database. Ports 3000 and 8000 are never used.

Run each in its own terminal, from `frontend/`:

1. `npm run e2e:stub` starts the synthetic backend on 127.0.0.1:8100.
2. `npm run e2e:app` starts the app on 127.0.0.1:3100, proxying to the stub. For streaming mode, prefix `NEXT_PUBLIC_CHAT_STREAMING_ENABLED=true`.
3. `npm run e2e:journeys` runs the journeys and axe checks (exit code 1 if any check fails). `ONLY=prepare,tab-switch` runs a subset.
4. `npm run e2e:responsive` captures 1100, 820, 390 and 320 px in both themes and fails on horizontal overflow.

Screenshots go to `$SHOTS`, or a `drivemind-e2e-shots` folder in the system temp directory. Do not point it inside the repository.
`node e2e/contrast.mjs` checks the colour tokens in `app/globals.css` against WCAG contrast targets.

Public demo: stop the app, start `npm run e2e:app:demo` instead (`NEXT_PUBLIC_DEMO_MODE=true`), then run `npm run e2e:demo`. The stub's `demo` scenario mirrors the backend demo runtime (anonymous status with sample questions, `POST /chat`, files, file text and passages; everything else refused).

All journeys wait on page state (elements, URLs, responses, focus), never on fixed delays.

