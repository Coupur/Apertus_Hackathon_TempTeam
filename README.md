# Hack Apertus Liebefeld — Research & Expertise Navigator, TempTeam

Template repository for [Hack Apertus](https://hackapertus.ch/) submissions.
Every project keeps the same layout, so organizers and judges find the same
things in the same place.

There are 3 challenges to pick from:
1. Bern Economic Development Agency: Research & Expertise Navigator
2. OpenParlData: Topic classification for Swiss parliaments with Apertus
3. University of Bern: Deciphering Archives with Apertus

Research institutions generate a considerable amount of valuable information about their people, expertise, research activities, technologies, infrastructures and services. However, this information is distributed across a large and heterogeneous landscape of institutional websites and platforms.

Submissions must use the v1.5 Apertus model family.
The submission must comply with the [HackApertus T&C](https://hackapertus.ch/terms-and-conditions).

## The Challenge

### Bern Economic Development Agency

### Research & Expertise Navigator

https://hackapertus.notion.site/liebefeld-challenges?p=fe5b4fec112a833daf9401a4771a7c12&pm=c

## 🔧 Resources & Tools

Check our resources & tools page for detailed information:
[https://hackapertus.notion.site/liebefeld-resources-tools](https://hackapertus.notion.site/liebefeld-resources-tools)

| Models           | URL                                      |
|------------------|------------------------------------------|
| Apertus v1.5 8B  | [huggingface.co/swiss-ai/Apertus-v1.5-8B](https://huggingface.co/swiss-ai/Apertus-v1.5-8B)  |
| Apertus v1.5 70B | [huggingface.co/swiss-ai/Apertus-v1.5-70B](https://huggingface.co/swiss-ai/Apertus-v1.5-70B) |

## The structure

The implemented focused collector uses local rules to maintain one working SQLite database, `data/focused.sqlite`, of up to 700 findings (research, technologies, infrastructure, experts and teams) from the supplied UniBE inventory, ARTORG, and Diabetes Center Berne. Collection, highlights and company reports use this same database. It requires no Apertus endpoint and marks candidates as unreviewed. Start with [the backend instructions](src/README.md) and [the focused workflow guide](Docs/Focused%20Crawler.md). Authored output is English; original names and evidence excerpts preserve source wording.

`company-report` accepts company JSON, selects focused findings by keyword overlap, reads their source pages as clean text, and asks Apertus to produce a report with citations. `--prepare-only` prepares the material without a model. The repository also contains separate legacy BM25/Apertus company search and embedding retrieval commands over a bulk page corpus. See the [implemented workflow comparison](src/README.md#implemented-workflows) for each command's inputs, matching method and output.

Keep the files and directories as shown below — don't rename or move them.

| Path | What it is |
| --- | --- |
| `README.md` | The challenge description and submission requirements |
| `technical_report.md` | The deeper write-up: architecture, evaluation, limitations |
| `LICENSE` | Apache-2.0 |
| `src/` | Your code |
| `Docs/unibe_sous_domaines_publics_etendus.xlsx` | The 42-site portal inventory, loaded automatically by both crawlers |

## Environment

- Include instructions for running the project in your technical report.
- Use the following environment variables:
```
LLM_NAME — name and version of the model
LLM_BASE_URL — endpoint base URL
LLM_API_KEY — your API key
```

## 📦 Submission Requirements & Deliverables

The submission must:
1. follow the template repo and include all prerequisite files and definitions
2. run end-to-end when judges try to run it

### Git repo (URL)
- Create your repo from this template (**Use this template**).
- Keep the layout as it is: don't rename or move its files.
- Set the repo to PUBLIC (Settings --> Collaborators --> Manage Visibility)
- Submit the URL of YOUR Git repo.

### Technical Report (pdf)
- Update [technical_report.md](technical_report.md) in this repository with all the details for your submission.
- Upload a pdf of your technical report to the root of the repo, named as `TeamName_Report.pdf`.
- Format: pdf, max. 6 pages w/o references
- Submit the pdf of the technical report.

### Demo video (URL)
- Max. 2 min demo video of your prototype
- Add the link to the **Demo** field at the top of [technical_report.md](technical_report.md)
- Submit the URL of the video.

## ⚖️ Judging Criteria

Each challenge has its own criteria, listed in its challenge description.

The main jury scores every submission on 6 dimensions (relevant for Top 6 teams):
1. **Purposeful use of AI**
2. **Technical rigour**
3. **Value, cost & scalability**
4. **Sovereign deployability**
5. **Implementation feasibility**
6. **Pitch & presentation**

Each dimension is scored from 0 to 5.

## Getting started

1. Click **Use this template** to create your own repository.

## TempTeam — company match layer (this repo)

Life-science company ingest → web enrich → **local Ollama LLM** (default
`qwen2.5:3b`; Apertus when `LLM_*` is set) → **collaboration potential %**
and P1–P4 priority for Bern outreach.

| | |
| --- | --- |
| Docs | [`src/company_match/README.md`](src/company_match/README.md) |
| UI | `http://127.0.0.1:5173` (Vite) |
| API | `http://127.0.0.1:8088` (`uvicorn company_match.api:app --app-dir src --port 8088`) |
| Env | copy [`.env.example`](.env.example) → `.env` |

Quick demo: start Ollama + API + UI, paste a company name or website, click
**Extract & prioritize**. Layer view shows the active model (e.g.
`ollama:qwen2.5:3b`), not Kimi.

## License

All Hack Apertus projects are open-sourced. Please check our Terms & Conditions for specific licensing details (6. What you build is open source): https://hackapertus.ch/terms-and-conditions

## Support

### FAQ
💡 https://hackapertus.ch/faq

### Contact

💬 In case you have questions, join the conversation on Discord. Alternatively, send an email to “hello@hackapertus.ch”.
