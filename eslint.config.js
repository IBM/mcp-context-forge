"use strict";
const neostandard = require("neostandard");

module.exports = [
  // Ignore compiled build artefacts — these are minified and not authored code
  {
    ignores: ["mcpgateway/static/bundle-*.js", "mcpgateway/static/.vite/**"],
  },
  ...neostandard({
    env: ["browser"],
    ignores: neostandard.resolveIgnoresFromGitignore(),
    noStyle: true,
  }),
  {
    rules: {
      indent: ["error", 2, { SwitchCase: 1 }],
      // Preserve previous lint behavior for curly braces and prefer-const
      curly: "error",
      "prefer-const": "error",
    },
  },
];
