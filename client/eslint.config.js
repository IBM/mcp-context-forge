import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import tseslint from "typescript-eslint";
import reactPlugin from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import prettierPlugin from "eslint-plugin-prettier";
import prettierConfig from "eslint-config-prettier";
import globals from "globals";

// Load .prettierrc explicitly instead of letting eslint-plugin-prettier
// resolve it on its own — this repo has a second, differently-configured
// prettier.config.js one directory up (repo root), and relying on the
// plugin's own cosmiconfig search risks it picking that one up instead,
// producing formatting eslint --fix disagrees with the prettier CLI on.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const prettierOptions = JSON.parse(fs.readFileSync(path.join(__dirname, ".prettierrc"), "utf8"));

export default tseslint.config(
  {
    ignores: [
      "../mcpgateway/static/app",
      "src/generated",
      "dist",
      "build",
      "playwright-report",
      "test-results",
    ],
  },
  {
    extends: [...tseslint.configs.recommended],
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      globals: globals.browser,
    },
    plugins: {
      react: reactPlugin,
      "react-hooks": reactHooks,
      prettier: prettierPlugin,
    },
    rules: {
      ...reactPlugin.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      ...prettierConfig.rules,

      // Prettier integration
      "prettier/prettier": ["error", prettierOptions],

      // Security: ban dangerouslySetInnerHTML — XSS vector
      "react/no-danger": "error",
      // Security: ban eval() — blocked by CSP too, but belt-and-suspenders
      "no-eval": "error",
      "no-implied-eval": "error",
      // Security: ban Function constructor — equivalent to eval
      "no-new-func": "error",

      "react/react-in-jsx-scope": "off",
      "react/prop-types": "off",
    },
    settings: {
      react: { version: "detect" },
    },
  },
  {
    extends: [...tseslint.configs.recommended],
    files: ["e2e/**/*.ts", "playwright.config.ts"],
    languageOptions: {
      globals: { ...globals.node, ...globals.browser },
    },
    plugins: {
      prettier: prettierPlugin,
    },
    rules: {
      ...prettierConfig.rules,
      "prettier/prettier": ["error", prettierOptions],
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
    },
  },
);
