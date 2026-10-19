# Company → Bern Queries – Plan

Oct 18, 2026. Sits in front of the retriever: [collection_net_plan.md](collection_net_plan.md) collects Bern, this step works out what a company would ask about it.

## In one paragraph

We are given a company and almost nothing else: a name, a URL or a one-line idea. The pipeline reads what the company publishes about itself, writes a profile of what it does and what it wants (aspirations, goals, wants, challenges), maps that onto the 14 resource sections of the collection net (A people … M talent), and writes the questions the company would ask. For each question it writes search queries in the words Bern research pages use, in English and German. Output is a `queries.json` that `navigator retrieve` already reads; it is not connected yet.

## Pipeline

```
"Ypsomed" | https://… | "startup that …"
      │
 1 COLLECT ─► 2 PROFILE ─► 3 NEEDS ─► 4 QUERIES ─► data/companies/<slug>/queries.json
 public       does + wants   sections   EN + DE,
 pages        with quotes    A–M        researcher words
```

| # | Step | What happens | Apertus | Without LLM |
|---|---|---|---|---|
| 1 | Collect | **URL:** home page plus up to 7 pages chosen by link text: about, products, technology, sustainability, careers, news. **Name:** Wikidata gives website, industry, headquarters, staff, founding year; Wikipedia gives a summary; then as for a URL. If there is no Wikidata entry, try `<name>.ch` and `<name>.com`. **Idea:** the text itself. robots.txt obeyed, 1 s between requests. | No | Same |
| 2 | Profile | Summary, sector, stage, locations, in Bern or not; products, technologies, markets; **aspirations** (mission, vision), **goals** (plans, targets), **wants** (partners, talent, investors), **challenges**. Each list item carries a quote and its page. If the quote is not on the page, the item is dropped. | 1 call | Meta description, lexicon topics, sentences with mission, goal, hiring or problem words |
| 3 | Needs | Choose up to 8 sections that serve the goals. Each need has the need, the question in the company's voice, a basis (stated or inferred) and the profile item it builds on. | 1 call | Rules: A–D, G and K always; E or F when the topic has facilities or services; I for startups and SMEs; J when regulated; L when not in Bern; M when hiring |
| 4 | Queries | Per need: 3 English and 2 German queries, phrased like a sentence on a research page (not a question), plus 6–12 keywords in both languages. | 1 call per need | Templates filled with lexicon terms |

## Design choices

- **Queries read like pages, not questions.** The e5 index matches page-like text best, so "glucose sensor" becomes "continuous glucose monitoring and biosensing". The company's question is kept beside its queries for the answer step.
- **Two languages.** About half of UniBE pages are German.
- **One section per need.** Retrieval can later filter by record type (expert, unit, infrastructure, service …).
- **Coverage flag.** Our data covers UniBE, ARTORG and DCB. Sections I–L (funding, regulation, ecosystem, setting up) are only partly covered or not at all. We still write queries for them and flag them, so the gaps are visible.
- **Traceable.** A query leads to its need, the need to a profile item, and the profile item to a quote and URL on the company's own site.
- **Prompts for the 8B model.** Each call does one task and returns a small JSON object. The prompts live in [company/prompts.py](../src/navigator/company/prompts.py).

## Choosing the answers (no fixed top-N)

Raw e5 scores all fall between 0.86 and 0.90, and their level shifts from query to query. A threshold or a fixed top-N on them can't tell a clear answer from noise. [answers.py](../src/navigator/answers.py) picks results by the shape of the scores instead:

1. **z per query:** how many standard deviations a chunk lies above that query's mean over the whole index (about 54,000 chunks).
2. **Per question:** a page's score is its best z across the question's EN and DE queries. It gets +0.1 for each further query that found it. Translations and repeated listing excerpts count once.
3. **Soft diversity, no hard cap:** each page already taken from the same site costs the next one 0.15 z. A site that really holds the best answers still shows several.
4. **Dynamic cut:** the background is the median score of candidates ranked 10–30. A page is kept if it stands at least half as far above the background as the best page. One standout gives one result; a tight group of strong pages keeps them all.
5. **Confidence:** set by the best page's margin over the background. *Clear* is ≥ 0.6 z (at most 8 results), *moderate* is ≥ 0.3 (at most 5), and below that the output says "no clear answer in our data" and shows 3.

On Ypsomed this gives 2 to 5 results per question. The constants were set on that single run, so tune them on the bench.

Listing pages (category, tag, archive, `/page/N`) lose 0.03 from their raw score before the cut. That's roughly the whole score band.

Queries are written as page text, never as questions, with no "Bern" and no company names. Code removes any that slip through, so the model's output doesn't have to obey the prompt.

## Run

```bash
export PYTHONPATH=src            # plus LLM_NAME / LLM_BASE_URL / LLM_API_KEY for Apertus
python -m navigator company "Ypsomed"
python -m navigator company https://www.lindt-spruengli.com "startup that detects lameness in dairy cows with cameras"
python -m navigator retrieve data/companies/ypsomed/queries.json      # later: feed the queries to retrieval
```

Output per company in `data/companies/<slug>/`: `collect.json` (fetched text, trace), `profile.json`, `queries.json`, `report.md`.

## Next

1. Connect to retrieval. Measure the share of queries with at least one chunk above the threshold, per section and per language.
2. Build a test bench of about 10 companies: Bern and non-Bern; medtech, food, space, agri and software. The team rates each question as relevant or not.
3. Add a self-hosted SearXNG for names without a Wikidata entry. Per the technical plan, only the company name leaves our server.
4. Write the answer step: each question, its retrieved chunks and an Apertus answer with citations.
