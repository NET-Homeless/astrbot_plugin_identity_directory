import path from "node:path";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, lazyPlugins } from "vite-plus";

// https://vite.dev/config/
export default defineConfig({
  base: "./",
  resolve: {
    alias: {
      $lib: path.resolve(__dirname, "./src/lib"),
    },
  },
  build: {
    outDir: "../pages/directory",
    emptyOutDir: true,
  },
  plugins: lazyPlugins(() => [tailwindcss(), svelte()]),
});
