import { defineConfig } from "orval";

export default defineConfig({
  contextforge: {
    input: { target: "./openapi.json" },
    output: {
      schemas: {
        path: "./src/generated/types/",
      },
      target: "./src/generated/types/",
      clean: true,
      client: "fetch",
      override: {
        useTypeOverInterfaces: true,
      },
    },
    hooks: {
      "afterAllFilesWrite": "prettier src/generated --write"
    }
  },
});
