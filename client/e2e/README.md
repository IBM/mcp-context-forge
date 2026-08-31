# E2E Tests (Playwright + TypeScript)

End-to-end tests for the ContextForge React admin UI, written in TypeScript with
[Playwright](https://playwright.dev/). They share types and conventions with the
client code under `src/` and run without requiring the Python gateway backend:
API responses are stubbed per-test with `page.route()`.

## Layout

```
e2e/
├── fixtures/
│   ├── api-mock.ts         # `test` with `apiMock` helper (page.route wrappers)
│   └── auth.ts             # `test` with a pre-authenticated page (session token)
├── smoke/                  # Fast checks on every PR — no backend, no auth
│   ├── app-loads.spec.ts
│   ├── auth-redirect.spec.ts
│   └── static-assets.spec.ts
├── auth/                   # Authentication & session flows
│   ├── login-flow.spec.ts
│   ├── forgot-password.spec.ts
│   └── session.spec.ts
├── utils/
│   └── paths.ts            # Route + API path constants (mirror src/router)
└── README.md
```

## Running

Install the Playwright browsers once per machine:

```bash
npm run e2e:install
```

Then, from `client/`:

```bash
npm run e2e             # Headless run against the Vite dev server
npm run e2e:ui          # Interactive UI mode (great for authoring)
npm run e2e:debug       # Step through with the Playwright Inspector
npm run e2e:report      # Open the last HTML report
```

The config spawns `npm run dev:e2e` (Vite with `--base=/`) on port `5173` and
tears it down after the run. Set `PLAYWRIGHT_BASE_URL` to point tests at an
existing server instead:

```bash
PLAYWRIGHT_BASE_URL=http://localhost:4444 PLAYWRIGHT_SKIP_WEBSERVER=1 npm run e2e
```

## Writing a new test

Import the `test` and `expect` helpers from the fixture that matches your needs:

```ts
// Unauthenticated / public flows
import { test, expect } from "../fixtures/api-mock";

// Authenticated flows (/app/auth/me mocked as a valid cookie session)
import { test, expect } from "../fixtures/auth";
```

Mock API endpoints through the `apiMock` fixture rather than calling
`page.route()` directly, so payload shapes stay in sync with `AuthContext`:

```ts
test("rejects wrong password", async ({ page, apiMock }) => {
  await apiMock.mockLogin({ status: 401 });
  await page.goto("/app/login");
  // ...
});
```

Prefer role- and label-based locators (`getByRole`, `getByLabel`) over CSS
selectors — they survive refactors and double as accessibility checks.

Keep smoke tests:

- Deterministic (no reliance on real network / time)
- Under a second per test on a warm dev server
- Tied to user-visible behaviour, not implementation details

## CI

Runs in
[`.github/workflows/client-e2e.yml`](../../.github/workflows/client-e2e.yml) on
PRs and pushes to `main` / `epic/ui-rewrite` that touch `client/**`.

## Troubleshooting

- **`Error: Timed out waiting for ... to be visible`** — check the locator in UI
  mode (`npm run e2e:ui`) and confirm the mock returns what the UI expects.
- **Tests that pass locally but flake in CI** — add a `page.waitForLoadState`,
  tighten the mock's payload, or widen the retry count in the config for the
  specific test. Do not add arbitrary `waitForTimeout` calls.
- **Mock not firing** — `page.route()` patterns use glob syntax. `"**/app/auth/me"`
  is the supported form; a leading `/` anchors to the origin only.
