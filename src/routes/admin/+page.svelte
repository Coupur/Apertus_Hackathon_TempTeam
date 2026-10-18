<script lang="ts">
  import { enhance } from "$app/forms";
  import { Label } from "bits-ui";
  import AppHeader from "../../lib/components/AppHeader.svelte";
  import EcosystemCards from "../../lib/components/EcosystemCards.svelte";
  import type { ActionData, PageData } from "./$types";

  let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head>
  <title>Data sources · Research Navigator</title>
  <meta name="description" content="Manage the websites in your research data ecosystem." />
</svelte:head>

<AppHeader email={data.email} active="admin" />

<main class="admin-page">
  <div class="admin-heading">
    <div>
      <p class="eyebrow">Workspace administration</p>
      <h1>Data sources</h1>
      <p class="admin-intro">
        Bring public research websites into one flexible, connected source registry.
      </p>
    </div>
    <a class="back-link" href="/">← Back to dashboard</a>
  </div>

  {#if form?.error}
    <p class="feedback error global-feedback" role="alert">{form.error}</p>
  {:else if form?.success}
    <p class="feedback success global-feedback" role="status">{form.success}</p>
  {/if}

  <section class="admin-section" aria-labelledby="ecosystem-title">
    <div class="section-heading">
      <div>
        <p class="eyebrow">Prototype collections</p>
        <h2 id="ecosystem-title">Starting research ecosystem</h2>
      </div>
      <span class="source-count">
        {data.sources.length} active websites
      </span>
    </div>
    <EcosystemCards sources={data.sources} />
  </section>

  <section class="admin-section source-management" aria-labelledby="source-form-title">
    <div class="source-form-panel">
      <div class="panel-heading">
        <span class="panel-number">01</span>
        <div>
          <p class="eyebrow">Extend the map</p>
          <h2 id="source-form-title">Add a website</h2>
          <p class="panel-copy">
            Add an institutional website or research data source. It will join the
            registry used by the crawler.
          </p>
        </div>
      </div>

      <form method="POST" action="?/addSource" class="source-form" use:enhance>
        <div class="field-pair">
          <div class="form-field">
            <Label.Root class="field-label" for="source-name">Source name</Label.Root>
            <input
              id="source-name"
              name="name"
              type="text"
              maxlength="120"
              placeholder="e.g. Institute of Medical Engineering"
              required
            />
          </div>
          <div class="form-field">
            <Label.Root class="field-label" for="institution">Institution or collection</Label.Root>
            <input
              id="institution"
              name="institution"
              type="text"
              maxlength="120"
              placeholder="e.g. University of Bern"
              required
            />
          </div>
        </div>
        <div class="form-field">
          <Label.Root class="field-label" for="source-url">Website URL</Label.Root>
          <input
            id="source-url"
            name="url"
            type="url"
            placeholder="https://research.example.org/"
            required
          />
          <span class="field-hint">Use the public root URL for this website.</span>
        </div>
        <div class="form-field">
          <Label.Root class="field-label" for="seed-paths">Starting paths <span>(optional)</span></Label.Root>
          <textarea
            id="seed-paths"
            name="seedPaths"
            rows="3"
            placeholder={"/research/\n/people/\n/projects/"}
          ></textarea>
          <span class="field-hint">Add one site-local path per line to guide discovery.</span>
        </div>
        <button class="primary-button" type="submit">Add to source registry <span aria-hidden="true">→</span></button>
      </form>
    </div>

    <div class="registry-panel">
      <div class="registry-heading">
        <div>
          <p class="eyebrow">Current configuration</p>
          <h2>Configured website roots</h2>
          <p class="registry-copy">
            University of Bern is its own source, alongside ARTORG and Diabetes Center Berne.
            The supplied UniBE subdomain inventory adds further sites to the same ecosystem.
          </p>
        </div>
        <span class="registry-count">{data.sources.length}</span>
      </div>

      <div class="source-list">
        {#each data.sources as source (source.id)}
          <article class="source-row">
            <span class="source-initial" aria-hidden="true">{source.name.slice(0, 1).toUpperCase()}</span>
            <div class="source-details">
              <div class="source-title">
                <strong>{source.name}</strong>
                <span class:added={source.sourceType === "custom"} class="source-tag">
                  {source.sourceType === "custom" ? "Added" : "Core"}
                </span>
              </div>
              <span class="source-institution">{source.institution}</span>
              <a class="source-url" href={source.url} target="_blank" rel="noreferrer">{source.url}</a>
              {#if source.seedPaths.length}
                <span class="seed-summary">{source.seedPaths.length} starting paths</span>
              {/if}
            </div>
            <div class="source-actions">
              <details class="edit-details">
                <summary>Edit</summary>
                <form method="POST" action="?/editSource" class="edit-form" use:enhance>
                  <input type="hidden" name="id" value={source.id} />
                  <label>
                    Source name
                    <input name="name" value={source.name} maxlength="120" required />
                  </label>
                  <label>
                    Institution
                    <input name="institution" value={source.institution} maxlength="120" required />
                  </label>
                  <label>
                    Website URL
                    <input name="url" type="url" value={source.url} required />
                  </label>
                  <label>
                    Starting paths
                    <textarea name="seedPaths" rows="3">{source.seedPaths.join("\n")}</textarea>
                  </label>
                  <button class="save-edit" type="submit">Save changes</button>
                </form>
              </details>
              <form method="POST" action="?/removeSource" use:enhance>
                <input type="hidden" name="id" value={source.id} />
                <button class="remove-source" type="submit">Remove</button>
              </form>
            </div>
          </article>
        {:else}
          <p class="empty-sources">No additional website sources yet.</p>
        {/each}
      </div>
    </div>
  </section>

  <section class="ecosystem-guide">
    <span class="guide-icon" aria-hidden="true">✳</span>
    <div>
      <strong>Designed to grow</strong>
      <p>
        New websites are stored in the shared source registry and become available to
        <code>python -m navigator sources</code> and the crawler.
      </p>
    </div>
  </section>
</main>

<style>
  .admin-page {
    width: min(100% - 3rem, 76rem);
    min-height: calc(100vh - 9rem);
    margin: 0 auto;
    padding: 3.1rem 0 4rem;
  }

  .admin-heading {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1.5rem;
    margin-bottom: 2.25rem;
  }

  .eyebrow {
    margin: 0 0 0.45rem;
    color: #9d4951;
    font-size: 0.72rem;
    font-weight: 750;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  h1,
  h2,
  p {
    margin-top: 0;
  }

  h1 {
    margin-bottom: 0;
    color: #303136;
    font-size: clamp(2.5rem, 5vw, 3.8rem);
    letter-spacing: -0.075em;
    line-height: 1;
  }

  h2 {
    margin-bottom: 0;
    color: #33353a;
    font-size: 1.35rem;
    letter-spacing: -0.04em;
  }

  .admin-intro {
    max-width: 38rem;
    margin: 0.8rem 0 0;
    color: #718076;
    line-height: 1.6;
  }

  .back-link {
    color: #bd1b2d;
    font-size: 0.82rem;
    font-weight: 700;
    text-decoration: none;
    white-space: nowrap;
  }

  .back-link:hover {
    text-decoration: underline;
  }

  .admin-section {
    margin-top: 2.5rem;
  }

  .section-heading,
  .registry-heading {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1.15rem;
  }

  .registry-heading > div {
    min-width: 0;
  }

  .registry-copy {
    max-width: 30rem;
    margin: 0.4rem 0 0;
    color: #79857c;
    font-size: 0.72rem;
    line-height: 1.5;
  }

  .source-count {
    color: #748178;
    font-size: 0.78rem;
  }

  .source-management {
    display: grid;
    grid-template-columns: minmax(17rem, 0.85fr) minmax(0, 1.15fr);
    align-items: start;
    gap: 1.1rem;
  }

  .source-form-panel,
  .registry-panel {
    padding: 1.5rem;
    border: 1px solid #e8e0e1;
    border-radius: 1rem;
    background: #fff;
    box-shadow: 0 0.5rem 1.5rem rgb(36 71 45 / 3%);
  }

  .panel-heading {
    display: flex;
    align-items: flex-start;
    gap: 0.9rem;
    margin-bottom: 1.35rem;
  }

  .panel-number {
    display: grid;
    width: 2rem;
    flex: 0 0 auto;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 0.65rem;
    color: #bd1b2d;
    background: #fbe9eb;
    font-size: 0.78rem;
    font-weight: 750;
  }

  .panel-heading .eyebrow,
  .registry-heading .eyebrow {
    margin-bottom: 0.35rem;
  }

  .panel-copy {
    margin: 0.5rem 0 0;
    color: #758279;
    font-size: 0.8rem;
    line-height: 1.55;
  }

  .source-form {
    display: grid;
    gap: 0.9rem;
  }

  .field-pair {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
  }

  .form-field {
    display: grid;
    min-width: 0;
    gap: 0.42rem;
  }

  :global(.field-label) {
    color: #45464a;
    font-size: 0.78rem;
    font-weight: 700;
  }

  :global(.field-label span) {
    color: #95a197;
    font-weight: 500;
  }

  input,
  textarea {
    width: 100%;
    min-height: 2.75rem;
    padding: 0.7rem 0.75rem;
    border: 1px solid #d4dfd6;
    border-radius: 0.55rem;
    color: #33353a;
    background: #fff;
    font: inherit;
    font-size: 0.8rem;
  }

  textarea {
    resize: vertical;
    line-height: 1.5;
  }

  input::placeholder,
  textarea::placeholder {
    color: #a0aaa3;
  }

  input:focus-visible,
  textarea:focus-visible,
  button:focus-visible,
  a:focus-visible {
    outline: 3px solid rgb(56 121 82 / 25%);
    outline-offset: 2px;
  }

  .field-hint {
    color: #89958d;
    font-size: 0.69rem;
    line-height: 1.4;
  }

  .primary-button {
    display: inline-flex;
    min-height: 2.8rem;
    align-items: center;
    justify-content: center;
    gap: 0.55rem;
    padding: 0.7rem 1rem;
    border: 0;
    border-radius: 0.6rem;
    color: #fff;
    background: #e30613;
    font: inherit;
    font-size: 0.82rem;
    font-weight: 700;
    cursor: pointer;
  }

  .primary-button:hover {
    background: #BD0018;
  }

  .feedback {
    margin: 0;
    padding: 0.7rem;
    border-radius: 0.55rem;
    font-size: 0.78rem;
    line-height: 1.5;
  }

  .feedback.error {
    color: #704d14;
    background: #fff6df;
  }

  .feedback.success {
    color: #7a2934;
    background: #fdebed;
  }

  .global-feedback {
    margin: -1.2rem 0 1.3rem;
  }

  .registry-heading {
    align-items: center;
    padding-bottom: 0.9rem;
    border-bottom: 1px solid #edf1ed;
  }

  .registry-count {
    display: grid;
    width: 2rem;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 50%;
    color: #bd1b2d;
    background: #fbe9eb;
    font-size: 0.78rem;
    font-weight: 750;
  }

  .source-list {
    display: grid;
  }

  .source-row {
    display: flex;
    align-items: flex-start;
    gap: 0.8rem;
    padding: 0.9rem 0;
    border-bottom: 1px solid #edf1ed;
  }

  .source-row:last-child {
    border-bottom: 0;
  }

  .source-initial {
    display: grid;
    width: 2.25rem;
    flex: 0 0 auto;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 0.7rem;
    color: #bd1b2d;
    background: #fbe9eb;
    font-size: 0.82rem;
    font-weight: 750;
  }

  .source-details {
    display: grid;
    min-width: 0;
    flex: 1;
    gap: 0.22rem;
  }

  .source-title {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.45rem;
  }

  .source-title strong {
    color: #3a3c40;
    font-size: 0.82rem;
  }

  .source-tag {
    padding: 0.15rem 0.4rem;
    border-radius: 999px;
    color: #6a756e;
    background: #f0f3f0;
    font-size: 0.61rem;
    font-weight: 700;
    text-transform: uppercase;
  }

  .source-tag.added {
    color: #bd1b2d;
    background: #fbe9eb;
  }

  .source-institution,
  .source-url,
  .seed-summary {
    overflow-wrap: anywhere;
    color: #77847a;
    font-size: 0.7rem;
    line-height: 1.4;
  }

  .source-url {
    color: #9d4951;
    text-decoration: none;
  }

  .source-url:hover {
    text-decoration: underline;
  }

  .seed-summary {
    color: #96a097;
    font-size: 0.65rem;
  }

  .source-actions {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 0.4rem;
  }

  .source-actions form {
    margin: 0;
  }

  .edit-details {
    position: relative;
  }

  .edit-details summary {
    padding: 0.45rem 0.6rem;
    border: 1px solid #e5eae5;
    border-radius: 0.5rem;
    color: #79575b;
    font-size: 0.7rem;
    font-weight: 650;
    list-style: none;
    cursor: pointer;
  }

  .edit-details summary::-webkit-details-marker {
    display: none;
  }

  .edit-details[open] summary {
    border-color: #e6b9bf;
    background: #faf7f7;
  }

  .edit-form {
    position: absolute;
    z-index: 2;
    top: calc(100% + 0.45rem);
    right: 0;
    display: grid;
    width: min(19rem, 75vw);
    gap: 0.65rem;
    padding: 0.9rem;
    border: 1px solid #dce5de;
    border-radius: 0.8rem;
    background: #fff;
    box-shadow: 0 0.8rem 2rem rgb(37 72 46 / 12%);
  }

  .edit-form label {
    display: grid;
    gap: 0.3rem;
    color: #526259;
    font-size: 0.67rem;
    font-weight: 700;
  }

  .edit-form input,
  .edit-form textarea {
    width: 100%;
    padding: 0.55rem;
    border: 1px solid #d4dfd6;
    border-radius: 0.45rem;
    font: inherit;
    font-size: 0.72rem;
    font-weight: 400;
  }

  .save-edit {
    min-height: 2.2rem;
    border: 0;
    border-radius: 0.5rem;
    color: #fff;
    background: #e30613;
    font-size: 0.72rem;
    font-weight: 700;
    cursor: pointer;
  }

  .save-edit:hover {
    background: #BD0018;
  }

  .remove-source {
    min-height: 1.9rem;
    padding: 0.4rem 0.55rem;
    border: 1px solid #e5eae5;
    border-radius: 0.55rem;
    color: #829087;
    background: #fff;
    font-size: 0.68rem;
    font-weight: 650;
    cursor: pointer;
  }

  .remove-source:hover {
    border-color: #efd2ce;
    color: #a24e43;
    background: #fff7f6;
  }

  .empty-sources {
    margin: 0;
    padding: 1.25rem 0;
    color: #89958d;
    font-size: 0.8rem;
  }

  .ecosystem-guide {
    display: flex;
    align-items: flex-start;
    gap: 0.9rem;
    margin-top: 1.3rem;
    padding: 1rem 1.2rem;
    border: 1px solid #eee2e3;
    border-radius: 0.85rem;
    background: #faf7f7;
  }

  .guide-icon {
    display: grid;
    width: 1.8rem;
    flex: 0 0 auto;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 0.55rem;
    color: #bd1b2d;
    background: #fbe9eb;
  }

  .ecosystem-guide strong {
    display: block;
    margin-bottom: 0.25rem;
    color: #3e4044;
    font-size: 0.82rem;
  }

  .ecosystem-guide p {
    margin: 0;
    color: #748178;
    font-size: 0.74rem;
    line-height: 1.55;
  }

  code {
    color: #79575b;
    font-size: 0.93em;
  }

  @media (max-width: 840px) {
    .source-management {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 680px) {
    .admin-page {
      width: min(100% - 2rem, 76rem);
      padding-top: 2.4rem;
    }

    .admin-heading,
    .section-heading {
      align-items: flex-start;
      flex-direction: column;
    }

    .source-count {
      margin-top: -0.5rem;
    }

    .field-pair {
      grid-template-columns: 1fr;
    }

    .source-form-panel,
    .registry-panel {
      padding: 1.1rem;
    }
  }
</style>
