# ContextForge UI Client

React-based admin UI for ContextForge MCP Gateway.

## Tech Stack

- **React 18** with TypeScript
- **Vite** - Build tool and dev server
- **React Router** - Client-side routing
- **React Intl** - Internationalization (i18n)
- **Tailwind CSS** - Utility-first styling
- **shadcn/ui** - Component library

## Getting Started

### Prerequisites

- Node.js 20+ and npm

### Installation

```bash
npm install
```

### Development

```bash
npm run dev
```

Starts the development server at `http://localhost:5173` with hot module replacement.

### Build

```bash
npm run build
```

Builds the production bundle to `dist/`.

### Preview Production Build

```bash
npm run preview
```

## Code Quality

### Linting

ESLint is configured with TypeScript support and Prettier integration.

```bash
# Check for linting errors
npm run lint

# Auto-fix linting errors
npm run lint:fix
```

**Configuration:** [`eslint.config.js`](./eslint.config.js)

### Formatting

Prettier is configured for consistent code formatting.

```bash
# Format all files
npm run format

# Check formatting without changes
npm run format:check
```

**Configuration:** [`.prettierrc`](./.prettierrc)

**Key Settings:**

- Trailing commas: `all` (including function calls)
- Semicolons: `true`
- Single quotes: `false` (use double quotes)
- Print width: `100`

## Testing

### Test Framework

- **Vitest** - Fast unit test runner with jsdom environment
- **React Testing Library** - Component testing utilities
- **MSW (Mock Service Worker)** - API mocking

### Running Tests

```bash
# Run tests in watch mode
npm run test

# Run tests once (CI mode)
npm run test:run

# Run tests with UI
npm run test:ui

# Generate coverage report
npm run test:coverage
```

### Test Structure

```
src/
├── test/
│   ├── setup.ts              # Global test setup (MSW, matchers, mocks)
│   ├── setup.d.ts            # TypeScript declarations for jest-dom
│   ├── test-utils.tsx        # Custom render with providers (I18nProvider)
│   └── mocks/
│       ├── server.ts         # MSW server setup
│       └── handlers.ts       # API request handlers
└── **/*.test.tsx             # Test files (co-located with components)
```

### Writing Tests

Tests use React Testing Library with jest-dom matchers:

```typescript
import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "./test/test-utils";
import { MyComponent } from "./MyComponent";

describe("MyComponent", () => {
  it("renders and handles user interaction", async () => {
    const user = userEvent.setup();
    renderWithProviders(<MyComponent />);

    const button = screen.getByRole("button", { name: /click me/i });
    await user.click(button);

    expect(screen.getByText(/success/i)).toBeInTheDocument();
  });
});
```

**Key Points:**

- Use `renderWithProviders()` instead of `render()` to wrap components with I18nProvider
- Use `userEvent` for simulating user interactions (more realistic than `fireEvent`)
- Use `screen` queries with accessible roles and names
- MSW automatically mocks API requests defined in `src/test/mocks/handlers.ts`

### Mocking API Endpoints

Add handlers to `src/test/mocks/handlers.ts`:

```typescript
import { http, HttpResponse } from "msw";

export const handlers = [
  http.get("/api/users", () => {
    return HttpResponse.json([
      { id: 1, name: "John Doe" },
      { id: 2, name: "Jane Smith" },
    ]);
  }),

  http.post("/api/users", async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json({ id: 3, ...body }, { status: 201 });
  }),
];
```

### TypeScript Configuration

Test-specific TypeScript configuration:

- **[`tsconfig.app.json`](./tsconfig.app.json)** - Includes `vitest/globals` and `@testing-library/jest-dom` types
- **[`src/vitest.d.ts`](./src/vitest.d.ts)** - Global type declarations for test utilities
- **[`vitest.config.ts`](./vitest.config.ts)** - Vitest configuration with jsdom environment

## CI/CD

### GitHub Actions

Tests and linting run automatically on pull requests via [`.github/workflows/client-lint-test.yml`](../.github/workflows/client-lint-test.yml).

**Workflow Steps:**

1. Install dependencies
2. Run Prettier format check
3. Run ESLint
4. Run Vitest tests

**Triggers:**

- Push to `main` or `epic/ui-rewrite` branches
- Pull requests to `main` or `epic/ui-rewrite` branches

## Project Structure

```
client/
├── src/
│   ├── api/              # API client and types
│   ├── auth/             # Authentication context and hooks
│   ├── components/       # Reusable UI components
│   │   ├── layout/       # Layout components (Header, Sidebar, etc.)
│   │   └── ui/           # shadcn/ui components
│   ├── hooks/            # Custom React hooks
│   ├── i18n/             # Internationalization
│   │   └── locales/      # Translation files (en-US, es-ES, pt-BR)
│   ├── pages/            # Page components (Dashboard, Gateways, etc.)
│   ├── router/           # React Router configuration
│   ├── test/             # Test utilities and mocks
│   ├── App.tsx           # Root component
│   └── main.tsx          # Application entry point
├── public/               # Static assets
├── .prettierrc           # Prettier configuration
├── .prettierignore       # Prettier ignore patterns
├── eslint.config.js      # ESLint configuration
├── vitest.config.ts      # Vitest configuration
├── tsconfig.json         # TypeScript base config
├── tsconfig.app.json     # TypeScript app config
├── vite.config.ts        # Vite configuration
└── package.json          # Dependencies and scripts
```

## Available Scripts

| Script                  | Description                      |
| ----------------------- | -------------------------------- |
| `npm run dev`           | Start development server         |
| `npm run build`         | Build for production             |
| `npm run preview`       | Preview production build         |
| `npm run lint`          | Check for linting errors         |
| `npm run lint:fix`      | Auto-fix linting errors          |
| `npm run format`        | Format all files with Prettier   |
| `npm run format:check`  | Check formatting without changes |
| `npm run test`          | Run tests in watch mode          |
| `npm run test:run`      | Run tests once (CI mode)         |
| `npm run test:ui`       | Run tests with UI                |
| `npm run test:coverage` | Generate coverage report         |

## Internationalization (i18n)

The app supports multiple languages via React Intl:

- **English (en-US)** - Default
- **Spanish (es-ES)**
- **Portuguese (pt-BR)**

Translation files are located in `src/i18n/locales/`.

### Adding Translations

1. Add keys to `src/i18n/locales/{locale}/[domain].json`
2. Use in components:

```typescript
import { useIntl } from "react-intl";

function MyComponent() {
  const intl = useIntl();
  return <h1>{intl.formatMessage({ id: "navigation.dashboard" })}</h1>;
}
```

## Troubleshooting

### Tests Failing with "toBeInTheDocument is not a function"

Ensure TypeScript types are properly configured:

- Check `tsconfig.app.json` includes `"types": ["vitest/globals", "@testing-library/jest-dom"]`
- Verify `src/vitest.d.ts` exists with proper type references

### MSW Not Intercepting Requests

- Verify handlers are defined in `src/test/mocks/handlers.ts`
- Check that paths match exactly (e.g., `/auth/login` not `/api/auth/login`)
- Ensure MSW server is started in `src/test/setup.ts`

### window.matchMedia Errors in Tests

The test setup includes a mock for `window.matchMedia` in `src/test/setup.ts`. If you see errors, verify the mock is properly configured.

## Contributing

1. Follow the existing code style (enforced by ESLint and Prettier)
2. Write tests for new features
3. Ensure all tests pass: `npm run test:run`
4. Ensure linting passes: `npm run lint`
5. Ensure formatting is correct: `npm run format:check`
