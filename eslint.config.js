"use strict";
const neostandard = require("neostandard");

module.exports = [
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
