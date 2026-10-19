"""Prompts and resource sections for the company pipeline, kept together so they can be tuned.

Written for Apertus 8B: one task per call, a small JSON shape, and quotes copied from the pages.
"""

# The collection net's taxonomy (Docs/collection_net_plan.md §2) seen from the company's side.
# hint: what a Bern page for this section looks like, so queries can be phrased like one.
# coverage: how much of it our Bern data holds today (UniBE, ARTORG, DCB): yes | partial | no.
SECTIONS = {
    "A": {"name": "People and contact persons", "ask": "Who is the expert, who do we call?", "finds": "expert",
          "hint": "profile pages of professors and group leaders: name, function, research interests",
          "coverage": "yes"},
    "B": {"name": "Units", "ask": "Which institute, group, clinic or centre does this?", "finds": "unit",
          "hint": "home and about pages of institutes, departments, clinics, centres and research groups",
          "coverage": "yes"},
    "C": {"name": "Expertise, methods and technologies", "ask": "Does anyone work on the technology we use?",
          "finds": "expertise",
          "hint": "research focus sections naming methods, technologies, materials and disease areas",
          "coverage": "yes"},
    "D": {"name": "Projects and activities", "ask": "Has a group done something like our problem?", "finds": "project",
          "hint": "project pages: title, aim, duration, funding (SNSF, Innosuisse, EU), partners",
          "coverage": "yes"},
    "E": {"name": "Infrastructure and equipment", "ask": "Can we use an instrument, lab, biobank, cohort or HPC?",
          "finds": "infrastructure",
          "hint": "pages on instruments, labs, core facilities, platforms, biobanks, cohorts and computing, "
                  "with access for external users",
          "coverage": "yes"},
    "F": {"name": "Services for companies", "ask": "Who can test, analyse, run a clinical study or consult?",
          "finds": "service",
          "hint": "service pages: contract research, testing and analysis, clinical study support, consulting",
          "coverage": "yes"},
    "G": {"name": "Technology transfer and collaboration", "ask": "How do we license, co-develop or spin off?",
          "finds": "service",
          "hint": "technology transfer, licensing, industry cooperation, spin-off and innovation office pages",
          "coverage": "partial"},
    "H": {"name": "Publications and outputs", "ask": "Is there proof they are good at it?", "finds": "publication",
          "hint": "publication lists and abstracts", "coverage": "partial"},
    "I": {"name": "Funding and financial support", "ask": "What money is there for a joint project?",
          "finds": "funding",
          "hint": "pages on funding instruments: Innosuisse, SNSF, vouchers, grants for joint projects",
          "coverage": "partial"},
    "J": {"name": "Laws, regulation and authorities", "ask": "Which rules apply, who approves?",
          "finds": "regulation",
          "hint": "pages on regulation, approval, ethics committees, clinical trial rules and data protection",
          "coverage": "partial"},
    "K": {"name": "Ecosystem and partner organisations", "ask": "Who else is here to work with?",
          "finds": "organisation",
          "hint": "pages on partner hospitals (Insel Gruppe), companies, networks, clusters and innovation parks",
          "coverage": "partial"},
    "L": {"name": "Setting up in Bern", "ask": "Company registration, permits, tax relief, space?",
          "finds": "service",
          "hint": "pages on company settlement, permits, taxes and sites in the Canton of Bern", "coverage": "no"},
    "M": {"name": "Talent and education", "ask": "Can we hire or train people here?", "finds": "program",
          "hint": "study programmes, continuing education (CAS, DAS, MAS) and career services",
          "coverage": "partial"},
}

# One sentence per section as a Bern page would write it, from fields unrelated to most companies on
# purpose: the model should copy the style (a statement about a unit and what it offers), not the topic.
PAGE_EXAMPLES = {
    "A": "Professor of soil science; research interests: nitrogen cycling, soil microbiology, long-term field trials",
    "B": "The Institute of Geography studies climate, land use and natural hazards in mountain regions",
    "C": "Our group develops machine learning methods for segmentation and analysis of MRI images",
    "D": "Project: early detection of crop disease with drone imaging, funded by Innosuisse, with Agroscope",
    "E": "Core facility for electron microscopy, open to external users from academia and industry, booking and fees",
    "F": "Our lab offers contract analyses for companies: mass spectrometry, method validation and consulting",
    "G": "Technology transfer: licensing of inventions, patent applications and research agreements with industry",
    "H": "Selected publications on perovskite photovoltaic materials in Nature Energy and Advanced Materials",
    "I": "Innosuisse innovation projects fund joint work of a research partner and an implementation partner",
    "J": "Advice on the Human Research Act, ethics committee submissions and clinical trial authorisation",
    "K": "Industry partners and sponsors: the centre collaborates with Roche, Swisscom and the Insel Gruppe",
    "L": "Support for companies settling in the canton: permits, tax relief and help finding a site",
    "M": "Master's programme in Biomedical Engineering and a CAS in medical technology for professionals",
}

PROFILE_SYSTEM ="""You read what a company says about itself and write a factual profile for the
Bern Economic Development Agency. Use ONLY the given pages. Every list item needs a short quote
(5-25 words) copied word for word from one page, and the id of that page (P1, P2, ...).
Return JSON:
{"name": the company name,
 "summary": one sentence: what the company does and for whom,
 "sector": a short sector label, e.g. "MedTech - drug delivery devices",
 "stage": "startup" | "sme" | "corporate" | "unknown",
 "locations": [cities or countries where it has sites],
 "products":     [{"value": a product or service it sells, "quote": "...", "page": "P1"}],
 "technologies": [{"value": a technology, method, material or scientific field it relies on, "quote": "...", "page": "P1"}],
 "markets":      [{"value": customers, industries or regions it serves, "quote": "...", "page": "P1"}],
 "aspirations":  [{"value": its mission, vision or long-term ambition, "quote": "...", "page": "P1"}],
 "goals":        [{"value": a concrete plan or target: new product, expansion, market entry, sustainability target, "quote": "...", "page": "P1"}],
 "wants":        [{"value": something it says it is looking for: partners, talent, investors, pilot customers, suppliers, "quote": "...", "page": "P1"}],
 "challenges":   [{"value": a problem it solves or faces, "quote": "...", "page": "P1"}]}
At most 6 items per list. Leave a list empty when the pages say nothing about it. Do not guess."""

NEEDS_SYSTEM = """You advise a company on what the Bern research ecosystem can do for it: the University
of Bern (institutes, clinics and service units), the ARTORG Center for Biomedical Engineering Research
and the Diabetes Center Berne. You get the company profile and a list of resource sections.
Choose the sections that would most help this company reach its goals and solve its challenges,
most useful first, at most {max_needs}. A section may appear twice for two different needs.
Return JSON {{"needs": [{{
  "section": the section letter,
  "need": what the company needs from Bern, one sentence naming the concrete technology, product, disease, material or method,
  "question": the question a university website can answer (rules below),
  "basis": "stated" if a profile aspiration, goal, want or challenge says so, "inferred" if it follows from its products or sector,
  "evidence": the profile item it builds on, copied}}]}}
Rules for "question":
- Start with "Who", "Which" or "What". Ask who exists, what they do or what they offer.
- Never a yes/no question: no "Can we", "Do they have", "Is there".
- One thing per question: no "X and Y" or "X or Y" pairs; split them into two needs.
- Name the research field or service, not the company's product brand.
Examples:
  "Can we access a clinical trial facility to test our autoinjectors?" -> "Which Bern units run clinical studies for industry sponsors?"
  "Do institutes have labs to test user-friendliness and reliability?" -> "Which Bern groups offer usability testing of medical devices?"
  "Who are the other medtech companies in Bern?" -> "Which companies already sponsor or partner with University of Bern research in diabetes technology?"
Be concrete: not "innovation" or "research partners", but for what."""

QUESTION_FIX_SYSTEM = """Rewrite the question so that the public web pages of a university can answer it.
- Start with "Who", "Which" or "What". Ask who exists, what they do or what they offer.
- Not a yes/no question, and not "How can we": a website describes units and services, it does not decide.
- Ask exactly one thing: if the question pairs two things with "and" or "or", keep the more important one.
- Keep the topic and the place (Bern).
Example: "Can we hire or train device engineers through University of Bern programs?" ->
"Which University of Bern study programmes train medical device engineers?"
Reply with the rewritten question only, on one line."""

QUERIES_SYSTEM = """You write search queries for a semantic search engine over the public web pages of
University of Bern institutes, ARTORG and the Diabetes Center Berne, in English and German. Each query is
compared with page text, so it must read like a sentence ON the page that answers the need: the page
describing a unit, a person, a method, an instrument or a service, in its own words.
Rules for every query:
- A statement or noun phrase of 6-16 words. Never a question: no "Which", "Who", "What", "How", "Where",
  "Welche", "Wer", "Wie", "Wo", and no "?".
- Write what that page says about itself, in the style of the example you are given.
- No place names and no names: not "Bern", "Berner", "University of Bern", not the company or its brands,
  not "we", "our", "companies like ours". Every page in the index is in Bern already.
- One idea per query. Across the queries vary the words: technical term, synonym, abbreviation, broader field.
- Translate the company's words into research words ("glucose sensor" -> "continuous glucose monitoring",
  "biosensing"; "user-friendliness" -> "usability", "human factors").
- German: use the words German university pages use, and avoid words with a second common meaning:
  "Prüfung" also means exam, so write "klinische Studie", "Testung" or "Evaluation".
Return JSON:
{"en": [3 English queries], "de": [2 German queries],
 "keywords": [6-12 keywords: technical terms, synonyms and abbreviations, in English and German]}"""


def sections_text(letters=SECTIONS) -> str:
    return "\n".join(f"{k} {SECTIONS[k]['name']}: {SECTIONS[k]['ask']}" for k in letters)


def profile_text(p: dict) -> str:
    """The profile as the short plain text the needs prompt reads."""
    lines = [f"Company: {p['name']} ({p.get('website') or 'no website'})",
             f"Summary: {p.get('summary', '')}",
             f"Sector: {p.get('sector', '')}. Stage: {p.get('stage', 'unknown')}. "
             f"Locations: {', '.join(p.get('locations', [])) or 'unknown'}. "
             f"In Bern: {({True: 'yes', False: 'no'}).get(p.get('in_bern'), 'unknown')}"]
    for field in ("products", "technologies", "markets", "aspirations", "goals", "wants", "challenges"):
        items = p.get(field, [])
        if items:
            lines.append(f"{field.capitalize()}: " + "; ".join(i["value"] for i in items))
    return "\n".join(lines)


def need_text(p: dict, n: dict) -> str:
    s = SECTIONS[n["section"]]
    return (f"Company: {p.get('summary', '')} (sector: {p.get('sector', '')})\n"
            f"Need (section {n['section']}, {s['name']}): {n['need']}\n"
            f"Company question: {n['question']}\n"
            f"Pages that answer it: {s['hint']}\n"
            f"Style of such a page (other topic, copy only the style): \"{PAGE_EXAMPLES[n['section']]}\"")
