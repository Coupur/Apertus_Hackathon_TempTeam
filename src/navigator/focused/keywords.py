"""Evidence-derived EN/DE subject keywords, with detailed medical coverage.

These describe mentions, not proven expertise, efficacy, availability or outcomes.
No keyword is inferred from an institution, source host or selection rule.
"""
import re
import unicodedata

MAX_KEYWORDS = 24

# Canonical English labels and explicit English/German aliases. Keep additions
# here so extraction, link prioritization and CLI filtering share one vocabulary.
MEDICAL = {
    # Diseases and clinical specialties.
    "diabetes": r"diabet\w*|t1d|t2d",
    "type 1 diabetes": r"(?:type|typ) 1 diabet\w*|diabet\w* (?:type|typ) 1|t1d",
    "type 2 diabetes": r"(?:type|typ) 2 diabet\w*|diabet\w* (?:type|typ) 2|t2d",
    "endocrinology": r"endocrin\w*|endokrin\w*|hormon\w*|androgen\w*|cortisol|kortisol",
    "hypoglycemia": r"hypoglyc(?:ae|e)mi\w*|hypoglykämi\w*|unterzucker\w*",
    "obesity": r"obesity|obese|adiposit\w*|fettleib\w*",
    "metabolic disease": r"metabolic (?:disease|disorder)\w*|stoffwechselerkrank\w*",
    "oncology": r"oncolog\w*|onkolog\w*|cancer\w*|tumou?r\w*|carcinom\w*|karzinom\w*|(?:brust|lungen|prostata|darm|blasen)?krebs\w*|leuk[aä]m\w*|leukem\w*|lymphom\w*",
    "breast cancer": r"breast cancer|mammakarzinom\w*|brustkrebs\w*",
    "lung cancer": r"lung cancer|lungenkrebs\w*|lungenkarzinom\w*",
    "prostate cancer": r"prostate cancer|prostatakrebs\w*|prostatakarzinom\w*",
    "colorectal cancer": r"colorectal cancer|colon cancer|darmkrebs\w*|kolorektal\w* karzinom\w*",
    "bladder cancer": r"bladder cancer|blasenkrebs\w*|blasenkarzinom\w*",
    "hematology": r"ha?ematolog\w*|hämatolog\w*|leuk[aä]m\w*|leukem\w*|lymphom\w*",
    "cardiology": r"cardiolog\w*|kardiolog\w*|cardiovascular|kardiovaskul\w*|heart disease|heart failure|herzinsuffizienz|herz kreislauf\w*",
    "heart failure": r"heart failure|herzinsuffizienz",
    "neurology": r"neurolog\w*|neuroscien\w*|neurowissen\w*|neurophysiolog\w*|brain\w*|gehirn\w*|nervous system|nervensystem\w*",
    "neurodegeneration": r"neurodegenerat\w*|alzheimer\w*|parkinson\w*|dementia|demenz\w*",
    "Alzheimer's disease": r"alzheimer\w*",
    "Parkinson's disease": r"parkinson\w*",
    "stroke": r"stroke\w*|schlaganfall\w*",
    "epilepsy": r"epilep\w*|seizures?|krampfanf[aä]ll\w*",
    "mental health": r"mental health|psychisch\w* gesundheit|psychiatr\w*|depressi\w*|anxiety|angststörung\w*",
    "addiction": r"addict\w*|substance use disorder\w*|suchterkrank\w*|abhängigkeitserkrank\w*",
    "sleep medicine": r"sleep\w*|schlaf\w*",
    "ophthalmology": r"ophthalm\w*|glaucom\w*|glaukom\w*|retin\w*|cornea\w*|augenheilkunde|perimetr\w*",
    "glaucoma": r"glaucom\w*|glaukom\w*",
    "hearing and audiology": r"audiolog\w*|hearing\w*|cochlea\w*|hör\w*|gehör|gehörlos\w*|deaf\w*",
    "musculoskeletal health": r"musculoskeletal|orthop[aä]d\w*|orthoped\w*|spinal|spine|scoliosis|skoliose|wirbelsäul\w*|osteoporos\w*|arthritis|osteoarthritis|arthrose\w*",
    "respiratory medicine": r"pulmonary|respiratory|pneumolog\w*|asthma\w*|copd|lungen\w*|airways?|atemweg\w*|cystic fibrosis|mukoviszidose",
    "gastroenterology": r"gastroenterolog\w*|intestinal|crohn\w*|colitis|kolitis|bowel|darm\w*",
    "hepatology": r"hepatolog\w*|liver\w*|leber\w*|cirrhosis|zirrhose\w*",
    "nephrology": r"nephrolog\w*|kidney\w*|renal|nieren\w*|dialys\w*",
    "dermatology": r"dermatolog\w*|skin disease|skin cancer|hautkrank\w*|hauterkrank\w*|psoriasis|eczema|ekzem\w*",
    "immunology": r"immun\w*|antibod\w*|antikörper\w*|t cells?|t helper|b cells?",
    "inflammation": r"inflamm\w*|entzünd\w*",
    "autoimmune disease": r"autoimmun\w*|multiple sclerosis|multiple sklerose|rheumatoid\w*|rheumatoide\w*",
    "allergy": r"allerg\w*",
    "infectious disease": r"infect\w*|infekt\w*|pathogen\w*|hiv|tuberculos\w*|tuberkulos\w*|malaria|covid\w*|sars cov 2|sepsis",
    "antimicrobial resistance": r"antimicrobial resistance|antibiotic resistan\w*|antibiotikaresisten\w*|antimikrobiell\w* resisten\w*",
    "virology": r"virolog\w*|virus\w*|viren|viral\w*|coronavirus\w*|coronaviren",
    "parasitology": r"parasit\w*|plasmodi\w*|trypanosom\w*",
    "microbiology": r"microbiolog\w*|mikrobiolog\w*|bacteri\w*|bakteri\w*|microorganism\w*|mikroorganism\w*",
    "microbiome": r"microbiom\w*|mikrobiom\w*|microbiota|mikrobiota|darmflora",
    "pediatrics": r"pa?ediatr\w*|pädiatr\w*|childhood|children|kinder\w*|neonat\w*",
    "reproductive health": r"reproduct\w*|fertility|infertility|schwanger\w*|pregnan\w*|placenta\w*|plazenta\w*|menstrual\w*|menstruation\w*|gyn[aä]kol\w*|gynecol\w*|gynaecol\w*",
    "veterinary medicine": r"veterinar\w*|veterinär\w*|tiermedizin\w*|tierärzt\w*|animal health|tiergesundheit\w*",
    "dentistry": r"dentist\w*|dental\w*|zahn\w*|oral health",
    "pain medicine": r"chronic pain|pain management|schmerz\w*",
    "palliative care": r"palliativ\w*|end of life care",
    "sports medicine": r"sports medicine|sportmedizin\w*|exercise physiolog\w*|physical activity|körperlich\w* aktivität",
    # Diagnostics, monitoring and devices.
    "glucose": r"glucose|blutzucker\w*|glukose\w*|glyc(?:ae|e)mi\w*|glykämi\w*|hypoglyc(?:ae|e)mi\w*|hypoglykämi\w*|cgm",
    "glucose monitoring": r"glucose (?:monitor|sensor|measur)\w*|(?:monitor\w*|measur\w*) (?:blood )?glucose|blutzuckermess\w*|glukosemess\w*|glukosesensor\w*|cgm|kontinuierlich\w* (?:glukose|blutzucker)\w*",
    "continuous glucose monitoring": r"continuous glucose monitor\w*|cgm|kontinuierlich\w* (?:glukose|blutzucker)\w*",
    "insulin delivery": r"insulin pump\w*|insulin delivery|insulin infusion|insulinpumpe\w*|insulinabgabe\w*|insulinzufuhr\w*",
    "automated insulin delivery": r"automated insulin delivery|artificial pancreas|künstlich\w* pankreas|closed loop insulin|closed loop (?:glucose|diabet\w*)",
    "insulin": r"insulin\w*",
    "biosensors": r"biosensor\w*|glucose sensors?|glukosesensor\w*|biomolecular sensors?",
    "wearable devices": r"wearabl\w*|tragbar\w* (?:sensor|gerät)\w*",
    "medical devices": r"medical devices?|medical technolog\w*|medizintechnik\w*|(?:bio)?medtech|medizinisch\w* gerät\w*",
    "biomedical engineering": r"biomedical engineer\w*|biomedizinisch\w* technik|biomems",
    "implants": r"implant\w*|prosthes\w*|prothes\w*",
    "medical imaging": r"medical imaging|biomedical imaging|medizinisch\w* bildgebung|magnetic resonance|magnetresonanz\w*|mri|mrt|computed tomography|computertomograph\w*|ultrasound|ultraschall\w*|pet imaging",
    "magnetic resonance imaging": r"magnetic resonance|magnetresonanz\w*|mri|mrt|fmri",
    "computed tomography": r"computed tomography|computertomograph\w*|ct scan\w*",
    "ultrasound": r"ultrasound|ultraschall\w*|sonograph\w*",
    "biomarkers": r"biomarker\w*",
    "molecular diagnostics": r"molecular diagnos\w*|molekular\w* diagnos\w*|pcr|polymerase chain reaction",
    "diagnostics": r"diagnos\w*|screening\w*|früherkennung\w*",
    "patient monitoring": r"patient monitor\w*|patientenüberwachung|remote monitor\w*|vital signs?|vitalparameter\w*",
    # Treatment and translation. Mentions do not establish clinical efficacy.
    "surgery": r"surg\w*|chirurg\w*|operativ\w* eingriff\w*",
    "surgical robotics": r"surgical robot\w*|robot\w* [^.!?\n]{0,60}\b(?:surg\w*|chirurg\w*)|chirurg\w* robot\w*",
    "image-guided therapy": r"image guided (?:therap|surg|intervention)\w*|bildgesteuert\w* (?:therap|chirurg|intervention)\w*",
    "radiotherapy": r"radiotherap\w*|radiation therap\w*|strahlentherap\w*",
    "immunotherapy": r"immunotherap\w*|immuntherap\w*|car t(?: cells?)?",
    "gene therapy": r"gene therap\w*|gentherap\w*",
    "cell therapy": r"cell therap\w*|zelltherap\w*|stem cells?|stammzell\w*",
    "drug discovery": r"drug (?:discovery|development|screening)|wirkstoff\w*|arzneimittelentwicklung",
    "pharmacology": r"pharmacolog\w*|pharmakolog\w*|pharmacokinet\w*|pharmakokinet\w*",
    "drug delivery": r"drug delivery|controlled release|wirkstofffreisetzung|wirkstofftransport",
    "vaccines": r"vaccin\w*|impf\w*",
    "regenerative medicine": r"regenerative medicin\w*|regenerativ\w* medizin|tissue engineer\w*|gewebezüchtung",
    "rehabilitation": r"rehabilitat\w*|physiotherap\w*|physical therap\w*",
    "precision medicine": r"precision medicin\w*|personalized medicin\w*|personalised medicin\w*|personalisierte\w* (?:medizin|therapie|behandlung)|präzisionsmedizin",
    "digital health": r"digital health|ehealth|e health|mhealth|digital\w* gesundheit\w*|telemedicin\w*|telemedizin\w*",
    "clinical trials": r"clinical (?:trial|stud)\w*|klinisch\w* (?:studie|prüfung)\w*|randomi[sz]ed|randomisiert\w*|controlled trial\w*",
    "clinical research": r"clinical research|klinisch\w* forschung|clinical facilit\w*|clinical space",
    "clinical validation": r"clinical validation|clinical performance|klinisch\w* validier\w*",
    "patient outcomes": r"patient outcomes?|patient reported|quality of life|lebensqualität|survival|überleben\w*",
    "patient safety": r"patient safety|patientensicherheit|adverse events?|nebenwirkung\w*",
    # Research methods and infrastructure.
    "genetics": r"genet\w*|genes?|gen|genexpression|genmutation\w*|dna|ribonucleic|rna",
    "genomics": r"genom\w*|whole genome\w*",
    "sequencing": r"sequenc\w*|sequenzier\w*|ngs",
    "single-cell analysis": r"single cell\w*|einzelzell\w*",
    "transcriptomics": r"transcriptom\w*|transkriptom\w*|rna sequenc\w*|rna sequenzier\w*|rna seq",
    "proteomics": r"proteom\w*",
    "metabolomics": r"metabolom\w*",
    "bioinformatics": r"bioinformat\w*",
    "biobanking": r"biobank\w*",
    "microscopy": r"microscop\w*|mikroskop\w*|confocal|konfokal\w*",
    "flow cytometry": r"flow cytometr\w*|durchflusszytometr\w*|facs",
    "mass spectrometry": r"mass spectrometr\w*|massenspektrometr\w*|lc ms|lc ms ms",
    "organoids": r"organoid\w*",
    "organ-on-chip": r"organs? on (?:a )?chip|organ chip\w*",
    "microfluidics": r"microfluid\w*|mikrofluid\w*",
    "3D bioprinting": r"3d bioprint\w*|3d biodruck\w*|bioprint\w*",
    "biomaterials": r"biomaterial\w*|biocompatib\w*|biokompatib\w*",
    "biomechanics": r"biomechani\w*|spinal mechanics",
    "laboratory services": r"laboratory services?|lab services?|laboratory facilities|biosafety\w*|bio safety|bsl 2|bsl 3|clinical facilit\w*|core facilit\w*",
    "preclinical research": r"preclinical|präklinisch\w*|animal models?|tiermodell\w*|in vivo|in vitro",
    "epidemiology": r"epidemiolog\w*",
    "public health": r"public health|population health|global health|öffentlich\w* gesundheit|gesundheitsförderung",
    "systematic reviews": r"systematic reviews?|systematisch\w* (?:review|übersicht)\w*|meta analys\w*",
    "cohort studies": r"cohort\w*|kohort\w*|longitudinal\w*",
    "biostatistics": r"biostatisti\w*|network meta analys\w*",
    "medical education": r"medical education|medical teaching|medical students?|clinical skills|medizinisch\w* (?:ausbildung|lehre)|humanmedizin|osce\w*|eosce",
    "nutrition": r"nutrition\w*|ernährung\w*|dietary|diets?|diät\w*",
}

GENERAL = {
    "artificial intelligence": r"artificial intelligence|künstlich\w* intelligenz|machine learning|maschinell\w* lernen|deep learning|neural networks?|neuronale\w* netz\w*|ai|ki",
    "machine learning": r"machine learning|maschinell\w* lernen|deep learning|neural networks?|neuronale\w* netz\w*",
    "robotics": r"robot\w*",
    "digital twins": r"digital twins?|digital\w* zwilling\w*",
    "computational modeling": r"computational model\w*|computer model\w*|numerical simulat\w*|computermodell\w*|simulation\w*",
    "sensors": r"sensor\w*",
    "spectroscopy": r"spectroscop\w*|spektroskop\w*",
    "nanotechnology": r"nanotechnolog\w*|nanoparticl\w*|nanopartikel\w*|nanomaterial\w*",
    "materials science": r"materials science|materialwissenschaft\w*|catalys\w*|katalys\w*|polymer\w*",
    "climate research": r"climat\w*|klima\w*|greenhouse gas\w*|treibhausgas\w*|ice cores?|eisbohrkern\w*",
    "biodiversity": r"biodivers\w*|biologisch\w* vielfalt|artenvielfalt|ecosystem\w*|ökosystem\w*",
    "sustainability": r"sustainab\w*|nachhaltig\w*",
    "agriculture": r"agricultur\w*|landwirtschaft\w*|farming|land use|landnutzung\w*",
    "energy": r"renewable energy|erneuerbar\w* energ\w*|fuel cells?|brennstoffzell\w*|hydrogen|wasserstoff\w*|solar energy|batter\w*",
    "space science": r"astronom\w*|astrophysi\w*|exoplanet\w*|planet\w*|satellite\w*|satellit\w*|telescope\w*|teleskop\w*|gnss|comet\w*|komet\w*|asteroid\w*|moon|mond|mars|venus|jupiter|space mission\w*|raumsond\w*|heliophysi\w*|interstellar\w*",
    "particle physics": r"particle physic\w*|teilchenphysik|neutrino\w*|neutron\w*",
    "quantum science": r"quantum\w*|quanten\w*",
    "social sciences": r"sociolog\w*|soziolog\w*|social scien\w*|sozialwissenschaft\w*",
    "archaeology": r"archaeolog\w*|archeolog\w*|archäolog\w*|prehistor\w*|prähistor\w*",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace("\u00ad", "")
    return " ".join(re.sub(r"[_\-‐‑–—/]", " ", text).split())


PATTERNS = {
    label: re.compile(r"(?<!\w)(?:" + re.escape(normalize(label)) + "|" + aliases + r")(?!\w)")
    for label, aliases in {**MEDICAL, **GENERAL}.items()
}
INSTITUTIONS = re.compile(r"diabetes cent(?:er|re) bern(?:e)?\b|university of bern\b|universität bern\b|artorg\b")


def extract_keywords(text: str, title: str = "") -> list[str]:
    """Prefer title matches, then medical terms and specificity; cap output size."""
    title = INSTITUTIONS.sub(" ", normalize(title))
    text = title + "\n" + INSTITUTIONS.sub(" ", normalize(text))
    matched = [label for label, pattern in PATTERNS.items() if pattern.search(text)]
    return sorted(matched, key=lambda label: (
        not bool(PATTERNS[label].search(title)), label not in MEDICAL,
        -len(label.split()), label.casefold(),
    ))[:MAX_KEYWORDS]


def record_keywords(record: dict) -> list[str]:
    # Template summaries/rationale/topics describe selection rules, not subjects.
    return extract_keywords("\n".join(e["quote"] for e in record.get("evidence", [])),
                            record.get("original_name", ""))


def matches_keyword(record: dict, query: str) -> bool:
    """Match canonical labels or EN/DE aliases; multiple concepts require all."""
    available = record.get("keywords", [])
    if normalize(query) in {normalize(label) for label in PATTERNS}:
        return normalize(query) in {normalize(keyword) for keyword in available}
    wanted = extract_keywords(query)
    if wanted:
        return set(wanted) <= set(available)
    return normalize(query) in {normalize(keyword) for keyword in available}


def keyword_priority(text: str) -> int:
    """A bounded link bonus, with a stronger signal for medical subject matter."""
    keywords = extract_keywords(text)
    return min(8, sum(4 if keyword in MEDICAL else 1 for keyword in keywords))
