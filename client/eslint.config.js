import tseslint from "typescript-eslint";
import reactPlugin from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default tseslint.config(
  { ignores: ["../mcpgateway/static/app"] },
  {
    extends: [...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      globals: globals.browser,
    },
    plugins: {
      react: reactPlugin,
      "react-hooks": reactHooks,
    },
    rules: {
      ...reactPlugin.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,

      // Security: ban dangerouslySetInnerHTML — XSS vector
      "react/no-danger": "error",
      // Security: ban eval() — blocked by CSP too, but belt-and-suspenders
      "no-eval": "error",
      "no-implied-eval": "error",
      // Security: ban Function constructor — equivalent to eval
      "no-new-func": "error",

      "react/react-in-jsx-scope": "off",
    },
    settings: {
      react: { version: "detect" },
    },
  }
);
