<script lang="ts">
  import type { DashboardMetrics } from "../server/metrics";

  let { metrics }: { metrics: DashboardMetrics } = $props();

  const cards = $derived([
    {
      label: "Pages collected",
      value: metrics.pagesCollected,
      detail: "Raw HTML documents saved",
      icon: "pages"
    },
    {
      label: "Pages indexed",
      value: metrics.pagesIndexed,
      detail: "Cleaned and ready for search",
      icon: "index"
    },
    {
      label: "PDFs discovered",
      value: metrics.pdfsDiscovered,
      detail: "Public documents found on source sites",
      icon: "pdf"
    },
    {
      label: "PDFs downloaded",
      value: metrics.pdfsDownloaded,
      detail: "Documents collected for processing",
      icon: "download"
    }
  ]);
</script>

<div class="metrics-grid">
  {#each cards as card}
    <article class="metric-card">
      <div class="metric-topline">
        <span>{card.label}</span>
        <span class="metric-icon" aria-hidden="true">
          {#if card.icon === "pages"}
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M7 3h7l5 5v13H7V3Z" /><path d="M14 3v5h5M10 13h6m-6 4h6" />
            </svg>
          {:else if card.icon === "index"}
            <svg viewBox="0 0 24 24" fill="none">
              <circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4M8 10h5m-5 3h3m-3-6h5" />
            </svg>
          {:else if card.icon === "pdf"}
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M7 3h7l5 5v13H7V3Z" /><path d="M14 3v5h5M10 15h2a1.5 1.5 0 0 0 0-3h-2v5m5-5v5h1a2.5 2.5 0 0 0 0-5h-1" />
            </svg>
          {:else}
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M12 3v12m-5-5 5 5 5-5M5 17v4h14v-4" />
            </svg>
          {/if}
        </span>
      </div>
      <strong class="metric-value">{card.value.toLocaleString("en-US")}</strong>
      <span class="metric-detail">{card.detail}</span>
    </article>
  {/each}
</div>

<style>
  .metrics-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 1rem;
  }

  .metric-card {
    min-width: 0;
    padding: 1.25rem;
    border: 1px solid #e8e0e1;
    border-radius: 1rem;
    background: #fff;
    box-shadow: 0 0.5rem 1.5rem rgb(36 71 45 / 3%);
  }

  .metric-topline {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    color: #66776c;
    font-size: 0.79rem;
    font-weight: 650;
  }

  .metric-icon {
    display: grid;
    width: 2.2rem;
    flex: 0 0 auto;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 0.65rem;
    color: #bd1b2d;
    background: #fbe9eb;
  }

  .metric-icon svg {
    width: 1.2rem;
    stroke: currentColor;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-width: 1.7;
  }

  .metric-value {
    display: block;
    margin: 0.85rem 0 0.25rem;
    color: #33353a;
    font-size: clamp(1.8rem, 3vw, 2.3rem);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.06em;
    line-height: 1;
  }

  .metric-detail {
    color: #829087;
    font-size: 0.75rem;
    line-height: 1.4;
  }

  @media (max-width: 860px) {
    .metrics-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 480px) {
    .metrics-grid {
      gap: 0.65rem;
    }

    .metric-card {
      padding: 0.95rem;
    }

    .metric-topline {
      font-size: 0.72rem;
    }

    .metric-detail {
      font-size: 0.7rem;
    }
  }
</style>
