import { useCallback, useEffect, useState } from "react";

const API = import.meta.env.VITE_NAVIGATOR_API_BASE || "/navigator-api";

async function readPayload(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function errorMessage(payload, fallback) {
  return typeof payload?.detail === "string" ? payload.detail : fallback;
}

export default function ResearchThemes() {
  const [result, setResult] = useState(null);
  const [batchSize, setBatchSize] = useState(50);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadClusters = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API}/clusters`);
      const payload = await readPayload(response);
      if (response.status === 404) {
        setResult(null);
        return;
      }
      if (!response.ok) {
        throw new Error(errorMessage(payload, `Could not load themes (HTTP ${response.status}).`));
      }
      setResult(payload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load themes.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadClusters();
  }, [loadClusters]);

  async function runClustering() {
    setError("");
    setNotice("");
    if (!Number.isInteger(batchSize) || batchSize < 1 || batchSize > 80) {
      setError("Choose a batch size from 1 to 80.");
      return;
    }
    setBusy(true);
    setNotice("Apertus is grouping the findings. This may take several minutes.");
    try {
      const response = await fetch(`${API}/clusters/run`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ batch_size: batchSize }),
      });
      const payload = await readPayload(response);
      if (!response.ok) {
        throw new Error(errorMessage(payload, `Clustering failed (HTTP ${response.status}).`));
      }
      setResult(payload);
      setNotice(`Clustered ${payload.finding_count} findings into ${payload.theme_count} themes.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Clustering failed.");
      setNotice("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="research-themes">
      <div className="themes-heading">
        <div>
          <p className="themes-eyebrow">Apertus research clustering</p>
          <h1>Research themes</h1>
          <p>
            Explore evidence-grounded themes across the focused research findings.
            Apertus proposes the themes and assigns every finding to exactly one group.
          </p>
        </div>
      </div>

      <section className="themes-run-panel" aria-labelledby="themes-run-title">
        <div>
          <p className="themes-eyebrow">Refresh the themes</p>
          <h2 id="themes-run-title">Cluster focused findings with Apertus</h2>
          <p>
            Requires a completed <code>focused-crawl</code> and an Apertus endpoint
            configured through <code>LLM_BASE_URL</code>.
          </p>
        </div>
        <div className="themes-controls">
          <label htmlFor="themes-batch-size">Findings per request</label>
          <input
            id="themes-batch-size"
            type="number"
            min="1"
            max="80"
            value={batchSize}
            onChange={(event) => setBatchSize(Number(event.target.value))}
          />
          <button type="button" onClick={runClustering} disabled={busy || loading}>
            {busy ? "Clustering…" : "Generate themes"}
          </button>
        </div>
      </section>

      {notice ? <p className="themes-feedback success" role="status">{notice}</p> : null}
      {error ? <p className="themes-feedback error" role="alert">{error}</p> : null}

      {result?.stale ? (
        <p className="themes-feedback warning" role="status">
          Findings changed since these themes were generated ({result.finding_count} clustered;
          {" "}{result.current_finding_count} currently stored). Generate themes again to refresh them.
        </p>
      ) : null}

      {loading ? (
        <p className="themes-empty" role="status">Loading saved themes…</p>
      ) : result ? (
        <>
          <div className="themes-summary">
            <span>{result.finding_count} findings</span>
            <span>{result.theme_count} themes</span>
            <span>{result.model}</span>
            <time dateTime={result.generated_at}>{new Date(result.generated_at).toLocaleString()}</time>
          </div>
          <section className="themes-list" aria-label="Research themes">
            {result.clusters.map((theme) => (
              <article className="themes-card" key={theme.id}>
                <div className="themes-card-heading">
                  <h2>{theme.name}</h2>
                  <span>{theme.finding_count} findings</span>
                </div>
                <p className="themes-description">{theme.description}</p>
                <details>
                  <summary>Show findings</summary>
                  <ul className="themes-findings">
                    {theme.findings.map((finding) => (
                      <li key={finding.id}>
                        <h3>{finding.title}</h3>
                        <p>{finding.summary}</p>
                        {finding.keywords?.length ? (
                          <p className="themes-keywords">{finding.keywords.join(" · ")}</p>
                        ) : null}
                        <div className="themes-source-list">
                          <span>{finding.organizations?.join(" · ") || finding.type}</span>
                          {(finding.source_urls || []).map((url) => (
                            <a href={url} target="_blank" rel="noopener noreferrer" key={url}>
                              Source ↗
                            </a>
                          ))}
                        </div>
                      </li>
                    ))}
                  </ul>
                </details>
              </article>
            ))}
          </section>
        </>
      ) : (
        <p className="themes-empty">
          No saved themes yet. Run <code>python -m navigator focused-crawl</code>,
          configure <code>LLM_BASE_URL</code> for Apertus, then generate themes here.
        </p>
      )}
    </main>
  );
}
