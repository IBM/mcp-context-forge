"use strict";
const neostandard = require("neostandard");
const prettierPlugin = require("eslint-plugin-prettier");
const prettierRecommended = require("eslint-plugin-prettier/recommended");

module.exports = [
  ...neostandard({
    env: ["browser"],
    ignores: neostandard.resolveIgnoresFromGitignore(),
    noStyle: true,
  }),
  prettierRecommended,
  {
    plugins: {
      prettier: prettierPlugin,
    },
    rules: {
      // Match previous style preferences: semicolons and double quotes
      "prettier/prettier": [
        "error",
        {
          semi: true,
          singleQuote: false,
          indentSize: 2,
          tabWidth: 2,
        },
      ],
      indent: ["error", 2, { SwitchCase: 1 }],
      // Preserve previous lint behavior for curly braces and prefer-const
      curly: "error",
      "prefer-const": "error",
    },
  },
];
