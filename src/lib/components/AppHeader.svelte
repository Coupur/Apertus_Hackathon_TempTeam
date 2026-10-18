<script lang="ts">
  let {
    email = null,
    active = "welcome"
  }: {
    email?: string | null;
    active?: "welcome" | "dashboard" | "admin";
  } = $props();
</script>

<header class="site-header">
  <a class="brand" href="/" aria-label="Research Navigator home">
    <span class="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 38 38" fill="none">
        <path d="M8 10.5 19 5l11 5.5v13L19 29l-11-5.5v-13Z" />
        <path d="m8.5 11 10.5 5.2L29.5 11M19 16.5V29" />
        <circle cx="8" cy="10.5" r="3" />
        <circle cx="19" cy="5" r="3" />
        <circle cx="30" cy="10.5" r="3" />
        <circle cx="19" cy="29" r="3" />
      </svg>
    </span>
    <span class="brand-name">Research <strong>Navigator</strong></span>
  </a>

  {#if email}
    <nav class="main-nav" aria-label="Main navigation">
      <a href="/" class:current={active === "dashboard"}>Dashboard</a>
      <a href="/admin" class:current={active === "admin"}>Admin</a>
    </nav>
    <div class="account-actions">
      <span class="account-email" title={email}>{email}</span>
      <form method="POST" action="/?/logout">
        <button class="sign-out" type="submit">Sign out</button>
      </form>
    </div>
  {:else}
    <a class="header-cta" href="#sign-in">Get started <span aria-hidden="true">↗</span></a>
  {/if}
</header>

<style>
  .site-header {
    position: relative;
    z-index: 1;
    display: flex;
    width: min(100% - 3rem, 76rem);
    min-height: 5.25rem;
    align-items: center;
    justify-content: space-between;
    gap: 1.5rem;
    margin: 0 auto;
    border-bottom: 1px solid rgb(29 69 53 / 10%);
  }

  .brand {
    display: inline-flex;
    align-items: center;
    gap: 0.7rem;
    text-decoration: none;
  }

  .brand-mark {
    display: grid;
    width: 2.25rem;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 0.7rem;
    background: #fcebed;
  }

  .brand-mark svg {
    width: 1.8rem;
    stroke: #e30613;
    stroke-width: 1.5;
  }

  .brand-mark circle {
    fill: #faf8f8;
    stroke-width: 1.8;
  }

  .brand-name {
    color: #33353a;
    font-size: 0.96rem;
    letter-spacing: -0.025em;
  }

  .brand-name strong {
    color: #bd1b2d;
    font-weight: 700;
  }

  .main-nav,
  .account-actions {
    display: flex;
    align-items: center;
    gap: 1.2rem;
  }

  .main-nav {
    margin-left: auto;
  }

  .main-nav a,
  .account-email,
  .sign-out {
    color: #5f7066;
    font-size: 0.84rem;
    text-decoration: none;
  }

  .main-nav a {
    padding: 0.5rem 0.1rem;
  }

  .main-nav a:hover,
  .main-nav a.current {
    color: #e30613;
  }

  .main-nav a.current {
    font-weight: 700;
  }

  .account-actions form {
    margin: 0;
  }

  .account-email {
    max-width: 12rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sign-out {
    padding: 0.55rem 0.8rem;
    border: 1px solid #e4e1e1;
    border-radius: 999px;
    background: transparent;
  }

  .sign-out:hover {
    color: #e30613;
    background: #fff3f4;
  }

  .header-cta {
    padding: 0.65rem 1rem;
    border-radius: 999px;
    color: #fff;
    background: #e30613;
    font-size: 0.86rem;
    font-weight: 650;
    text-decoration: none;
  }

  .header-cta:hover {
    background: #BD0018;
  }

  @media (max-width: 680px) {
    .site-header {
      width: min(100% - 2rem, 76rem);
      min-height: 4.5rem;
      gap: 0.75rem;
    }

    .brand-name {
      font-size: 0.84rem;
    }

    .main-nav,
    .account-actions {
      gap: 0.65rem;
    }

    .account-email {
      display: none;
    }
  }
</style>
