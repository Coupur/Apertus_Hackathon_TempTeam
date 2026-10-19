"""Conservative, source-local people/team links and deterministic separate scoring.

Only explicit role labels or named grammatical subjects establish a link. A
directory, contact person, shared page, professor title or host is not a role.
"""
import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from .keywords import record_keywords
from .privacy import clean_text, has_contact
from .ranking import FUTURE, NEGATED, METHOD, MEASURE, OUTCOME, has, sentence_scores
from .rules import COLLECTION_TITLE

ENTITY_VERSION = "entities-v2"
ENTITY_WEIGHTS = {"contribution": 25, "expertise": 15, "results": 25,
                  "application": 15, "recognition": 5, "collaboration": 15}
ENTITY_TYPES = {"expert", "team"}
ROLE = r"principal investigator|project (?:leader|lead|coordinator|team|member|partner)|programme? (?:leader|coordinator)|co-investigator|investigator|sponsor|phd student|doctoral (?:student|researcher)|research (?:team|group)|researchers?|group leader|scientific (?:lead|coordinator)|work.?package (?:leader|lead)|projektleit(?:er|ung)|projekt ?team|projektmitarbeit\w*|forschungsgruppe|studienleit(?:er|ung)|doktorand"
ROLE_LINE = re.compile(r"^(?P<role>" + ROLE + r")\s*:\s*(?P<names>.+)$", re.I)
ROLE_HEADING = re.compile(r"^(?:" + ROLE + r"|project members|project participants|projektbeteiligte|team members)\s*:?$", re.I)
HONORIFIC = re.compile(r"^(?:(?:Prof(?:essor)?|Dr|PD|med|rer|nat|phil)\.?\s+)+", re.I)
NAME = re.compile(r"[A-ZÀ-ÖØ-Þ][\wÀ-ÿ’'\-]+(?:\s+(?:[A-ZÀ-ÖØ-Þ][\wÀ-ÿ’'\-]+|von|van|de|del|der)){1,5}")
TEAM = re.compile(r"\b((?:[A-Z][\w’'()\-]*|on|in|of|for|and|the)(?:[ -]+(?:[A-Z][\w’'()\-]*|on|in|of|for|and|the)){0,10}[ -]+(?:[Gg]roup|[Tt]eam|Laboratory|Lab|Consortium))\b")


def profile_identity(url: str) -> str:
    parts = urlsplit(url)
    path = re.sub(r"/index_(?:eng|ger|fra)\.html$", "/", parts.path)
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))


def person_name(value: str) -> str:
    value = HONORIFIC.sub("", value.strip())
    value = re.split(r"\s+[–—|]|,|\s+\(|\s+-\s+", value)[0].strip()
    value = re.sub(r"\s+(?:PhD|MD|MSc|BSc)$", "", value).strip()
    subject_labels = record_keywords({'original_name': value, 'evidence': []})
    if (NAME.fullmatch(value) and value.casefold() not in {label.casefold() for label in subject_labels}
            and not re.search(r"University|Department|Institute|Center|Centre|Research|Group|Project|Chief|Professor|\b(?:Digital|Technologies|Solutions|Corporation|Company|GmbH|AG|Inc)\b", value)):
        return value
    return ""


def contribution(role: str) -> int:
    if has(r"principal investigator|project (?:leader|lead|coordinator)|programme? (?:leader|coordinator)|projektleit|studienleit", role):
        return 4
    if has(r"work.?package (?:leader|lead)|scientific (?:lead|coordinator)|direction lead|group leader", role):
        return 3
    if has(r"developed|designed|analysed|analyzed|conducted|conducts|investigated|develops|investigates|studies|advances|operates|serves|entwickelt|untersucht", role):
        return 2
    if has(ROLE + r"|participant|member|beteiligt", role):
        return 1
    return 0


def eligible_link(link: dict) -> bool:
    return bool(link.get("work_id") and link.get("accepted_work") and link.get("quote")
                and link.get("source_url") and contribution(link.get("role", "")))


TECHNIQUE = (METHOD + r"|sequencing|RNA.Seq|proteomics|genomics|epigenetic|DNA methylation"
             r"|echocardiograph\w*|hemodynamic\w*|imaging|image analysis|machine learning"
             r"|computational model\w*|statistical method\w*|prognostic model\w*|digital twins?"
             r"|evidence synthesis|meta.analysis|epidemiolog\w* stud\w*|population.based"
             r"|prospective|retrospective|cohort|randomi[sz]ed|surveys?|questionnaires?"
             r"|in.vitro|in.vivo|animal model\w*|microengineer\w*|molecular diagnostic\w*")
ACTIVITY = (r"\b(?:investigat\w*|studies|study|research\w*|focus\w*|explor\w*|examines?|develop\w*|design\w*|analys\w*|analyz\w*"
            r"|uses?|using|employ\w*|combin\w*|conduct\w*|operat\w*|offers?|provid\w*|speciali[sz]\w*|validat\w*|replicat\w*"
            r"|untersucht|entwickelt|erforscht|verwendet)\b")
COMPLETED_RESULT = (r"^(?:(?:has|have)\s+)?(?:showed|shown|demonstrated|developed|designed|built|found|"
                    r"achieved|published|conducted|validated|independently replicat\w*|"
                    r"independently reproduc\w*|entwickelt|zeigte|nachgewiesen)\b")


def attributed_statements(name: str, kind: str, evidence: dict, *, own_page=False):
    """Yield subject-local assertions with verbatim context for pronouns.

    A mention is not a subject. Pronouns cannot jump across paragraphs or a
    different subject. Only a named team's own detail page licenses first-person
    prose without a preceding full-name assertion.
    """
    text = evidence['quote']
    named = re.compile(r"^(?:the\s+)?" + re.escape(name) + r"(?![\w'’])(?:\s*\([^)]+\))?\s+", re.I)
    acronym_match = re.search(r"\(([A-Z]{2,8})\)|\b([A-Z]{2,8})$", name)
    acronym = next((v for v in acronym_match.groups() if v), '') if acronym_match else ''
    team_subject = r"(?:we|our (?:research group|group|lab|laboratory|research|team)|the (?:research group|group|lab|team))"
    if acronym:
        team_subject += r"|the " + re.escape(acronym)
    continuation = re.compile(r"^(?:" + (team_subject if kind == 'team' else r"he|she|his research|her research") + r")\s+", re.I)
    for paragraph in re.finditer(r"[^\n]+", text):
        start = None
        for match in re.finditer(r".*?(?:[.!?](?=\s+[A-ZÄÖÜ]|$)|$)", paragraph[0]):
            raw = match[0]
            if not raw.strip():
                continue
            sentence = HONORIFIC.sub('', raw.strip())
            explicit = named.match(sentence)
            pronoun = continuation.match(sentence)
            if explicit:
                start = paragraph.start() + match.start() + len(raw) - len(raw.lstrip())
                subject = explicit
            elif pronoun and (start is not None or (own_page and kind == 'team')):
                if start is None:
                    start = paragraph.start() + match.start() + len(raw) - len(raw.lstrip())
                subject = pronoun
            else:
                start = None
                continue
            body = sentence[subject.end():]
            if kind == 'expert' and has(r"^(?:research\s+)?(?:group|lab|laboratory|team)\b", body):
                start = None
                continue
            # A relative clause may describe a different participant's result.
            body = re.split(r",\s*(?:who|whose|which)\b|\b(?:while|whereas)\b|\band\s+(?=[A-Z][a-z]+\s+[A-Z])", body)[0]
            end = paragraph.start() + match.end()
            if end - start <= 2000:
                yield body, {**evidence, 'quote': text[start:end].strip()}


def entity_assertions(record: dict, links: list[dict]):
    """Re-use retained relation paragraphs; never inherit the linked work's score."""
    seen = set()
    work_ids = {link['work_id'] for link in links}
    for ev in [*links, *record.get('attributed_evidence', [])]:
        if ev.get('work_id') not in work_ids:
            continue
        own_page = (record['type'] == 'team' and ev in links
                    and ev.get('work_name', '').casefold() == record['original_name'].casefold())
        for body, proof in attributed_statements(record['original_name'], record['type'], ev, own_page=own_page):
            key = (body, proof['source_url'], proof['work_id'])
            if key not in seen:
                seen.add(key)
                yield body, {k: proof[k] for k in ('quote', 'source_url', 'work_id')}


def assess_entity(record: dict) -> dict:
    criteria = {k: {"score": 0, "reason": "No data: no qualifying attributed evidence.",
                    "quote": "", "source_url": ""} for k in ENTITY_WEIGHTS}
    def award(key, level, reason, evidence):
        old = criteria[key]
        quote, url = evidence.get("quote", ""), evidence.get("source_url", "")
        if level > old["score"] or (level == old["score"] and level > 0 and (len(quote), quote, url) < (len(old["quote"]),old["quote"],old["source_url"])):
            criteria[key] = dict(score=level, reason=reason, quote=quote, source_url=url)
    links = [l for l in record.get("related_works", []) if eligible_link(l)]
    if record['type'] == 'expert' and not person_name(record['original_name']):
        links = []
    for link in links:
        award("contribution", contribution(link["role"]), "Explicit role or own contribution in an accepted work.", link)
    # These are independently attributed assertions, never an institution's or
    # another participant's score. The linked-work snapshots serve provenance,
    # not automatic inheritance of every project result.
    collaboration_works = {}
    international_awards = {}
    for text, ev in entity_assertions(record, links):
        guard = re.sub(r"\bnot only\b", "", text, flags=re.I)
        if has(FUTURE, guard) or has(NEGATED, guard):
            continue
        metrics = sentence_scores(text)
        topics = record_keywords({'original_name': '', 'evidence': [{'quote': text}]})
        technique = has(TECHNIQUE, text)
        completed = has(COMPLETED_RESULT, text)
        if has(ACTIVITY, text):
            defined_focus = has(r"\b(?:research (?:explores|examines|investigates)|focus(?:es)? on)\s+.{25,}", text)
            if topics or defined_focus:
                award('expertise', 1, 'An own research activity names a specific subject.', ev)
            if technique:
                award('expertise', 2, 'An own research activity describes a concrete method.', ev)
            if completed and technique and has(r"\b(?:algorithms?|software|datasets?|protocols?|instruments?|models?|platforms?|devices?)\b", text):
                award('expertise', 3, 'A concrete method was used to produce a research tool or resource.', ev)
            if completed and technique and metrics.get('validation', (0,))[0] >= 2 and has(MEASURE, text):
                award('expertise', 4, 'An own method has comparative validation and a quantitative measurement.', ev)
        if completed:
            award("results", 1, "An attributed concrete result is described.", ev)
            if technique and has(MEASURE, text) and has(OUTCOME, text):
                award("results", 2, "Attributed method and quantitative results are reported.", ev)
            if metrics.get("validation", (0,))[0] >= 2:
                award("results", 3, "Attributed comparative or independent validation is reported.", ev)
            if metrics.get("validation", (0,))[0] == 4:
                award("results", 4, "Attributed independent replication is reported.", ev)
        if has(r"working prototype|functional prototype|(?:developed|designed) (?:a |the )?(?:method|platform|device|algorithm)|tested prototype|functioning|funktionsfähig", text) and completed:
            award("application", 1, "An attributed working prototype or method is described.", ev)
        if has(r"tested in (?:clinical|real.world|field)|(?:completed|underwent|conducted) (?:a |the )?clinical evaluation|(?:conducted|completed) (?:a |the )?pilot study|deployed in (?:a |the )?pilot|klinisch getestet", text):
            award("application", 2, "Testing in application conditions is reported.", ev)
        if completed and has(r"used by|adopted by", text) and has(r"hospital|company|industry|partner|clinic", text):
            award("application", 3, "External partner use is explicitly attributed.", ev)
        deployed = has(r"^(?:(?:has|have|was|were|is|are)\s+(?:been\s+)?)?(?:licensed|signed|deployed|implemented|lizenziert)\b", text)
        if (completed or deployed) and has(r"licensed to|signed licen[cs]e|deployed in|implemented in|lizenziert", text):
            award("application", 4, "Implementation or licensing is explicitly attributed.", ev)
        named_awards = re.findall(r"\b([A-Z][\w’'-]+(?:\s+(?:[A-Z][\w’'-]+|of|the|for)){0,8}\s+(?:Award|Prize|Medal|Preis))\b",text)
        named_awards = [a for a in named_awards if a.casefold() not in ('international award','national award','institutional award','international prize','national prize')]
        if named_awards and has(r"^(?:(?:has|have|was|were)\s+(?:been\s+)?)?(?:awarded|received|gewann|erhielt)\b", text):
            level = 3 if has(r"international", text) else 2 if has(r"national|swiss|schweizer", text) else 1 if has(r"university|institutional|universit",text) else 0
            if level: award("recognition", level, "A named award is explicitly attributed with its scope.", ev)
            if level == 3:
                # Separate source assertions alone do not prove independent awards.
                body = re.search(r"(?:from|by) (?:the )?([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+){0,6})",text)
                if body:
                    for award_id in named_awards:
                        international_awards[(award_id,body[1])] = ev
        partners = re.findall(r"(?:University|Hospital|Institute|Universität) (?:of )?[A-Z][\w-]+(?: [A-Z][\w-]+){0,3}|[A-Z][\w-]+(?: [A-Z][\w-]+){0,3} (?:University|Hospital|Institute|GmbH|AG)|ETH Zurich|EPFL|Inselspital",text)
        own = {o.casefold() for o in record.get('organizations',[])}
        if 'artorg' in record.get('source_ids',[]): own.update(('artorg','university of bern'))
        external = {p for p in partners if p.casefold() not in own}
        collaboration_action = has(r"^(?:(?:has|have)\s+)?(?:collaborat\w*|works?|worked|operates?|conducted|conducts|leads?|led|participates?)\b", text)
        if external and collaboration_action and has(r"collaborat|together with|in partnership with|zusammenarbeit", text):
            award("collaboration", 1, "An attributed external collaboration is named.", ev)
            if has(r"\b(?:[2-9]|several|multiple) (?:institutions|organizations|organisations|universities)|University.*University", text):
                award("collaboration", 2, "Collaboration with multiple organizations is reported.", ev)
            if has(r"multicent|multi.cent|multizentr|cross.sector|intersector|industry.*(?:university|hospital)|(?:university|hospital).*industry", text):
                award("collaboration", 3, "An attributed multicenter or cross-sector collaboration is reported.", ev)
                collaboration_works[ev["work_id"]] = ev
    if len({body for _,body in international_awards}) > 1 and len({name for name,_ in international_awards}) > 1:
        criteria["recognition"].update(score=4, reason="Multiple independently awarded named international prizes.",
                                       evidence=list(international_awards.values()))
    if len(collaboration_works) > 1:
        criteria["collaboration"].update(score=4, reason="Attributed multicenter/cross-sector collaboration in separate works.",
                                         evidence=list(collaboration_works.values()))
    return dict(version=ENTITY_VERSION, score=sum(ENTITY_WEIGHTS[k]*v["score"]/4 for k,v in criteria.items()),
                criteria=criteria, assessed_criteria=len(criteria),
                evidenced_criteria=sum(v['score'] > 0 for v in criteria.values()))


def enrich_entity_evidence(record: dict, document) -> None:
    """Refresh only own assertions from a dated, already linked source document."""
    works = {}
    source_text = ' '.join(clean_text(document.text).split())
    for link in record.get('related_works', []):
        if (eligible_link(link) and link['source_url'] in (document.url, document.retrieval_url)
                and ' '.join(link['quote'].split()) in source_text):
            works[link['work_id']] = dict(id=link['work_id'], original_name=link['work_name'],
                type=link.get('work_type', 'project'), organizations=record.get('organizations', []),
                evidence=link.get('work_evidence', []))
    if not works:
        return
    own = [r for r in extract_entities(document, list(works.values()))
           if r['type'] == record['type'] and r['original_name'] == record['original_name']
           and not (r.get('identity_url') and record.get('identity_url')
                    and profile_identity(r['identity_url']) != profile_identity(record['identity_url']))]
    if not own:
        return
    # Other sources and identity/role proofs are untouched; keep actual source dates.
    retained = [ev for ev in record.get('attributed_evidence', [])
                if ev['source_url'] not in (document.url, document.retrieval_url)]
    unique = {(ev['source_url'], ev['work_id'], ev['quote']): ev
              for ev in [*retained, *(ev for r in own for ev in r['attributed_evidence'])]}
    record['attributed_evidence'] = list(unique.values())[:30]
    record['competencies'] = record_keywords({**record, 'evidence': record['attributed_evidence']})


def extract_entities(document, works: list[dict]) -> list[dict]:
    """Extract against accepted local work scope, not against the whole institution."""
    if not works:
        return []
    text = clean_text(document.text)
    anchors = [(clean_text(a).strip(), u) for u,a,*_ in document.links if a.strip()]
    person_anchors = [(name,u) for a,u in anchors if (name := person_name(a))]
    profiles = {a:u for a,u in anchors}
    profiles.update(dict(person_anchors))
    result = {}
    for work in works:
        name = work["original_name"]
        sections = text.split("\n\n")
        # A detail page has one work identity. On a multi-project page only its
        # own titled section can establish the relation.
        detail = (len(works) == 1 and " ".join(name.split()) == " ".join(document.title.split())
                  and not has(COLLECTION_TITLE,document.title)
                  and not re.search(r"/(?:project_category|category|archive)/",document.url))
        scope = text if detail else "\n\n".join(s for s in sections if s.splitlines() and s.splitlines()[0].strip() == name)
        if not scope:
            # Exact local result excerpts can carry explicitly named subjects.
            scope = "\n".join(e["quote"] for e in work["evidence"])
        def add(entity_name, kind, role, quote, affiliation=""):
            entity_name = entity_name.strip()
            if not entity_name or has_contact(quote) or not contribution(role): return
            if kind == "team" and (len(entity_name.split()) < 2 or re.fullmatch(r"(?:our |the )?(?:research )?(?:group|team|laboratory|lab)",entity_name,re.I)):
                return
            profile = profiles.get(entity_name, "")
            if kind == "team" and detail and entity_name.casefold() in document.title.casefold():
                profile = document.url
            # Profiles are same-boundary HTTP links, never publication or mail links.
            if profile and (urlsplit(profile).hostname != urlsplit(document.url).hostname or not re.search(r"person|people|staff|group|team|research/[^/]+/index", profile,re.I)):
                profile = ""
            translations = [u for a,u in anchors if a.casefold() in ("deutsch","english","german","englisch","en","de")
                            and '/project/' in u and '/project/' in document.url
                            and urlsplit(u).hostname == urlsplit(document.url).hostname]
            work_url = next((u for a,u in anchors if a == name and '/project/' in u
                             and urlsplit(u).hostname == urlsplit(document.url).hostname),document.url)
            identity = profile_identity(profile) if profile else min([work_url,*translations]) + "|" + entity_name
            key = kind + ":" + identity
            ev = dict(quote=quote,source_url=document.url,retrieval_url=document.retrieval_url or document.url,fetched_at=document.fetched_at)
            link = {**ev, "work_id":work["id"],"work_name":name,"role":role,"accepted_work":True,
                    "work_evidence": work["evidence"][:3], "work_type":work["type"]}
            if key not in result:
                result[key] = dict(id=hashlib.sha256(key.encode()).hexdigest()[:24],type=kind,
                    title=entity_name, original_name=entity_name, unit=work.get("unit", ""),
                    selection_method="rules", review_status="unreviewed", matched_rules=["explicit_work_role"],
                    summary="Explicitly linked to an accepted research work; evidence is retained with the relation.",
                    rationale="Separate entity criteria apply only to attributed evidence; absent data earn zero points.",
                    organizations=([affiliation] if affiliation else work["organizations"] if kind == "team" else []),scores={"scientific":0,"practical":0,"capability":0},
                    evidence=[], related_works=[], attributed_evidence=[], roles=[], competencies=[],
                    experts=[],teams=[],identifiers=[],topics=[],source_urls=[document.url],
                    source_ids=[document.source_id],external_references=[],fetched_at=document.fetched_at,
                    status="unknown",status_quote="", date=None,identity_url=profile,
                    identity_evidence=[ev] if profile else [], identity_anchor=key)
            rec = result[key]
            rec["related_works"].append(link)
            rec["roles"].append(dict(role=role,work_id=work["id"],**ev))
            rec["evidence"].append({**ev,"supports":[]})
            for _, proof in attributed_statements(entity_name, kind, {**ev, 'quote': scope},
                                                   own_page=detail and entity_name == document.title):
                rec["attributed_evidence"].append({**proof, "work_id": work["id"]})
            if profile and profile not in rec["source_urls"]: rec["source_urls"].append(profile)
        lines = scope.splitlines()
        for i,line in enumerate(lines):
            match = ROLE_LINE.match(line.strip())
            if match:
                role, values = match["role"], match["names"]
                # Parenthesized affiliations contain commas; strip them before
                # splitting a member list. Titles/qualifications never become names.
                values_for_names = re.sub(r"\([^)]*\)","",values)
                members = [n for value in re.split(r";|,|\s+and\s+|\s+und\s+|&", values_for_names) if (n := person_name(value))]
                for j,entity_name in enumerate(members):
                    start = values.find(entity_name) + len(entity_name)
                    end = values.find(members[j+1],start) if j+1 < len(members) else len(values)
                    affiliation_text = values[start:end]
                    affiliation = next((canonical for pattern,canonical in (
                        (r"University of Bern(?:e)?\b|Universität Bern", "University of Bern"),
                        (r"Diabetes Center Bern(?:e)?|\bDCB\b", "Diabetes Center Berne"),
                        (r"Kantonsspital Olten", "Kantonsspital Olten"),
                        (r"Inselspital", "Inselspital")) if has(pattern,affiliation_text)), "")
                    add(entity_name,"expert",role,line,affiliation)
                if has(r"group|team|gruppe",role) and TEAM.fullmatch(values) and len(values) < 160:
                    add(values,"team","project participant",line)
            elif ROLE_HEADING.fullmatch(line.strip()):
                # A labelled list ends at the next blank/heading/paragraph.
                for offset, following in enumerate(lines[i+1:i+9], 1):
                    if not following.strip(): break
                    if entity_name := person_name(following):
                        add(entity_name,"expert",line,"\n".join(lines[i:i+offset+1]))
                    else: break
            explicit_team = re.match(r"The (?P<name>[^.!?\n]{3,140}?\b(?:[Gg]roup|[Ll]ab|Laboratory|Team))(?:\s*\([^)]+\))?\s+(?:has )?(?P<verb>develops|developed|designed|conducts|conducted|investigates|studies|advances)\b",line)
            if explicit_team:
                add(explicit_team["name"],"team",explicit_team["verb"],line)
            for team in (() if explicit_team else TEAM.finditer(line)):
                entity_name = re.sub(r"^(?:The|Our|At|In)\s+", "", team[1])
                tail = line[team.end():]
                verb = re.match(r"\s*(?:\([^)]+\)\s*)?(develops|developed|designed|conducted|investigated|investigates|studies|advances|analysed|analyzed)\b",tail)
                if verb: add(entity_name,"team",verb[1],line)
            # A named person is an explicit subject of a contribution/leadership
            # clause. Never scan arbitrary co-occurring names as contributors.
            for entity_name,u in person_anchors:
                match = re.search(re.escape(entity_name)+r",?\s+(?:who\s+)?(leads? (?:the |a )?project|developed|designed|conducted|investigated|analysed|analyzed)\b",line)
                if match: add(entity_name,"expert","project leader" if match[1].startswith("lead") else match[1],line)
        # A dedicated, explicitly named group page can use first-person prose.
        # Its title plus own activity is the evidence; directory entries cannot.
        if detail and has(r"Group|Lab\b|Laboratory|Research Group:",document.title) and not has(r"groups|leaders|members",document.title.lower()):
            acronym_match = re.search(r"\(([A-Z]{2,8})\)|\b([A-Z]{2,8})$",document.title)
            acronym = next((v for v in acronym_match.groups() if v), "") if acronym_match else ""
            own = re.search(r"(?:Our (?:research group|group|lab)|This research group|The group" +
                            (r"|The "+re.escape(acronym) if acronym else "") +
                            r")\s+(?:has )?(investigates|studies|develops|developed|conducts|operates|serves)",scope,re.I)
            if own:
                first = scope[own.start():scope.find('\n',own.end())] if '\n' in scope[own.end():] else scope[own.start():]
                if len(first) <= 2000:
                    add(document.title,"team","investigates",first)
        # Safe fact enrichment only from evidence belonging to this relation.
    for rec in result.values():
        rec["keywords"] = record_keywords({**rec,"evidence":rec["evidence"]+[e for l in rec["related_works"] for e in l["work_evidence"]]})
        rec["competencies"] = record_keywords({**rec,"evidence":rec["attributed_evidence"]})
    return list(result.values())
