import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts", "adapters/**/*.test.ts"],
    environment: "node",
  },
});
