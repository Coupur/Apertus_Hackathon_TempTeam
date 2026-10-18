<script lang="ts">
  import { Label } from "bits-ui";
  import type { ActionData, PageData } from "./$types";

  let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head>
  <title>Hello world · Research &amp; Expertise Navigator</title>
  <meta
    name="description"
    content="A simple starting point for the Research & Expertise Navigator."
  />
  <meta name="referrer" content="no-referrer" />
</svelte:head>

<main>
  <section class="welcome" aria-labelledby="welcome-heading">
    <p class="eyebrow">Research &amp; Expertise Navigator</p>
    <h1 id="welcome-heading">Hello world</h1>
    <p class="welcome-copy">Your workspace starts here.</p>
  </section>

  <section class="login-card" aria-labelledby="login-heading">
    {#if data.email}
      <h2 id="login-heading">You're signed in</h2>
      <p class="card-copy">Signed in as {data.email}.</p>
      <form method="POST" action="?/logout">
        <button type="submit">Sign out</button>
      </form>
    {:else}
      <h2 id="login-heading">Sign in with email</h2>
      <p class="card-copy">We'll email you a one-time magic link to sign in.</p>

      <form method="POST" action="?/requestLink">
        <Label.Root class="field-label" for="email">Email address</Label.Root>
        <input
          id="email"
          name="email"
          type="email"
          autocomplete="email"
          placeholder="you@example.com"
          required
        />
        <button type="submit">Email me a sign-in link</button>
      </form>
    {/if}
    {#if form?.error}
      <p class="notice" role="alert">{form.error}</p>
    {:else if form?.message}
      <p class="hint" role="status">{form.message}</p>
    {:else if data.notice}
      <p class="hint" role="status">{data.notice}</p>
    {/if}
  </section>
</main>
