<script lang="ts">
  import { Label } from "bits-ui";
  import AppHeader from "../lib/components/AppHeader.svelte";
  import DashboardMetrics from "../lib/components/DashboardMetrics.svelte";
  import EcosystemCards from "../lib/components/EcosystemCards.svelte";
  import WelcomeArtwork from "../lib/components/WelcomeArtwork.svelte";
  import type { ActionData, PageData } from "./$types";

  let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head>
  <title>Research Navigator · Connect to expertise</title>
  <meta
    name="description"
    content="Discover research expertise, projects and services across Bern's connected research ecosystem."
  />
  <meta name="referrer" content="no-referrer" />
</svelte:head>

<AppHeader email={data.email} active="dashboard" />

{#if data.email && data.metrics}
  <main class="dashboard">
    <section class="dashboard-heading">
      <div>
        <p class="eyebrow">Your workspace</p>
        <h1>Welcome back<span class="heading-period">.</span></h1>
        <p class="page-intro">Explore the research knowledge connected across Bern.</p>
        <p class="coverage-pill">
          <span aria-hidden="true"></span>{data.sources.length} active data sources
        </p>
      </div>
      <a class="button-primary dashboard-admin-link" href="/admin">
        Manage data sources <span aria-hidden="true">↗</span>
      </a>
    </section>

    {#if data.notice}
      <p class="notice" role="status">{data.notice}</p>
    {/if}

    <section class="dashboard-section" aria-labelledby="activity-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Research activity</p>
          <h2 id="activity-title">Your ecosystem at a glance</h2>
        </div>
        <p class="section-note">Metrics will appear when analytics is connected</p>
      </div>
      <DashboardMetrics metrics={data.metrics} />
    </section>

    <section class="dashboard-section ecosystem-section" aria-labelledby="ecosystem-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Connected datasets</p>
          <h2 id="ecosystem-title">One distributed information ecosystem</h2>
        </div>
        <a class="text-link" href="/admin">View source registry <span aria-hidden="true">→</span></a>
      </div>
      <EcosystemCards sources={data.sources} />
    </section>

    <section class="pipeline-note">
      <span class="pipeline-icon" aria-hidden="true">✳</span>
      <div>
        <strong>From public pages to useful connections</strong>
        <p>
          The current prototype maps and indexes public web pages. PDF links are tracked
          separately from documents downloaded for processing.
        </p>
      </div>
    </section>
  </main>
{:else}
  <main class="landing">
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow"><span class="eyebrow-dot"></span> A connected view of Bern research</p>
        <h1>Welcome!<br /><span>Expertise is closer than you think.</span></h1>
        <p class="hero-description">
          Find the people, projects and research capabilities that can help move your next
          idea forward.
        </p>
        <div class="hero-actions">
          <a class="button-primary" href="#sign-in">Explore the navigator <span aria-hidden="true">↗</span></a>
          <a class="button-secondary" href="#ecosystems">Meet the ecosystem</a>
        </div>
        <div class="hero-proof">
          <span class="proof-avatars" aria-hidden="true"><i>U</i><i>A</i><i>D</i></span>
          <span>University-wide expertise, all in one place</span>
        </div>
      </div>
      <WelcomeArtwork />
    </section>

    <section class="ecosystem-section landing-section" id="ecosystems">
      <div class="section-heading">
        <div>
          <p class="eyebrow">The starting point</p>
          <h2>One connected research landscape.</h2>
        </div>
        <p class="section-note">
          An extensible map of public research information, designed to grow.
        </p>
      </div>
      <EcosystemCards sources={data.sources} />
    </section>

    <section class="sign-in-section" id="sign-in">
      <div class="sign-in-copy">
        <p class="eyebrow">A little closer to the right connection</p>
        <h2>Sign in to explore your research workspace.</h2>
        <p>
          Get a secure one-time sign-in link in your inbox. No password to remember.
        </p>
        <div class="sign-in-perks">
          <span><b aria-hidden="true">✓</b> Discover expertise across institutions</span>
          <span><b aria-hidden="true">✓</b> Follow projects, services and facilities</span>
          <span><b aria-hidden="true">✓</b> Keep your research connections together</span>
        </div>
      </div>

      <section class="login-card" aria-labelledby="login-heading">
        <div class="login-card-icon" aria-hidden="true">
          <svg viewBox="0 0 28 28" fill="none">
            <rect x="3.5" y="6" width="21" height="16" rx="3" />
            <path d="m5 8 9 7 9-7" />
          </svg>
        </div>
        <h3 id="login-heading">Welcome to your workspace</h3>
        <p class="card-copy">Enter your email and we’ll send you a secure sign-in link.</p>

        <form method="POST" action="?/requestLink">
          <Label.Root class="field-label" for="email">Work or research email</Label.Root>
          <input
            id="email"
            name="email"
            type="email"
            autocomplete="email"
            placeholder="you@institution.ch"
            required
          />
          <button class="button-primary login-button" type="submit">Email me a sign-in link</button>
        </form>
        {#if form?.error}
          <p class="notice" role="alert">{form.error}</p>
        {:else if form?.message}
          <p class="success-message" role="status">{form.message}</p>
        {:else if data.notice}
          <p class="success-message" role="status">{data.notice}</p>
        {/if}
        <p class="privacy-note">Secure, password-free sign-in. Your link expires after 15 minutes.</p>
      </section>
    </section>
  </main>
{/if}

<footer class="site-footer">
  <span>Research Navigator</span>
  <span>Built around a connected Bern research ecosystem</span>
</footer>

<style>
  .landing,
  .dashboard {
    width: min(100% - 3rem, 76rem);
    margin: 0 auto;
  }

  .hero {
    display: grid;
    min-height: 34rem;
    grid-template-columns: 1fr 0.92fr;
    align-items: center;
    gap: 1rem;
    padding: 2.25rem 0 3rem;
  }

  .hero-copy {
    position: relative;
    z-index: 1;
    max-width: 34rem;
    padding: 1rem 0;
  }

  .eyebrow {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    margin: 0 0 0.95rem;
    color: #9d4951;
    font-size: 0.72rem;
    font-weight: 750;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  .eyebrow-dot {
    width: 0.5rem;
    aspect-ratio: 1;
    border-radius: 50%;
    background: #e30613;
    box-shadow: 0 0 0 0.22rem #fdebed;
  }

  h1,
  h2,
  h3,
  p {
    margin-top: 0;
  }

  .hero h1,
  .dashboard h1 {
    margin: 0;
    color: #303136;
    font-size: clamp(3rem, 6.4vw, 5.3rem);
    font-weight: 680;
    letter-spacing: -0.075em;
    line-height: 0.99;
  }

  .hero h1 span {
    color: #9d4951;
  }

  .hero-description {
    max-width: 32rem;
    margin: 1.35rem 0 1.6rem;
    color: #68796e;
    font-size: 1.08rem;
    line-height: 1.7;
  }

  .hero-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem;
  }

  .button-primary,
  .button-secondary {
    display: inline-flex;
    min-height: 2.9rem;
    align-items: center;
    justify-content: center;
    gap: 0.55rem;
    padding: 0.7rem 1.15rem;
    border: 1px solid transparent;
    border-radius: 0.65rem;
    font: inherit;
    font-size: 0.86rem;
    font-weight: 700;
    text-decoration: none;
    transition:
      background 120ms ease,
      transform 120ms ease,
      border-color 120ms ease;
  }

  .button-primary {
    color: #fff;
    background: #e30613;
  }

  .button-primary:hover {
    transform: translateY(-1px);
    background: #BD0018;
  }

  .button-secondary {
    border-color: #e7d6d8;
    color: #515257;
    background: rgb(255 255 255 / 50%);
  }

  .button-secondary:hover {
    border-color: #e6b9bf;
    background: #fff;
  }

  .hero-proof {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-top: 1.75rem;
    color: #728076;
    font-size: 0.78rem;
  }

  .proof-avatars {
    display: flex;
    padding-left: 0.35rem;
  }

  .proof-avatars i {
    display: grid;
    width: 1.6rem;
    aspect-ratio: 1;
    margin-left: -0.35rem;
    place-items: center;
    border: 2px solid #f8f6f6;
    border-radius: 50%;
    color: #bd1b2d;
    background: #f5dfe2;
    font-size: 0.58rem;
    font-style: normal;
    font-weight: 750;
  }

  .proof-avatars i:nth-child(2) {
    color: #795f34;
    background: #eee4cf;
  }

  .proof-avatars i:nth-child(3) {
    color: #536780;
    background: #dce7ef;
  }

  .landing-section {
    padding: 3rem 0;
    border-top: 1px solid #eae5e5;
  }

  .section-heading {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1.5rem;
    margin-bottom: 1.35rem;
  }

  .section-heading .eyebrow,
  .dashboard-section .eyebrow {
    margin-bottom: 0.45rem;
  }

  .section-heading h2,
  .dashboard-section h2 {
    margin-bottom: 0;
    color: #33353a;
    font-size: clamp(1.45rem, 3vw, 1.9rem);
    letter-spacing: -0.045em;
  }

  .section-note {
    max-width: 20rem;
    margin-bottom: 0.1rem;
    color: #718076;
    font-size: 0.82rem;
    line-height: 1.55;
  }

  .sign-in-section {
    display: grid;
    grid-template-columns: 1fr minmax(18rem, 25rem);
    align-items: center;
    gap: clamp(2rem, 7vw, 6rem);
    margin: 1rem 0 4rem;
    padding: clamp(1.5rem, 5vw, 3.5rem);
    border: 1px solid #eee1e2;
    border-radius: 1.4rem;
    background:
      radial-gradient(ellipse at 1% 100%, rgb(220 238 222 / 55%), transparent 35%),
      #fff4f4;
  }

  .sign-in-copy h2 {
    max-width: 30rem;
    margin-bottom: 0.8rem;
    color: #35363a;
    font-size: clamp(1.8rem, 4vw, 2.65rem);
    letter-spacing: -0.06em;
    line-height: 1.08;
  }

  .sign-in-copy > p:not(.eyebrow) {
    max-width: 28rem;
    margin-bottom: 1.45rem;
    color: #68796e;
    line-height: 1.65;
  }

  .sign-in-perks {
    display: grid;
    gap: 0.7rem;
    color: #685b5d;
    font-size: 0.84rem;
  }

  .sign-in-perks b {
    display: inline-grid;
    width: 1.2rem;
    aspect-ratio: 1;
    margin-right: 0.35rem;
    place-items: center;
    border-radius: 50%;
    color: #bd1b2d;
    background: #f7dfe2;
    font-size: 0.72rem;
  }

  .login-card {
    padding: 1.7rem;
    border: 1px solid #e8e0e1;
    border-radius: 1rem;
    background: #fff;
    box-shadow: 0 1.2rem 3.5rem rgb(37 72 46 / 8%);
  }

  .login-card-icon {
    display: grid;
    width: 2.75rem;
    aspect-ratio: 1;
    margin-bottom: 1.1rem;
    place-items: center;
    border-radius: 0.75rem;
    color: #bd1b2d;
    background: #fbe9eb;
  }

  .login-card-icon svg {
    width: 1.55rem;
    stroke: currentColor;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-width: 1.7;
  }

  .login-card h3 {
    margin-bottom: 0.4rem;
    color: #33353a;
    font-size: 1.14rem;
    letter-spacing: -0.035em;
  }

  .card-copy {
    margin-bottom: 1.15rem;
    color: #728076;
    font-size: 0.84rem;
    line-height: 1.55;
  }

  .login-card form {
    display: grid;
    gap: 0.65rem;
  }

  :global(.field-label) {
    color: #45464a;
    font-size: 0.8rem;
    font-weight: 700;
  }

  .login-card input {
    width: 100%;
    min-height: 2.9rem;
    padding: 0.7rem 0.8rem;
    border: 1px solid #d4dfd6;
    border-radius: 0.55rem;
    color: #33353a;
    background: #fff;
  }

  input::placeholder {
    color: #9aa79e;
  }

  input:focus-visible,
  button:focus-visible,
  a:focus-visible {
    outline: 3px solid rgb(56 121 82 / 25%);
    outline-offset: 2px;
  }

  .login-button {
    width: 100%;
    margin-top: 0.25rem;
    cursor: pointer;
  }

  .privacy-note {
    margin: 1rem 0 0;
    color: #89968d;
    font-size: 0.7rem;
    line-height: 1.5;
    text-align: center;
  }

  .notice,
  .success-message {
    margin: 0.8rem 0 0;
    padding: 0.75rem;
    border-radius: 0.55rem;
    font-size: 0.8rem;
    line-height: 1.5;
  }

  .notice {
    color: #704d14;
    background: #fff6df;
  }

  .success-message {
    color: #7a2934;
    background: #fdebed;
  }

  .dashboard {
    min-height: calc(100vh - 9rem);
    padding: 3.25rem 0 4rem;
  }

  .dashboard-heading {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1.5rem;
    margin-bottom: 2.25rem;
  }

  .dashboard h1 {
    font-size: clamp(2.6rem, 5vw, 4rem);
  }

  .heading-period {
    color: #d54b58;
  }

  .page-intro {
    margin: 0.75rem 0 0;
    color: #718076;
    font-size: 1rem;
  }

  .coverage-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.85rem 0 0;
    padding: 0.38rem 0.65rem;
    border: 1px solid #ead7da;
    border-radius: 999px;
    color: #9d4951;
    background: #fff3f4;
    font-size: 0.72rem;
    font-weight: 650;
  }

  .coverage-pill span {
    width: 0.4rem;
    aspect-ratio: 1;
    border-radius: 50%;
    background: #e30613;
  }

  .dashboard-admin-link {
    flex: 0 0 auto;
  }

  .dashboard-section {
    margin-top: 2.5rem;
  }

  .dashboard-section .section-heading {
    margin-bottom: 1.15rem;
  }

  .text-link {
    color: #bd1b2d;
    font-size: 0.81rem;
    font-weight: 700;
    text-decoration: none;
    white-space: nowrap;
  }

  .text-link:hover {
    text-decoration: underline;
  }

  .pipeline-note {
    display: flex;
    align-items: flex-start;
    gap: 1rem;
    margin-top: 2.5rem;
    padding: 1.2rem 1.35rem;
    border: 1px solid #eee2e3;
    border-radius: 0.9rem;
    background: #faf7f7;
  }

  .pipeline-icon {
    display: grid;
    width: 2rem;
    flex: 0 0 auto;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 0.6rem;
    color: #bd1b2d;
    background: #fbe9eb;
  }

  .pipeline-note strong {
    display: block;
    margin-bottom: 0.3rem;
    color: #3e4044;
    font-size: 0.87rem;
  }

  .pipeline-note p {
    margin: 0;
    color: #748178;
    font-size: 0.79rem;
    line-height: 1.55;
  }

  .site-footer {
    display: flex;
    width: min(100% - 3rem, 76rem);
    justify-content: space-between;
    gap: 1rem;
    margin: 0 auto;
    padding: 1.25rem 0 1.5rem;
    border-top: 1px solid #eae5e5;
    color: #839087;
    font-size: 0.72rem;
  }

  @media (max-width: 900px) {
    .hero {
      min-height: auto;
      grid-template-columns: 1fr 0.75fr;
      padding: 3.5rem 0;
    }

    .hero h1 {
      font-size: clamp(2.8rem, 6vw, 4rem);
    }

    .sign-in-section {
      grid-template-columns: 1fr minmax(17rem, 22rem);
      gap: 2rem;
    }
  }

  @media (max-width: 680px) {
    .landing,
    .dashboard {
      width: min(100% - 2rem, 76rem);
    }

    .hero {
      grid-template-columns: 1fr;
      gap: 0;
      padding: 3rem 0 2rem;
    }

    .hero-copy {
      padding-bottom: 0;
    }

    .hero h1 {
      font-size: clamp(2.8rem, 12vw, 4.2rem);
    }

    .hero-description {
      font-size: 0.98rem;
    }

    .hero :global(.artwork) {
      max-width: 27rem;
      margin-top: -0.25rem;
    }

    .section-heading,
    .dashboard-heading {
      align-items: flex-start;
      flex-direction: column;
    }

    .section-note {
      max-width: 28rem;
    }

    .sign-in-section {
      grid-template-columns: 1fr;
      gap: 1.5rem;
      margin-bottom: 2.5rem;
      padding: 1.4rem;
    }

    .login-card {
      padding: 1.3rem;
    }

    .dashboard {
      padding-top: 2.5rem;
    }

    .dashboard-admin-link {
      width: 100%;
    }

    .site-footer {
      width: min(100% - 2rem, 76rem);
      flex-direction: column;
      gap: 0.4rem;
    }
  }
</style>
