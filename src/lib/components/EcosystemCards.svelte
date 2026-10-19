<script lang="ts">
  import { ecosystems } from "../data/ecosystems";
  import type { WebsiteSource } from "../server/sources";

  let { sources = [] }: { sources: WebsiteSource[] } = $props();
  let additionalSources = $derived(
    sources.filter((source) => !ecosystems.some((ecosystem) => ecosystem.id === source.id))
  );

</script>

<div
  class="ecosystem-strip"
  role="region"
  aria-label="Research source websites. Scroll horizontally for more."
>
  {#each ecosystems as ecosystem}
    {@const source = sources.find((item) => item.id === ecosystem.id)}
    {#if source}
      <a class="ecosystem-card" href={source.url} target="_blank" rel="noreferrer">
        <span class="card-icon" aria-hidden="true">
          {#if ecosystem.icon === "university"}
            <svg viewBox="0 0 28 28" fill="none">
              <path d="m3 10 11-6 11 6M5 12h18M7 13v9m5-9v9m4-9v9m5-9v9M4 24h20" />
            </svg>
          {:else if ecosystem.icon === "research"}
            <svg viewBox="0 0 28 28" fill="none">
              <path d="M10 4h8m-6 0v8l-6 10a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-6-10V4M9 18h10m-8-4h6" />
              <circle cx="12" cy="21" r="1" />
              <circle cx="17" cy="22" r="1" />
            </svg>
          {:else}
            <svg viewBox="0 0 28 28" fill="none">
              <path d="M14 24s-9-5.7-9-12a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 6.3-9 12-9 12Z" />
              <path d="M8 14h4l2-4 3 8 2-4h2" />
            </svg>
          {/if}
        </span>
        <span class="card-eyebrow">{ecosystem.eyebrow}</span>
        <strong>{source.name}</strong>
        <span class="card-description">{ecosystem.description}</span>
        <span class="card-link">Explore source <span aria-hidden="true">↗</span></span>
      </a>
    {/if}
  {/each}
  {#each additionalSources as source (source.id)}
    <a class="ecosystem-card extra-card" href={source.url} target="_blank" rel="noreferrer">
      <span class="card-icon extra-icon" aria-hidden="true">
        <svg viewBox="0 0 28 28" fill="none">
          <circle cx="14" cy="14" r="10" />
          <path d="M4 14h20M14 4c3 3 4.5 6.3 4.5 10S17 21 14 24m0-20c-3 3-4.5 6.3-4.5 10S11 21 14 24" />
        </svg>
      </span>
      <span class="card-eyebrow">Additional source</span>
      <strong>{source.name}</strong>
      <span class="card-description">{source.institution}</span>
      <span class="card-link">Explore source <span aria-hidden="true">↗</span></span>
    </a>
  {/each}
</div>

<style>
  .ecosystem-strip {
    display: flex;
    overflow-x: auto;
    gap: 1rem;
    padding: 0.75rem 0 1.25rem;
    scroll-behavior: smooth;
    scroll-snap-type: x mandatory;
    scrollbar-color: #e7bfc5 transparent;
    scrollbar-width: thin;
  }

  .ecosystem-card {
    display: flex;
    min-width: 0;
    min-height: 14.5rem;
    flex: 0 0 calc((100% - 2rem) / 3);
    flex-direction: column;
    align-items: flex-start;
    padding: 1.35rem;
    border: 1px solid #e8e0e1;
    border-radius: 1rem;
    color: inherit;
    background: #fff;
    scroll-snap-align: start;
    text-decoration: none;
    transition:
      transform 150ms ease,
      box-shadow 150ms ease,
      border-color 150ms ease;
  }

  .ecosystem-card:hover {
    transform: translateY(-3px);
    border-color: #e7bfc5;
    box-shadow: 0 0.75rem 2rem rgb(44 78 52 / 8%);
  }

  .card-icon {
    display: grid;
    width: 2.7rem;
    aspect-ratio: 1;
    margin-bottom: 1.25rem;
    place-items: center;
    border-radius: 0.8rem;
    color: #bd1b2d;
    background: #fbe9eb;
  }

  .card-icon svg {
    width: 1.5rem;
    stroke: currentColor;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-width: 1.6;
  }

  .extra-icon {
    color: #bd1b2d;
    background: #fff0f1;
  }

  .card-eyebrow {
    margin-bottom: 0.45rem;
    color: #857074;
    font-size: 0.69rem;
    font-weight: 750;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  strong {
    margin-bottom: 0.6rem;
    color: #33353a;
    font-size: 1.04rem;
    letter-spacing: -0.025em;
  }

  .card-description {
    color: #68786e;
    font-size: 0.84rem;
    line-height: 1.6;
  }

  .card-link {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    margin-top: auto;
    padding-top: 1rem;
    color: #bd1b2d;
    font-size: 0.8rem;
    font-weight: 700;
  }

  @media (max-width: 780px) {
    .ecosystem-card {
      min-height: 14rem;
      flex-basis: min(78vw, 19rem);
    }
  }
</style>
