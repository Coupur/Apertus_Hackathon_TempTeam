"""Topic lexicon for the no-LLM fallback: spots what a company works on and gives the research terms,
in English and German, that Bern pages use for it. Apertus does this better; this keeps the
pipeline running without an endpoint and gives the template queries their words.
"""
import re
from dataclasses import dataclass, field


@dataclass
class Topic:
    key: str
    label: str
    pattern: str
    en: list[str]
    de: list[str]
    infra: list[str] = field(default_factory=list)     # what a company would want to use (section E)
    services: list[str] = field(default_factory=list)  # what a company would want done (section F)
    reg: tuple[str, str] | None = None                 # (en, de) rules that apply (section J)

    def __post_init__(self):
        self.rx = re.compile(self.pattern, re.I)


MEDTECH_REG = ("medical devices and clinical investigations", "Medizinprodukte und klinische Versuche")
DRUG_REG = ("medicinal products and clinical trials", "Arzneimittel und klinische Versuche")

TOPICS = [
    Topic("diabetes", "diabetes care", r"diabet|insulin|glucose|glukose|blutzucker|\bcgm\b",
          ["diabetes technology", "continuous glucose monitoring", "insulin therapy"],
          ["Diabetestechnologie", "kontinuierliche Glukosemessung", "Insulintherapie"],
          ["clinical research unit for diabetes"], ["clinical studies with diabetes patients", "usability testing"],
          MEDTECH_REG),
    Topic("drug_delivery", "drug delivery devices", r"drug delivery|injector|injection (pen|device|system)|pen needle|injektion|autoinjekt|self-?inject"
          r"|selbstmedikation|selbstbehandlung|infusion pump|insulin ?pump|insulinpumpe|inhal|parenteral",
          ["drug delivery systems", "injection devices", "pharmaceutical technology"],
          ["Arzneimittelverabreichung", "Injektionssysteme", "pharmazeutische Technologie"],
          ["device testing lab"], ["human factors and usability studies"], MEDTECH_REG),
    Topic("medical_devices", "medical devices", r"medical device|medtech|medizintechnik|medizinprodukt|medizinische geräte|implant"
          r"|catheter|surgical|chirurg",
          ["medical device development", "biomedical engineering", "surgical technology"],
          ["Medizintechnik", "Medizinprodukte", "Biomedizintechnik"],
          ["biomechanics test lab", "surgical simulation lab"], ["preclinical testing", "clinical validation"],
          MEDTECH_REG),
    Topic("pharma", "drug development", r"pharma|drug discovery|drug development|therapeutic|wirkstoff|arzneimittel"
          r"|clinical trial|biologics",
          ["drug development", "pharmacology", "clinical trials"],
          ["Medikamentenentwicklung", "Pharmakologie", "klinische Studien"],
          ["clinical trials unit", "biobank"], ["clinical study support", "pharmacokinetic analysis"], DRUG_REG),
    Topic("diagnostics", "diagnostics", r"diagnos|biomarker|\bassays?\b|in[- ]vitro|\bivd\b|point[- ]of[- ]care",
          ["diagnostics", "biomarkers", "laboratory medicine"], ["Diagnostik", "Biomarker", "Labormedizin"],
          ["clinical laboratory", "mass spectrometry"], ["sample analysis", "assay validation"], MEDTECH_REG),
    Topic("digital_health", "digital health", r"digital health|telemedicine|telemedizin|e-?health|m-?health"
          r"|health data|patient data|electronic health record",
          ["digital health", "medical informatics", "telemedicine"],
          ["digitale Gesundheit", "Medizininformatik", "Telemedizin"],
          [], ["clinical data analysis"], ("health data protection and medical software", "Gesundheitsdaten und Medizinsoftware")),
    Topic("biotech", "biotechnology", r"biotech|cell therap|antibod|antikörper|protein|enzym|fermentation"
          r"|synthetic biology|bioprocess",
          ["biotechnology", "molecular biology", "protein engineering"],
          ["Biotechnologie", "Molekularbiologie", "Proteinengineering"],
          ["protein production facility", "flow cytometry", "microscopy"], ["protein analysis"]),
    Topic("genomics", "genomics", r"genom|sequencing|sequenzier|\bdna\b|\brna\b|crispr|bioinformati",
          ["genomics", "next-generation sequencing", "bioinformatics"], ["Genomik", "Sequenzierung", "Bioinformatik"],
          ["next generation sequencing platform", "high-performance computing"], ["sequencing service", "bioinformatics analysis"]),
    Topic("infection", "infectious diseases", r"infect|infekt|\bvir(us|al)|bacteri|bakteri|antibiotic|antibiotik"
          r"|vaccin|impfstoff|pathogen",
          ["infectious diseases", "microbiology", "vaccine research"],
          ["Infektionskrankheiten", "Mikrobiologie", "Impfstoffforschung"], ["biosafety laboratory"], ["microbiological testing"]),
    Topic("oncology", "oncology", r"cancer|krebs|oncolog|onkolog|tumou?r",
          ["oncology", "cancer research"], ["Onkologie", "Krebsforschung"], ["biobank"], ["clinical studies"]),
    Topic("neuro", "neuroscience", r"neuro|brain|gehirn|stroke|schlaganfall|epilep|parkinson|sleep|schlaf",
          ["neuroscience", "neurology", "neurotechnology"], ["Neurowissenschaften", "Neurologie"],
          ["MRI scanner", "sleep laboratory"]),
    Topic("cardio", "cardiovascular health", r"cardi|\bheart|herz|vascular|gefäss|blood pressure|blutdruck",
          ["cardiovascular engineering", "cardiology"], ["Kardiologie", "Herz-Kreislauf-Forschung"], ["cardiovascular test bench"]),
    Topic("musculoskeletal", "orthopaedics and dental", r"orthop|\bbones?\b|knochen|spine|wirbelsäule|\bjoints?\b"
          r"|gelenk|musculoskeletal|dental|\bzahn",
          ["orthopaedics", "bone biomechanics", "dental medicine"], ["Orthopädie", "Knochenbiomechanik", "Zahnmedizin"],
          ["biomechanics test lab"], ["implant testing"], MEDTECH_REG),
    Topic("imaging", "imaging", r"imaging|\bmri\b|ultrasound|ultraschall|x-ray|röntgen|\bct\b|microscop|mikroskop",
          ["medical imaging", "image analysis", "magnetic resonance imaging"], ["Bildgebung", "Bildanalyse"],
          ["MRI scanner", "microscopy imaging centre"], ["image analysis"]),
    Topic("ai", "AI and data science", r"artificial intelligence|machine learning|deep learning|\bAI\b|künstliche intelligenz"
          r"|neural network|computer vision|data science|predictive",
          ["machine learning", "artificial intelligence", "computer vision", "data science"],
          ["maschinelles Lernen", "künstliche Intelligenz", "Datenwissenschaft"],
          ["GPU computing cluster"], ["data analysis consulting"]),
    Topic("software", "software and cybersecurity", r"\bsoftware\b|\bsaas\b|cyber|cryptograph|kryptograph|encryption"
          r"|verschlüssel|informatik",
          ["software engineering", "cybersecurity", "cryptography"], ["Softwaretechnik", "Cybersicherheit", "Kryptographie"]),
    Topic("robotics", "robotics and automation", r"robot|automation|automatisier|mechatron|actuator",
          ["robotics", "automation", "mechatronics"], ["Robotik", "Automatisierung", "Mechatronik"], ["robotics lab"]),
    Topic("sensors", "sensors and wearables", r"sensor|wearable|messtechnik|measurement system",
          ["sensor technology", "wearable sensors", "biosensing"], ["Sensorik", "Messtechnik", "Wearables"],
          ["electronics lab", "cleanroom"], ["sensor validation"]),
    Topic("photonics", "photonics and quantum", r"quantum|quanten|photonic|photonik|\blasers?\b|optics|optik",
          ["photonics", "laser physics", "quantum technology"], ["Photonik", "Laserphysik", "Quantentechnologie"], ["laser lab"]),
    Topic("materials", "materials and surfaces", r"polymer|coating|beschicht|composite|ceramic|keramik|alloy|legierung"
          r"|surface|oberfläch|nano",
          ["materials science", "surface analysis", "polymers"], ["Materialwissenschaft", "Oberflächenanalyse", "Polymere"],
          ["X-ray diffraction", "electron microscopy"], ["materials testing", "surface analysis"]),
    Topic("chemistry", "chemistry", r"chemi|catalys|katalys|synthes|analytical",
          ["chemistry", "analytical chemistry", "catalysis"], ["Chemie", "analytische Chemie", "Katalyse"],
          ["mass spectrometry", "NMR spectroscopy"], ["chemical analysis"]),
    Topic("precision", "precision manufacturing", r"precision|präzision|\bwatch|uhren|micro-?mechani|mikrotechnik"
          r"|machining|manufactur|fertigung|injection mould",
          ["precision engineering", "microtechnology", "advanced manufacturing"],
          ["Präzisionstechnik", "Mikrotechnik", "Fertigungstechnik"], ["materials testing lab"], ["metrology"]),
    Topic("food", "food and nutrition", r"\bfood|lebensmittel|nahrung|chocolate|schokolade|cocoa|kakao|dairy (products?|industry|processing)"
          r"|molkerei"
          r"|cheese|käse|beverage|getränk|confection|nutrition|ernährung",
          ["food science", "nutrition", "food technology"], ["Lebensmittelwissenschaft", "Ernährung", "Lebensmitteltechnologie"],
          ["food analysis lab"], ["food analysis", "sensory testing"], ("food safety and labelling", "Lebensmittelsicherheit und Kennzeichnung")),
    Topic("agriculture", "agriculture", r"agri|\bfarm|landwirtschaft|\bcrops?\b|\bsoil|\bboden|plant breeding"
          r"|pflanzenzüchtung|agronom",
          ["agricultural science", "crop science", "soil science"], ["Agrarwissenschaft", "Pflanzenwissenschaften", "Bodenkunde"],
          ["experimental farm", "plant growth facility"], ["soil analysis"]),
    Topic("veterinary", "animal health", r"veterin|animal health|tiergesundheit|tiermedizin|livestock|nutztier|cattle"
          r"|\bcows?\b|\bdairy herd|\brind|\bpigs?\b|schwein|\bhorses?\b|pferd",
          ["veterinary medicine", "animal health", "veterinary diagnostics"], ["Veterinärmedizin", "Tiergesundheit", "Nutztiermedizin"],
          ["veterinary clinic", "animal diagnostics lab"], ["veterinary diagnostics"],
          ("veterinary medicinal products and animal welfare", "Tierarzneimittel und Tierschutz")),
    Topic("climate", "climate and environment", r"climate|klima|emission|\bco2\b|carbon|environment|umwelt|weather"
          r"|wetter|biodivers",
          ["climate science", "environmental monitoring", "climate risk"], ["Klimaforschung", "Umweltwissenschaften", "Klimarisiko"],
          ["climate data archive"], ["climate risk assessment"]),
    Topic("sustainability", "sustainability and circular economy", r"sustainab|nachhaltig|circular|kreislauf|recycl"
          r"|\bwaste|abfall|life[- ]cycle|ökobilanz",
          ["sustainability", "circular economy", "life cycle assessment", "waste reduction"],
          ["Nachhaltigkeit", "Kreislaufwirtschaft", "Ökobilanz", "Abfallvermeidung"],
          [], ["life cycle assessment", "sustainability consulting"]),
    Topic("energy", "energy", r"\benergy|energie|solar|photovolt|batter|hydrogen|wasserstoff|power grid|stromnetz"
          r"|heat pump|wärmepumpe",
          ["energy systems", "photovoltaics", "energy storage"], ["Energiesysteme", "Photovoltaik", "Energiespeicher"]),
    Topic("water", "water and natural hazards", r"\bwater|wasser|hydrolog|flood|hochwasser|natural hazard|naturgefahr",
          ["hydrology", "water resources", "natural hazards"], ["Hydrologie", "Wasserressourcen", "Naturgefahren"]),
    Topic("space", "space and geodesy", r"\bspace|satellit|orbit|aerospace|raumfahrt|\bgnss\b|\bgps\b|earth observation"
          r"|remote sensing|fernerkundung",
          ["space research", "satellite geodesy", "remote sensing", "GNSS"],
          ["Weltraumforschung", "Satellitengeodäsie", "Fernerkundung"], ["satellite laser ranging station"], ["orbit determination"]),
    Topic("mobility", "mobility and logistics", r"mobility|mobilität|transport|logistic|logistik|vehicle|fahrzeug"
          r"|railway|\bbahn\b|traffic|verkehr",
          ["transport and mobility", "logistics"], ["Mobilität", "Verkehr", "Logistik"]),
    Topic("finance", "finance and insurance", r"insur|versicher|\bbank|fintech|\bfinanc|finanz|actuar|aktuar",
          ["finance", "insurance economics", "risk modelling"], ["Finanzwissenschaft", "Versicherung", "Risikomodellierung"],
          [], [], ("financial market regulation", "Finanzmarktregulierung")),
    Topic("sport", "sport and exercise", r"\bsports?\b|fitness|athlet|exercise|bewegung",
          ["sport science", "exercise physiology"], ["Sportwissenschaft", "Trainingswissenschaft"], ["performance lab"]),
    Topic("construction", "construction and buildings", r"construction|building technology|gebäude|\bbau(en|stoff)"
          r"|architect|timber|\bholz|cement|zement|concrete|beton",
          ["building technology", "construction materials"], ["Bautechnik", "Baustoffe"]),
]


def find_topics(texts: list[tuple[str, float]], strong: str = "", top: int = 4,
                min_hits: float = 3) -> list[tuple[Topic, float]]:
    """Topics by weighted number of matches over (text, weight) pairs; a match in `strong`
    (title, description, headings) counts 3 times."""
    scored = []
    for t in TOPICS:
        n = sum(w * len(t.rx.findall(text)) for text, w in texts) + 3 * len(t.rx.findall(strong))
        if n >= min_hits:
            scored.append((t, round(n, 1)))
    scored.sort(key=lambda x: -x[1])
    if not scored:
        return []
    best = scored[0][1]
    return [(t, n) for t, n in scored[:top] if n >= 0.25 * best]
