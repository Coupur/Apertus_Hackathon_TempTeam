import adapter from "@sveltejs/adapter-node";
import { sveltekit } from "@sveltejs/kit/vite";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

const origin = process.env.ORIGIN;

export default defineConfig({
  plugins: [
    sveltekit({
      adapter: adapter(),
      ...(origin ? { paths: { origin } } : {}),
      preprocess: vitePreprocess()
    })
  ]
});
