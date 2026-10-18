import { useEffect, useMemo, useRef, useState } from "react";

const API = import.meta.env.VITE_API_BASE || "/api";

const SAMPLE_TEXT = `Company Name: Helix Glucose AG
Headquarters: Zurich, Switzerland
Website: https://www.example-helix-glucose.ch

Helix Glucose develops wearable continuous glucose monitoring (CGM) sensors
and biosensing patches for people with diabetes. Looking for clinical validation
partners and university collaboration in Switzerland.

---

Company Name: Alpine Surgical Systems
Based in: Munich, Germany

Alpine Surgical Systems builds computer-assisted surgical navigation and
robotic surgery tooling. Needs hospital partnership and biomedical engineering
co-development.`;

function ChipList({ items, kind, scored }) {
  const list = scored?.length
    ? scored
    : (items || []).map((term) => ({ term, relevance: null, count: null }));
  if (!list.length) return <span className="empty">None detected</span>;
  return (
    <div className="chips">
      {list.map((k) => {
        const term = k.term || k;
        const rel = k.relevance;
        const count = k.count;
        return (
          <span key={`${kind}-${term}`} className={`chip ${kind || ""}`} title={k.cluster_label || ""}>
            {term}
            {rel != null ? (
              <em className="chip-score">
                {Math.round(rel)}%{count != null ? ` · n=${count}` : ""}
              </em>
            ) : null}
          </span>
        );
      })}
    </div>
  );
}

const PROFILE_FIELDS = [
  ["therapeutic_areas", "Therapeutic areas"],
  ["indications", "Indications"],
  ["modalities_technologies", "Modalities / technologies"],
  ["products_platforms", "Products / platforms"],
  ["patient_populations", "Patient populations"],
  ["development_activities", "Development / clinical activity"],
];

function EvidenceChips({ items }) {
  if (!items || !items.length) return <span className="empty">Not stated in source</span>;
  return (
    <div className="chips">
      {items.map((it) => (
        <span key={it.term} className="chip" title={`Source: “${it.evidence}”`}>
          {it.term}
        </span>
      ))}
    </div>
  );
}

function MedicalProfile({ profile }) {
  if (!profile) return null;
  const suff = profile.information_sufficiency || "limited";
  return (
    <>
      <h3>
        Medical profile{" "}
        <span className={`pill ${suff === "sufficient" ? "p1" : suff === "insufficient" ? "out" : ""}`}>
          source info: {suff}
        </span>{" "}
        <span className="pill">{profile.model}</span>
      </h3>
      <dl className="kv">
        {profile.business_model ? (
          <div>
            <dt>Business model</dt>
            <dd title={`Source: “${profile.business_model.evidence}”`}>{profile.business_model.value}</dd>
          </div>
        ) : null}
        {PROFILE_FIELDS.map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>
              <EvidenceChips items={profile[key]} />
            </dd>
          </div>
        ))}
        {(profile.partnership_needs || []).length > 0 && (
          <div>
            <dt>Stated needs</dt>
            <dd>
              <EvidenceChips
                items={profile.partnership_needs.map((n) => ({ term: n.need, evidence: n.evidence }))}
              />
            </dd>
          </div>
        )}
        {(profile.missing_information || []).length > 0 && (
          <div>
            <dt>Not in source</dt>
            <dd>{profile.missing_information.join(" · ")}</dd>
          </div>
        )}
      </dl>
      <p className="empty" style={{ fontSize: "0.8rem" }}>
        Hover a term to see the verbatim source quote. Items without a verifiable quote are
        dropped{(profile.dropped_unsupported || []).length
          ? ` (${profile.dropped_unsupported.length} dropped)`
          : ""}.
      </p>
    </>
  );
}

const HQ_LABELS = {
  source: "stated in source",
  json_ld: "website structured data",
  llm_quote: "quoted from source (LLM)",
  footer: "website footer address",
  imprint: "imprint / contact page",
  wikidata: "Wikidata",
  llm_knowledge: "model knowledge — UNVERIFIED",
  domain_hint: "domain hint only",
};

function LocationSource({ src }) {
  if (!src || src.method === "none") return null;
  const label = HQ_LABELS[src.method] || src.method;
  return (
    <div style={{ fontSize: "0.8rem", marginTop: "0.2rem" }}>
      <span className={`pill ${src.verified ? "p1" : "out"}`} title={src.evidence || ""}>
        via {label}
      </span>{" "}
      {src.url ? (
        <a href={src.url} target="_blank" rel="noreferrer">
          source
        </a>
      ) : null}
    </div>
  );
}

function PipelineNotes({ notes, profile }) {
  if (profile || !notes || !notes.length) return null;
  // Collapse noisy Ollama 402 credit dumps into one short line
  const cleaned = notes.map((n) => {
    if (/402|usage credits|not included in your free/i.test(n)) {
      return "Cloud LLM needs credits — using free local Ollama model or web/rules fallback.";
    }
    if (/no valid JSON/i.test(n)) {
      return "LLM JSON profile incomplete — showing web/rules summary.";
    }
    if (n.length > 160) return `${n.slice(0, 157)}…`;
    return n;
  });
  const uniq = [...new Set(cleaned)];
  return (
    <div style={{ color: "var(--muted)", fontSize: "0.85rem", margin: "0.5rem 0" }}>
      Note: {uniq.join(" · ")}
    </div>
  );
}

function CompanyCard({ card }) {
  if (!card) return null;
  const info = card.main_info || {};
  const kw = card.keywords || {};
  const prio = card.priority || {};
  const match = card.match || {};
  const layer = card.teammate_layer || {};

  return (
    <article className="card">
      <div className="card-head">
        <div>
          <div className="badge-row" style={{ marginBottom: "0.45rem" }}>
            <span className={`pill ${(prio.rating || "p4").toLowerCase()}`}>
              {prio.rating || "—"} / {prio.stage || "—"}
            </span>
            <span className={`pill ${card.in_scope ? "p1" : "out"}`}>
              {card.in_scope ? "Life science" : "Out of scope"}
            </span>
            <span className="pill">{card.source_type}</span>
            <span className="pill">
              lang {(info.source_language || "en").toUpperCase()}
              {info.translated_to_english ? " → EN" : ""}
            </span>
            <span className={`pill ${info.summary_method && info.summary_method !== "rules" ? "p1" : ""}`}>
              summary {info.summary_method || "rules"}
            </span>
          </div>
          <h2>{card.company_name}</h2>
        </div>
        <div className="rates">
          <div className="rate">
            <b>{match.match_rate ?? "—"}%</b>
            <span>Collaboration potential</span>
          </div>
          <div className="rate">
            <b>{prio.rating || "—"}</b>
            <span>Priority {prio.score != null ? `(${prio.score})` : ""}</span>
          </div>
        </div>
      </div>

      {(match.verdict_label || match.tier) && (
        <p className={`verdict verdict-${match.verdict || "possible"}`}>
          <strong>Judge:</strong> {match.verdict_label || match.tier}
        </p>
      )}

      <h3>Main information collected</h3>
      <dl className="kv">
        <div>
          <dt>Sector</dt>
          <dd>
            {info.sector || "—"}
            {info.subsector ? ` / ${info.subsector}` : ""}
          </dd>
        </div>
        <div>
          <dt>Location</dt>
          <dd>
            {[info.hq_city, info.hq_country].filter(Boolean).join(", ") || "—"}
            {info.canton_bern_presence ? " · Canton of Bern" : ""}
            <LocationSource src={info.hq_source} />
          </dd>
        </div>
        <div>
          <dt>Website</dt>
          <dd>
            {info.website ? (
              <a href={info.website} target="_blank" rel="noreferrer">
                {info.website}
              </a>
            ) : (
              "—"
            )}
          </dd>
        </div>
        <div>
          <dt>Needs</dt>
          <dd>{(info.needs || []).join(", ") || "—"}</dd>
        </div>
        <div>
          <dt>What they do</dt>
          <dd>{info.what_they_do || card.semantics?.activity_summary || "—"}</dd>
        </div>
        <div>
          <dt>Medical summary</dt>
          <dd>
            {info.description || info.meta_description || "—"}
            {info.description &&
            /select your region|benelux|asia pacific/i.test(info.description) ? (
              <div style={{ color: "var(--danger)", marginTop: "0.35rem", fontSize: "0.85rem" }}>
                Warning: summary still looks like a region gateway — restart API / retry.
              </div>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>Language</dt>
          <dd>
            {(() => {
              const lang = (info.source_language || "unknown").toUpperCase();
              if (info.translated_to_english) {
                return `${lang} → English (${info.translation_method || "translated"})`;
              }
              if (lang === "EN") {
                return "EN (source already English)";
              }
              return `${lang} (translation bridge partial — check Apertus / translator)`;
            })()}
          </dd>
        </div>
        {info.original_excerpt && info.translated_to_english ? (
          <div>
            <dt>Original</dt>
            <dd>{info.original_excerpt}</dd>
          </div>
        ) : null}
        <div>
          <dt>Source</dt>
          <dd>{card.source_ref || "—"}</dd>
        </div>
      </dl>

      <PipelineNotes notes={info.pipeline_notes} profile={info.medical_profile} />
      <MedicalProfile profile={info.medical_profile} />

      {(card.semantics?.focus_clusters || []).length > 0 && (
        <>
          <h3>Focus understanding (semantic clusters)</h3>
          <div className="chips">
            {card.semantics.focus_clusters.map((c) => (
              <span key={c.id} className={`chip ${c.stage === "early" ? "early" : c.stage === "mid" ? "mid" : "late"}`}>
                {c.label}
                <em className="chip-score">
                  {Math.round(c.relevance)}% · n={c.count}
                </em>
              </span>
            ))}
          </div>
        </>
      )}

      <h3>Front keywords (highest relevance)</h3>
      <ChipList items={kw.early} scored={kw.early_relevance} kind="early" />
      <h3>Supporting keywords</h3>
      <ChipList items={kw.mid} scored={kw.mid_relevance} kind="mid" />
      <h3>Peripheral keywords</h3>
      <ChipList items={kw.late} scored={kw.late_relevance} kind="late" />

      <div className="layer-box">
        <strong>Teammate handoff layer</strong>
        <p style={{ margin: "0.35rem 0 0", color: "var(--muted)", fontSize: "0.92rem" }}>
          {prio.handoff_note || "Ordered queries for the expertise navigator."}
        </p>
        <h3 style={{ marginTop: "0.8rem" }}>Run first</h3>
        <ChipList items={layer.run_first} kind="early" />
        <h3>Run later</h3>
        <ChipList items={layer.run_later} kind="late" />
        {(match.bern_units || []).length > 0 && (
          <>
            <h3>Bern units to match</h3>
            <ChipList items={match.bern_units} />
          </>
        )}
      </div>

      {(match.score_breakdown && Object.keys(match.score_breakdown).length > 0) && (
        <>
          <h3>Collaboration score breakdown</h3>
          <dl className="kv">
            <div>
              <dt>Potential</dt>
              <dd>{match.score_breakdown.match_rate ?? match.match_rate}%</dd>
            </div>
            {Object.entries(match.score_breakdown.components || {}).map(([k, v]) => (
              <div key={k}>
                <dt>{k.replace(/_/g, " ")}</dt>
                <dd>
                  {v} / {(match.score_breakdown.component_max || {})[k] ?? "—"}
                </dd>
              </div>
            ))}
            <div>
              <dt>Capability hits</dt>
              <dd>
                {(match.score_breakdown.capability_hits || [])
                  .map((h) => `${h.name} (${h.score})`)
                  .join(" · ") || "—"}
              </dd>
            </div>
          </dl>
        </>
      )}

      {(match.bern_matches || []).length > 0 && (
        <>
          <h3>Matched Bern experts / units (verified sources)</h3>
          <ol className="reasons">
            {match.bern_matches.slice(0, 6).map((r) => (
              <li key={r.record_id}>
                <strong>{r.name}</strong>
                {r.role ? ` — ${r.role}` : ""}
                {r.unit ? `, ${r.unit}` : ""}
                {r.institution ? ` (${r.institution})` : ""} · score {r.score}
                <br />
                <small>matched: {(r.matched_terms || []).join(", ")}</small>{" "}
                <a href={r.source_url} target="_blank" rel="noreferrer">
                  source
                </a>
              </li>
            ))}
          </ol>
        </>
      )}

      {(match.reasons || []).length > 0 && (
        <>
          <h3>Why this match</h3>
          <ol className="reasons">
            {match.reasons.slice(0, 10).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ol>
        </>
      )}
    </article>
  );
}

export default function App() {
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [deepLlm, setDeepLlm] = useState(false);
  const [files, setFiles] = useState([]);
  const [translate, setTranslate] = useState(true);
  const [indexQdrant, setIndexQdrant] = useState(false);
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [selected, setSelected] = useState(0);
  const abortRef = useRef(null);
  const refineRef = useRef(null);
  const [refining, setRefining] = useState(false);
  const [aiRefine, setAiRefine] = useState(true);

  const cards = result?.cards || [];
  const active = cards[selected] || null;

  useEffect(() => {
    if (!loading) {
      setElapsed(0);
      return undefined;
    }
    const t0 = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 250);
    return () => clearInterval(id);
  }, [loading]);

  const pipeline = useMemo(() => result?.pipeline || [
    { id: "ingest", label: "Ingest", detail: "PDF / text / website (any language)" },
    { id: "translate", label: "Translate", detail: "→ English (bridge / Apertus)" },
    { id: "web", label: "Web enrich", detail: "Search by company name → context + keywords" },
    { id: "llm", label: "LLM summary", detail: "ollama:qwen2.5:3b (local) on page/search context" },
    { id: "extract", label: "Extract", detail: "Name, sector, keywords, needs" },
    { id: "priority", label: "Prioritize", detail: "Semantic frequency → early front" },
    { id: "match", label: "Match", detail: "Collaboration potential % + judge verdict" },
    { id: "qdrant", label: "Qdrant", detail: "Later-stage vector index" },
    { id: "handoff", label: "Handoff", detail: "Queries for navigator teammate" },
  ], [result]);

  async function analyze(e) {
    e?.preventDefault?.();
    setError("");
    setResult(null);
    setLoading(true);

    let textIn = text.trim();
    let urlIn = url.trim();
    // If the URL was pasted into the text box, treat it as a website
    const looksLikeUrl = /^(https?:\/\/)?([\w-]+\.)+[\w-]{2,}(\/.*)?$/i.test(textIn)
      && !/\s/.test(textIn)
      && textIn.length < 200;
    if (!urlIn && looksLikeUrl) {
      urlIn = /^https?:\/\//i.test(textIn) ? textIn : `https://${textIn}`;
      textIn = "";
    } else if (urlIn && !/^https?:\/\//i.test(urlIn)) {
      urlIn = `https://${urlIn}`;
    }

    if (!textIn && !urlIn && files.length === 0) {
      setError("Add a company name, website URL, or file — then click Extract & prioritize.");
      setLoading(false);
      return;
    }

    abortRef.current?.abort();
    refineRef.current?.abort();
    setRefining(false);
    const controller = new AbortController();
    abortRef.current = controller;

    const buildForm = (mode) => {
      const form = new FormData();
      if (textIn) form.append("text", textIn);
      if (urlIn) form.append("urls", urlIn);
      for (const f of files) form.append("files", f);
      form.append("write_handoff", mode === "off" ? "false" : "true");
      form.append("translate", translate ? "true" : "false");
      form.append("index_qdrant", indexQdrant && mode !== "off" ? "true" : "false");
      form.append("llm_mode", mode);
      return form;
    };
    const post = async (mode, signal) => {
      const res = await fetch(`${API}/ui/analyze`, { method: "POST", body: buildForm(mode), signal });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Request failed (${res.status})`);
      }
      return res.json();
    };

    // Step 1 — instant result (no LLM): rules + verified sources, a few seconds
    const timer = setTimeout(() => controller.abort(), 30000);
    let firstOk = false;
    try {
      const data = await post("off", controller.signal);
      if (!data?.cards?.length) {
        throw new Error(
          data?.detail
            || "No company extracted from that website. Try the company name in the text box, or another URL."
        );
      }
      setResult(data);
      setSelected(0);
      firstOk = true;
    } catch (err) {
      setError(
        err?.name === "AbortError"
          ? "The website did not answer within 30s. Try again, or paste the company name / a short description."
          : err.message || String(err)
      );
    } finally {
      clearTimeout(timer);
      setLoading(false);
    }
    if (!firstOk || !aiRefine) return;

    // Step 2 — AI refinement in the background; the card is replaced when it arrives
    const refine = new AbortController();
    refineRef.current = refine;
    const refineTimer = setTimeout(() => refine.abort(), deepLlm ? 175000 : 30000);
    setRefining(true);
    try {
      const better = await post(deepLlm ? "deep" : "lite", refine.signal);
      if (better?.cards?.length) setResult(better);
    } catch (err) {
      if (err?.name !== "AbortError") console.warn("AI refinement failed", err);
    } finally {
      clearTimeout(refineTimer);
      if (refineRef.current === refine) setRefining(false);
    }
  }

  function loadSample() {
    setText(SAMPLE_TEXT);
    setUrl("");
    setFiles([]);
  }

  function onFiles(ev) {
    setFiles(Array.from(ev.target.files || []));
  }

  return (
    <div className="app">
      <header className="hero">
        <p className="badge-row">
          <span className="badge">Canton of Bern</span>
          <span className="badge">Life science only</span>
          <span className="badge">Company layer</span>
        </p>
        <h1 className="brand">Company intelligence layer</h1>
        <p className="lede">
          Drop a company PDF, paste text, or add a website. See what keywords and
          main fields are extracted, how they are prioritized, and what your
          navigator teammate should run first.
        </p>
      </header>

      <div className="layout">
        <section className="panel">
          <h2>Input</h2>
          <form onSubmit={analyze}>
            <label htmlFor="text">Plain text (one or several companies)</label>
            <textarea
              id="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Company name alone works (e.g. Mindray) — we web-search then LLM.&#10;Or paste a blurb / use URL / PDF."
            />

            <h3>Website</h3>
            <label htmlFor="url">Public company page URL</label>
            <input
              id="url"
              type="text"
              inputMode="url"
              autoComplete="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.novartis.com or novartis.com"
            />

            <h3>PDF or text file</h3>
            <div className="file-box">
              <input
                type="file"
                accept=".pdf,.txt,.md,.json,application/pdf,text/plain"
                multiple
                onChange={onFiles}
              />
              <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
                {files.length
                  ? files.map((f) => f.name).join(", ")
                  : "Optional — upload pitch decks or notes"}
              </span>
            </div>

            <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.85rem" }}>
              <input
                type="checkbox"
                checked={translate}
                onChange={(e) => setTranslate(e.target.checked)}
              />
              Translate any language → English before extraction
            </label>
            <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.45rem" }}>
              <input
                type="checkbox"
                checked={indexQdrant}
                onChange={(e) => setIndexQdrant(e.target.checked)}
              />
              Index into Qdrant (later-stage vector matching)
            </label>
            <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.45rem" }}>
              <input
                type="checkbox"
                checked={aiRefine}
                onChange={(e) => setAiRefine(e.target.checked)}
              />
              Refine with AI in the background (instant result first)
            </label>
            <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.45rem" }}>
              <input
                type="checkbox"
                disabled={!aiRefine}
                checked={deepLlm}
                onChange={(e) => setDeepLlm(e.target.checked)}
              />
              Deep LLM profile (slower — structured medical JSON)
            </label>

            <div className="actions">
              <button type="submit" disabled={loading}>
                {loading ? `Analyzing… ${elapsed}s` : "Extract & prioritize"}
              </button>
              <button type="button" className="secondary" onClick={loadSample}>
                Load sample
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  setText(
                    "Firmenname: Helix Glukose AG\nHauptsitz: Zürich, Schweiz\n\nWir entwickeln kontinuierliche Glukosemessung (CGM), Blutzuckersensoren und Biosensorik für Diabetes. Wir suchen klinische Studien und Universitätskooperationen."
                  )
                }
              >
                DE sample
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  setText(
                    "会社名：アークレイ株式会社（ARKRAY, Inc.）\n本社：京都府京都市\nウェブサイト：https://www.arkray.co.jp/\n\nアークレイは、血糖自己測定、糖尿病検査、バイオセンサー、臨床検査機器を手がける日本の医療機器メーカーです。血糖センサーや糖尿病関連の診断技術に強みがあり、連続的な血糖モニタリングにも取り組んでいます。スイスの大学・糖尿病研究センターとの共同研究を希望します。"
                  )
                }
              >
                JP sample
              </button>
            </div>
            {error ? <p className="error">{error}</p> : null}
          </form>
        </section>

        <section className="panel">
          <h2>Layer view</h2>

          <div className="pipeline">
            {pipeline.map((step, idx) => (
              <div
                key={step.id}
                className={`pipe-step ${result ? "active" : ""}`}
                style={{ animationDelay: `${idx * 40}ms` }}
              >
                <strong>{step.label}</strong>
                <span>{step.detail}</span>
              </div>
            ))}
          </div>

          {loading && (
            <div className="loading-panel" role="status">
              <strong>Working on your input… {elapsed}s</strong>
              <p>
                Website fetch + Wikipedia enrich usually takes <b>10–30s</b>.
                Keep this tab open — results appear here when ready.
                {elapsed >= 20 ? " Still going (large sites are slower)." : ""}
              </p>
            </div>
          )}

          {!result && !loading && (
            <p className="empty">
              Results appear here after you click <b>Extract & prioritize</b>.
              Paste a URL in Website (or a company name in text), then click the button.
            </p>
          )}

          {result && (
            <>
              <div className="badge-row" style={{ marginBottom: "0.85rem" }}>
                {refining ? (
                  <span className="badge" role="status">Refining with AI…</span>
                ) : result.timings?.llm_mode === "off" ? (
                  <span className="badge">instant (rules + verified sources)</span>
                ) : (
                  <span className="badge">AI-refined</span>
                )}
                <span className="badge">{result.domain_label} domain</span>
                <span className="badge">{result.company_count} compan(y/ies)</span>
                <span className="badge">{result.in_scope_count} in scope</span>
                {result.qdrant_index && !result.qdrant_index.error ? (
                  <span className="badge">
                    Qdrant +{result.qdrant_index.indexed} ({result.qdrant_index.embedder})
                  </span>
                ) : null}
                {result.qdrant_index?.error ? (
                  <span className="badge">Qdrant error</span>
                ) : null}
                {result.timings?.total_s != null ? (
                  <span
                    className="badge"
                    title={Object.entries(result.timings.steps_s || {})
                      .map(([k, v]) => `${k}: ${v}s`)
                      .join(" · ")}
                  >
                    {result.timings.total_s}s
                    {Object.keys(result.timings.steps_s || {}).length
                      ? ` (${Object.entries(result.timings.steps_s)
                          .map(([k, v]) => `${k} ${Math.round(v)}s`)
                          .join(", ")})`
                      : ""}
                  </span>
                ) : null}
              </div>
              {(result.timings?.notes || []).length > 0 && (
                <div className="empty" style={{ fontSize: "0.8rem", marginBottom: "0.6rem" }}>
                  {result.timings.notes.join(" · ")}
                </div>
              )}

              <h3>Priority queue</h3>
              <div className="queue">
                {cards.map((card, idx) => (
                  <button
                    key={`${card.company_name}-${idx}`}
                    type="button"
                    className={`queue-item ${selected === idx ? "selected" : ""}`}
                    onClick={() => setSelected(idx)}
                  >
                    <span className="pos">#{card.queue_position || idx + 1}</span>
                    <span>
                      <strong>{card.company_name}</strong>
                      <div className="meta">
                        {(card.priority || {}).rating} · {(card.priority || {}).stage} ·{" "}
                        {(card.match || {}).match_rate}% potential · {(card.priority || {}).rating || "—"}
                      </div>
                    </span>
                    <span className={`pill ${((card.priority || {}).rating || "p4").toLowerCase()}`}>
                      {(card.priority || {}).rating || "—"}
                    </span>
                  </button>
                ))}
              </div>

              <CompanyCard card={active} />
            </>
          )}
        </section>
      </div>
    </div>
  );
}
