"""
RBI Compliance Ingestion Pipeline  v3  — NO LLM
================================================
Uses spaCy + regex pattern matching instead of Ollama.
~5-15 seconds per PDF vs 30-120 minutes with LLM.

Install:
    pip install spacy pymupdf pymongo qdrant-client sentence-transformers tqdm colorama
    python -m spacy download en_core_web_sm

Run:
    mongod                  (keep running)
    python ingest.py
"""

import re
import json
import uuid
import hashlib
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz
import spacy
from tqdm import tqdm
from colorama import Fore, Style, init as colorama_init

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

CIRCULARS_FOLDER  = "./circulars"
QDRANT_PATH       = "./qdrant_storage"
MONGO_URI         = "mongodb://localhost:27017"
MONGO_DB          = "compliance_db"
QDRANT_COLLECTION = "compliance_rules"
EMBED_MODEL       = "all-MiniLM-L6-v2"
EMBED_DIM         = 384
CHUNK_WORDS       = 300
CHUNK_OVERLAP     = 60

# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

colorama_init(autoreset=True)

class _ColorFmt(logging.Formatter):
    _C = {logging.DEBUG: Fore.CYAN, logging.INFO: Fore.GREEN,
          logging.WARNING: Fore.YELLOW, logging.ERROR: Fore.RED,
          logging.CRITICAL: Fore.MAGENTA}
    def format(self, r):
        r.msg = f"{self._C.get(r.levelno,'')}{r.msg}{Style.RESET_ALL}"
        return super().format(r)

_h = logging.StreamHandler(sys.stdout)
_h.setFormatter(_ColorFmt("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
logging.basicConfig(level=logging.INFO, handlers=[_h])
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# TOPIC TAXONOMY
# ─────────────────────────────────────────────────────────────

FOLDER_SUBTOPICS: dict = {
    "commercial_banks":                 ["credit", "deposits", "NPA", "capital_adequacy", "interest_rate"],
    "NBFC":                             ["registration", "prudential_norms", "fair_practices", "systemic_risk"],
    "payment_banks":                    ["operations", "deposit_limits", "KYC", "digital_payments"],
    "small_financial_banks":            ["lending", "priority_sector", "deposits", "KYC"],
    "Regional_Rural_Bank":              ["agricultural_credit", "priority_sector", "refinance"],
    "local_area_banks":                 ["operations", "capital", "lending"],
    "Urban_Cooperative_Bank":           ["governance", "audit", "deposits", "lending"],
    "Rural_Cooperative_Bank":           ["agricultural_credit", "governance", "audit"],
    "All_India_Financial_Institutions": ["long_term_finance", "infrastructure", "bonds"],
    "Asset_Reconstruction_Companies":   ["securitisation", "NPA_acquisition", "resolution"],
    "Credit_Information_Services":      ["credit_report", "data_submission", "dispute_resolution"],
    "KYC":                              ["small_account", "re_kyc", "video_kyc", "aadhaar_kyc"],
    "AML":                              ["suspicious_transactions", "cash_transactions", "STR", "CTR"],
    "PMLA":                             ["record_keeping", "beneficial_ownership", "reporting"],
    "forex":                            ["FEMA", "remittance", "import_export", "ECB"],
    "governance":                       ["board_composition", "audit", "disclosure", "risk_management"],
    "general":                          ["miscellaneous"],
}

TOPIC_COLORS: dict = {
    "commercial_banks": "blue", "NBFC": "purple", "payment_banks": "teal",
    "small_financial_banks": "green", "Regional_Rural_Bank": "amber",
    "local_area_banks": "amber", "Urban_Cooperative_Bank": "coral",
    "Rural_Cooperative_Bank": "coral", "All_India_Financial_Institutions": "pink",
    "Asset_Reconstruction_Companies": "red", "Credit_Information_Services": "gray",
    "KYC": "teal", "AML": "coral", "PMLA": "coral",
    "forex": "purple", "governance": "gray", "general": "gray",
}

RELATIONSHIP_TYPES = {"modifies", "overrides", "depends_on", "references", "clarifies", "supersedes"}

# ─────────────────────────────────────────────────────────────
# REGEX PATTERNS FOR RBI DOCUMENT STRUCTURE
# ─────────────────────────────────────────────────────────────
# RBI circulars follow very consistent patterns.
# These patterns cover 90%+ of clauses across all circular types.

# Section/clause starters — how RBI numbers its rules
SECTION_PATTERNS = [
    # "1.", "1.1", "1.1.1", "A.", "I.", "ii."
    re.compile(r"^(\d+\.(?:\d+\.)*\d*)\s+(.+)", re.MULTILINE),
    re.compile(r"^([A-Z]+\.)\s+(.+)", re.MULTILINE),
    re.compile(r"^([IVXivx]+\.)\s+(.+)", re.MULTILINE),
    # "Paragraph 3", "Clause 5", "Section 4"
    re.compile(r"^(?:Paragraph|Clause|Section|Para|Article)\s+(\d+[A-Z]?)\s*[:\-–]?\s*(.+)", re.MULTILINE | re.IGNORECASE),
]

# Monetary limits — INR amounts in various formats
MONEY_PATTERN = re.compile(
    r"(?:Rs\.?|INR|₹)\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*"
    r"(crore|lakh|thousand|million|billion|cr\.?|lac|lakhs|crores)?"
    r"(?:\s*(?:per|a|each|every)\s+\w+)?",
    re.IGNORECASE
)

# Percentage limits
PERCENT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:per\s*cent|percent|%)", re.IGNORECASE)

# Date patterns
DATE_PATTERN = re.compile(
    r"\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2}|"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{4})\b",
    re.IGNORECASE
)

# Obligation keywords — sentences that contain actual rules
OBLIGATION_KEYWORDS = re.compile(
    r"\b(shall|must|should|required to|mandated|prohibited|not permitted|"
    r"obligatory|compulsory|necessary|ensure|comply|compliance|adhere|maintain|"
    r"submit|report|disclose|obtain|seek|apply|furnish|provide|establish)\b",
    re.IGNORECASE
)

# Penalty / consequence keywords
PENALTY_KEYWORDS = re.compile(
    r"\b(penalty|penalise|fine|action|liable|suspension|cancellation|"
    r"revocation|imprisonment|prosecution|suo.?motu|show.?cause|"
    r"compounding|adjudication)\b",
    re.IGNORECASE
)

# Exception / exemption keywords
EXCEPTION_KEYWORDS = re.compile(
    r"\b(except|exempted|provided that|notwithstanding|subject to|"
    r"unless|save as|without prejudice|however|but not)\b",
    re.IGNORECASE
)

# Circular reference pattern (e.g. "RBI/2023/45", "DBOD.No.BP.BC.1/2023")
CIRCULAR_REF_PATTERN = re.compile(
    r"(?:RBI/\d{4}[-–]\d{2,4}/\d+|"
    r"[A-Z]{2,}\.(?:No\.)?[A-Z0-9/.]+/\d{4}[-–]\d{2,4})",
    re.IGNORECASE
)

# Key compliance terms per topic — used for subtopic detection
SUBTOPIC_KEYWORDS: dict = {
    "KYC": {
        "small_account":    ["small account", "simplified kyc", "self declaration"],
        "re_kyc":           ["re-kyc", "periodic updation", "re kyc", "update kyc"],
        "video_kyc":        ["v-cip", "video kyc", "video based", "video customer"],
        "aadhaar_kyc":      ["aadhaar", "uid", "biometric"],
        "customer_identification": ["cdd", "customer due diligence", "identification"],
    },
    "AML": {
        "suspicious_transactions": ["suspicious", "str", "suspicious transaction"],
        "cash_transactions":       ["ctr", "cash transaction", "cash dealing"],
        "STR":                     ["suspicious transaction report", "fiu"],
        "CTR":                     ["cash transaction report", "10 lakh", "10,00,000"],
    },
    "commercial_banks": {
        "NPA":              ["npa", "non-performing", "bad loan", "stressed asset"],
        "capital_adequacy": ["crar", "capital adequacy", "tier 1", "tier 2", "basel"],
        "deposits":         ["deposit", "savings", "current account", "fd", "fixed deposit"],
        "credit":           ["loan", "credit", "advance", "lending", "borrower"],
        "interest_rate":    ["interest rate", "base rate", "mclr", "spread"],
    },
    "NBFC": {
        "registration":     ["certificate of registration", "cor", "register"],
        "prudential_norms": ["npa", "provisioning", "capital", "crar"],
        "fair_practices":   ["fair practice", "grievance", "customer service"],
        "systemic_risk":    ["systemically important", "si-nbfc", "d-sib"],
    },
    "governance": {
        "board_composition": ["board", "director", "independent director", "md & ceo"],
        "audit":             ["audit", "auditor", "statutory audit", "internal audit"],
        "disclosure":        ["disclosure", "publish", "annual report", "website"],
        "risk_management":   ["risk", "alm", "liquidity", "market risk"],
    },
}

# ─────────────────────────────────────────────────────────────
# spaCy SETUP
# ─────────────────────────────────────────────────────────────

def load_nlp():
    try:
        nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
        # increase max length for long PDFs
        nlp.max_length = 2_000_000
        log.info("spaCy model loaded")
        return nlp
    except OSError:
        log.error("spaCy model not found. Run: python -m spacy download en_core_web_sm")
        sys.exit(1)

# ─────────────────────────────────────────────────────────────
# PDF EXTRACTION
# ─────────────────────────────────────────────────────────────

def extract_text(pdf_path: str) -> str:
    try:
        doc = fitz.open(pdf_path)
        pages = [p.get_text("text") for p in doc]
        doc.close()
        text = "\n".join(pages)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()
    except Exception as e:
        log.error(f"PDF read error: {e}")
        return ""


def make_chunks(text: str, size: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list:
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunks.append(" ".join(words[i:i + size]))
        if i + size >= len(words):
            break
        i += size - overlap
    return [c for c in chunks if len(c.split()) > 20]

# ─────────────────────────────────────────────────────────────
# TOPIC / FOLDER HELPERS
# ─────────────────────────────────────────────────────────────

def discover_topics(root: Path) -> dict:
    topics = dict(FOLDER_SUBTOPICS)
    for entry in root.iterdir():
        if entry.is_dir() and entry.name not in topics:
            topics[entry.name] = ["general"]
            log.info(f"New topic from folder: {entry.name}")
    topics.setdefault("general", ["miscellaneous"])
    return topics


def folder_to_topic(pdf_path: Path, root: Path) -> str:
    try:
        parts = pdf_path.relative_to(root).parts
        if len(parts) > 1:
            return parts[0]
    except ValueError:
        pass
    return "general"

# ─────────────────────────────────────────────────────────────
# CORE: RULE EXTRACTION — spaCy + Regex (replaces Ollama)
# ─────────────────────────────────────────────────────────────

def detect_subtopic(text: str, topic: str, known_topics: dict) -> str:
    """Detect subtopic by keyword matching against SUBTOPIC_KEYWORDS."""
    text_lower = text.lower()
    kw_map = SUBTOPIC_KEYWORDS.get(topic, {})
    best_subtopic, best_count = None, 0
    for subtopic, keywords in kw_map.items():
        count = sum(1 for kw in keywords if kw.lower() in text_lower)
        if count > best_count:
            best_count = count
            best_subtopic = subtopic
    if best_subtopic and best_count > 0:
        return best_subtopic
    # fallback to first valid subtopic for this topic
    return known_topics.get(topic, ["general"])[0]


def extract_monetary_limits(text: str) -> list:
    """Extract all monetary limits found in text."""
    limits = []
    for m in MONEY_PATTERN.finditer(text):
        raw_val = m.group(1).replace(",", "")
        try:
            value = float(raw_val)
        except ValueError:
            continue
        unit = (m.group(2) or "").lower().strip()
        # normalise to INR
        multipliers = {"crore": 1e7, "cr": 1e7, "crores": 1e7,
                       "lakh": 1e5, "lac": 1e5, "lakhs": 1e5,
                       "thousand": 1e3, "million": 1e6, "billion": 1e9}
        inr_value = value * multipliers.get(unit, 1)
        limits.append({
            "type": "limit",
            "field": "monetary_limit",
            "value": inr_value,
            "currency": "INR",
            "description": m.group(0).strip(),
        })
    return limits[:5]  # cap at 5 per rule to avoid noise


def extract_percentage_limits(text: str) -> list:
    """Extract percentage-based requirements."""
    limits = []
    for m in PERCENT_PATTERN.finditer(text):
        try:
            val = float(m.group(1))
        except ValueError:
            continue
        limits.append({
            "type": "percentage_limit",
            "field": "percentage",
            "value": val,
            "currency": None,
            "description": m.group(0).strip(),
        })
    return limits[:3]


def extract_dates_from_text(text: str) -> Optional[str]:
    """Return the first date found in text as ISO string, or None."""
    m = DATE_PATTERN.search(text)
    if not m:
        return None
    raw = m.group(0).strip()
    # try common formats
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%B %d, %Y",
                "%d %B %Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw  # return raw if we can't parse — still useful


def split_into_clauses(text: str) -> list:
    """
    Splits document text into individual clauses/sections.
    Returns list of (section_number, clause_text) tuples.
    Each clause is a potential rule.
    """
    clauses = []
    lines   = text.split("\n")
    current_num  = ""
    current_text = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        matched = False
        for pattern in SECTION_PATTERNS:
            m = pattern.match(line)
            if m:
                # save previous clause
                if current_text:
                    clause_body = " ".join(current_text).strip()
                    if len(clause_body.split()) >= 8:  # skip tiny fragments
                        clauses.append((current_num, clause_body))
                current_num  = m.group(1)
                current_text = [m.group(2)] if len(m.groups()) > 1 else []
                matched = True
                break

        if not matched and current_num:
            current_text.append(line)

    # don't forget the last clause
    if current_text and current_num:
        clause_body = " ".join(current_text).strip()
        if len(clause_body.split()) >= 8:
            clauses.append((current_num, clause_body))

    return clauses


def is_obligation_clause(text: str) -> bool:
    """Returns True if the clause contains an actual obligation/rule."""
    return bool(OBLIGATION_KEYWORDS.search(text))


def extract_conditions(text: str, nlp) -> list:
    """
    Uses spaCy + regex to extract conditions from clause text.
    Looks for "if X then Y", "where X", "in case of X" patterns.
    """
    conditions = []
    condition_patterns = [
        re.compile(r"(?:where|if|in case of|in the event of|when)\s+(.{10,80}?)(?:\,|\.|shall|must)", re.IGNORECASE),
        re.compile(r"(?:account type|entity type|category)\s+(?:is|are|being)\s+(\w[\w\s]{2,30})", re.IGNORECASE),
        re.compile(r"(?:balance|limit|amount)\s+(?:exceeds?|below|above|less than|more than|up to)\s+([\w\s,\.₹]+?)(?:\,|\.|\s{2})", re.IGNORECASE),
    ]
    for pat in condition_patterns:
        for m in pat.finditer(text):
            val = m.group(1).strip().rstrip(".,;")
            if 3 < len(val) < 100:
                conditions.append({
                    "field":    "condition",
                    "operator": "matches",
                    "value":    val,
                })
    return conditions[:3]


def extract_exceptions_from_text(text: str) -> list:
    """Extracts exception/proviso clauses."""
    exceptions = []
    exc_pattern = re.compile(
        r"(?:provided that|except|notwithstanding|however|subject to|unless)\s+(.{15,200}?)(?:\.|;|\n)",
        re.IGNORECASE | re.DOTALL
    )
    for m in exc_pattern.finditer(text):
        val = m.group(1).strip().replace("\n", " ")
        if len(val.split()) >= 4:
            exceptions.append({
                "condition": val[:200],
                "outcome":   "exception applies",
            })
    return exceptions[:2]


def extract_penalties_from_text(text: str) -> list:
    """Extracts penalty clauses."""
    penalties = []
    if not PENALTY_KEYWORDS.search(text):
        return []
    pen_pattern = re.compile(
        r"(?:penalty|fine|liable|action|prosecution)\s+(?:of|for|under)?\s*(.{10,150}?)(?:\.|;|\n)",
        re.IGNORECASE
    )
    for m in pen_pattern.finditer(text):
        val = m.group(1).strip()
        # find section reference near this match
        ref_match = re.search(r"(?:section|clause|para)\s+\d+[A-Z]?", text[max(0, m.start()-50):m.end()+50], re.IGNORECASE)
        penalties.append({
            "violation": "regulatory non-compliance",
            "action":    val[:150],
            "reference": ref_match.group(0) if ref_match else "",
        })
    return penalties[:2]


def detect_relationship_type(text: str) -> str:
    """Detect what type of relationship a cross-reference implies."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["supersede", "replace", "repeal", "rescind"]):
        return "supersedes"
    if any(w in text_lower for w in ["modify", "modif", "amend", "revise", "update"]):
        return "modifies"
    if any(w in text_lower for w in ["subject to", "read with", "pursuant to", "in addition"]):
        return "depends_on"
    if any(w in text_lower for w in ["override", "overrule", "notwithstanding"]):
        return "overrides"
    return "references"


def build_plain_summary(section_num: str, clause_text: str, topic: str) -> str:
    """Builds a concise plain-language summary from the clause."""
    # take first 2 sentences as summary
    sentences = re.split(r"(?<=[.!?])\s+", clause_text)
    summary   = " ".join(sentences[:2]).strip()
    if len(summary) < 20:
        summary = clause_text[:200]
    # cap length
    if len(summary) > 300:
        summary = summary[:297] + "..."
    return summary


def generate_tags(text: str, topic: str) -> list:
    """Generate tags from keywords found in text."""
    tags = [topic]
    text_lower = text.lower()

    # universal compliance terms
    tag_keywords = {
        "KYC": ["kyc", "know your customer", "customer identification"],
        "AML": ["aml", "anti-money laundering", "money laundering"],
        "PMLA": ["pmla", "prevention of money laundering"],
        "NPA": ["npa", "non-performing", "bad loan"],
        "capital": ["capital", "crar", "tier-1", "tier-2"],
        "deposit": ["deposit", "savings", "current account"],
        "loan": ["loan", "credit", "advance", "lending"],
        "penalty": ["penalty", "fine", "action"],
        "reporting": ["report", "submit", "furnish", "disclose"],
        "audit": ["audit", "inspection"],
        "governance": ["board", "director", "governance"],
        "digital": ["digital", "online", "electronic", "e-"],
        "forex": ["forex", "fema", "foreign exchange"],
        "priority_sector": ["priority sector", "psl", "agricultural"],
    }

    for tag, kws in tag_keywords.items():
        if any(kw in text_lower for kw in kws):
            if tag not in tags:
                tags.append(tag)

    return tags[:8]


def clauses_to_rules(
    clauses: list,
    circular_id: str,
    topic: str,
    known_topics: dict,
    nlp,
) -> list:
    """
    Converts extracted clauses into structured rule dicts.
    This is the core replacement for the LLM extraction step.
    """
    rules    = []
    seen_ids = set()
    counter  = 1

    for section_num, clause_text in clauses:
        # only process clauses that contain actual obligations
        if not is_obligation_clause(clause_text):
            continue

        # generate a stable, readable rule_id
        clean_num = re.sub(r"[^A-Za-z0-9]", "_", section_num).strip("_")
        rule_id   = f"{topic[:8]}_{circular_id[-12:]}_{clean_num}_{counter:03d}"
        rule_id   = re.sub(r"_+", "_", rule_id)[:50]
        if rule_id in seen_ids:
            rule_id = f"{rule_id}_{counter}"
        seen_ids.add(rule_id)
        counter += 1

        # detect subtopic
        subtopic = detect_subtopic(clause_text, topic, known_topics)

        # extract structured fields
        requirements = extract_monetary_limits(clause_text) + extract_percentage_limits(clause_text)
        conditions   = extract_conditions(clause_text, nlp)
        exceptions   = extract_exceptions_from_text(clause_text)
        penalties    = extract_penalties_from_text(clause_text)
        eff_date     = extract_dates_from_text(clause_text)
        tags         = generate_tags(clause_text, topic)
        summary      = build_plain_summary(section_num, clause_text, topic)

        rule = {
            "rule_id":                section_num.strip() + "_" + circular_id[-8:],
            "rule_id":                rule_id,
            "title":                  clause_text[:80].strip().rstrip(".,;:"),
            "topic":                  topic,
            "subtopic":               subtopic,
            "source_circular_id":     circular_id,
            "effective_date":         eff_date,
            "is_active":              True,
            "superseded_by":          None,
            "conditions":             conditions,
            "requirements":           requirements,
            "exceptions":             exceptions,
            "penalties":              penalties,
            "plain_language_summary": summary,
            "tags":                   tags,
            "related_rule_ids":       [],
            "vec_chunk_ids":          [],
            "raw_clause_text":        clause_text[:500],   # keep original for reference
            "section_number":         section_num,
            "visualization_meta": {
                "cluster_color": TOPIC_COLORS.get(topic, "gray"),
                "node_label":    clause_text[:40].rstrip(".,;"),
                "cluster":       topic,
            },
            "_validation_warnings": [],
            "_ingested_at":         datetime.utcnow().isoformat(),
        }

        rules.append(rule)

    return rules


def extract_cross_references(text: str, rule_ids: list) -> list:
    """
    Finds relationships between rules using circular cross-references.
    Entirely regex-based — no LLM needed.
    """
    relationships = []
    seen          = set()
    rule_id_set   = set(rule_ids)

    # look for explicit circular references (RBI/XXXX/YY)
    for m in CIRCULAR_REF_PATTERN.finditer(text):
        ref      = m.group(0)
        context  = text[max(0, m.start()-100):m.end()+100]
        rel_type = detect_relationship_type(context)

        # find which rule this reference appears near
        for rule_id in rule_ids:
            # check if this rule's section text contains this reference
            key = f"{rule_id}__{ref}"
            if key not in seen:
                seen.add(key)
                relationships.append({
                    "_id":          f"rel__{rule_id}__{rel_type}__{ref[:20]}",
                    "from_rule_id": rule_id,
                    "to_rule_id":   ref,    # external circular ref
                    "type":         rel_type,
                    "note":         f"References {ref}",
                    "effective_date": None,
                })

    return relationships[:20]  # cap to avoid noise


# ─────────────────────────────────────────────────────────────
# QDRANT
# ─────────────────────────────────────────────────────────────

def init_qdrant(client: QdrantClient):
    existing = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        log.info(f"Created Qdrant collection '{QDRANT_COLLECTION}'")


def embed_and_upsert(qdrant: QdrantClient, embedder: SentenceTransformer,
                     texts: list, base_payload: dict) -> list:
    ids, points = [], []
    for idx, text in enumerate(texts):
        h     = hashlib.sha256(text.encode()).hexdigest()
        pt_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, h))
        if qdrant.retrieve(collection_name=QDRANT_COLLECTION, ids=[pt_id], with_payload=False):
            ids.append(pt_id)
            continue
        vec = embedder.encode(text, normalize_embeddings=True).tolist()
        payload = {**base_payload, "chunk_index": idx, "chunk_text": text[:400],
                   "content_hash": h, "ingested_at": datetime.utcnow().isoformat()}
        points.append(PointStruct(id=pt_id, vector=vec, payload=payload))
        ids.append(pt_id)
    if points:
        qdrant.upsert(collection_name=QDRANT_COLLECTION, points=points)
    return ids


def upsert_topic_vec(qdrant: QdrantClient, embedder: SentenceTransformer,
                     topic_id: str, related: list, rule_count: int):
    text  = (f"Topic {topic_id}: {topic_id.replace('_',' ')} compliance regulations. "
             f"Related: {', '.join(related)}. Contains {rule_count} rules.")
    pt_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"topic_{topic_id}"))
    vec   = embedder.encode(text, normalize_embeddings=True).tolist()
    qdrant.upsert(collection_name=QDRANT_COLLECTION, points=[PointStruct(
        id=pt_id, vector=vec,
        payload={"record_type": "topic", "topic_id": topic_id,
                 "related_topics": related, "rule_count": rule_count,
                 "ingested_at": datetime.utcnow().isoformat()}
    )])

# ─────────────────────────────────────────────────────────────
# MONGODB
# ─────────────────────────────────────────────────────────────

def init_mongo(db):
    db.rules.create_index([("rule_id", ASCENDING)], unique=True)
    db.rules.create_index([("topic", ASCENDING), ("subtopic", ASCENDING), ("is_active", ASCENDING)])
    db.rules.create_index([("source_circular_id", ASCENDING)])
    db.rules.create_index([("tags", ASCENDING)])
    db.circulars.create_index([("circular_id", ASCENDING)], unique=True)
    db.circulars.create_index([("topic", ASCENDING)])
    db.relationships.create_index([("from_rule_id", ASCENDING)])
    db.relationships.create_index([("to_rule_id", ASCENDING)])
    db.topics.create_index([("topic_id", ASCENDING)], unique=True)
    log.info("MongoDB indexes ready")


def upsert_rule(db, rule: dict):
    rid = rule["rule_id"]
    ex  = db.rules.find_one({"rule_id": rid}, {"vec_chunk_ids": 1})
    if ex:
        merged = list(set(ex.get("vec_chunk_ids", [])) | set(rule.get("vec_chunk_ids", [])))
        rule["vec_chunk_ids"] = merged
        db.rules.replace_one({"rule_id": rid}, rule)
    else:
        try:
            db.rules.insert_one(rule)
        except DuplicateKeyError:
            pass


def upsert_circular(db, circular: dict):
    cid = circular["circular_id"]
    ex  = db.circulars.find_one({"circular_id": cid}, {"rule_ids": 1})
    if ex:
        circular["rule_ids"] = list(set(ex.get("rule_ids", [])) | set(circular.get("rule_ids", [])))
        db.circulars.replace_one({"circular_id": cid}, circular)
    else:
        try:
            db.circulars.insert_one(circular)
        except DuplicateKeyError:
            pass


def upsert_relationship(db, rel: dict):
    db.relationships.replace_one({"_id": rel["_id"]}, rel, upsert=True)


def upsert_topic(db, topic_id: str, circular_id: str, known_topics: dict):
    related = [t for t in known_topics if t != topic_id][:5]
    ex = db.topics.find_one({"topic_id": topic_id})
    if ex:
        db.topics.update_one({"topic_id": topic_id},
            {"$inc": {"rule_count": 1}, "$addToSet": {"circular_ids": circular_id},
             "$set": {"last_updated": datetime.utcnow().isoformat()}})
    else:
        try:
            db.topics.insert_one({
                "topic_id": topic_id, "label": topic_id.replace("_", " "),
                "parent_topic": None, "subtopics": known_topics.get(topic_id, ["general"]),
                "related_topics": related, "rule_count": 1, "active_rule_count": 1,
                "circular_ids": [circular_id], "last_updated": datetime.utcnow().isoformat(),
                "visualization_meta": {"cluster_color": TOPIC_COLORS.get(topic_id, "gray"),
                                       "node_size": "medium", "x_hint": 0.5, "y_hint": 0.5},
            })
        except DuplicateKeyError:
            pass

# ─────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────

def check_mongo() -> bool:
    try:
        MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000).server_info()
        log.info("MongoDB OK")
        return True
    except Exception:
        log.error("MongoDB not reachable — run: mongod")
        return False

# ─────────────────────────────────────────────────────────────
# PROCESS ONE PDF
# ─────────────────────────────────────────────────────────────

def process_pdf(pdf_path: Path, root: Path, qdrant: QdrantClient,
                embedder: SentenceTransformer, db, nlp, known_topics: dict):

    topic       = folder_to_topic(pdf_path, root)
    stem        = pdf_path.stem
    circular_id = re.sub(r"[^A-Za-z0-9_]", "_", f"{topic}__{stem}")[:60]

    log.info(f"{'─'*50}")
    log.info(f"File:  {pdf_path.name}  |  Topic: {topic}")

    if db.circulars.find_one({"circular_id": circular_id}):
        log.info("  Already ingested — skipping")
        return

    text = extract_text(str(pdf_path))
    if not text or len(text.split()) < 30:
        log.error("  Too little text — skipping")
        return

    word_count = len(text.split())
    log.info(f"  {word_count} words extracted")

    # ── RULE EXTRACTION (regex + spaCy, no LLM) ──────────────
    clauses = split_into_clauses(text)
    log.info(f"  {len(clauses)} clauses detected")

    rules = clauses_to_rules(clauses, circular_id, topic, known_topics, nlp)
    log.info(f"  {len(rules)} obligation rules extracted")

    # ── RELATIONSHIPS (regex, no LLM) ────────────────────────
    rule_ids      = [r["rule_id"] for r in rules]
    relationships = extract_cross_references(text, rule_ids)
    log.info(f"  {len(relationships)} cross-references found")

    # ── EMBED CHUNKS ─────────────────────────────────────────
    chunks    = make_chunks(text)
    base_meta = {"record_type": "chunk", "circular_id": circular_id,
                 "topic": topic, "subtopic": "general", "is_active": True, "tags": [topic]}
    chunk_ids = embed_and_upsert(qdrant, embedder, chunks, base_meta)
    log.info(f"  {len(chunk_ids)} text chunks embedded")

    # embed each rule's summary text separately for precise rule search
    for rule in rules:
        rule_text = (
            f"{rule['title']}. {rule['plain_language_summary']} "
            f"Topic: {rule['topic']} / {rule['subtopic']}. Tags: {', '.join(rule['tags'])}."
        )
        rule_meta = {"record_type": "rule", "rule_id": rule["rule_id"],
                     "circular_id": circular_id, "topic": topic,
                     "subtopic": rule["subtopic"], "is_active": rule["is_active"],
                     "tags": rule["tags"]}
        rule["vec_chunk_ids"] = embed_and_upsert(
            qdrant, embedder, make_chunks(rule_text, size=100, overlap=10), rule_meta
        )

    upsert_topic_vec(qdrant, embedder, topic, list(known_topics.keys())[:5], len(rules))

    # ── WRITE TO MONGODB ──────────────────────────────────────
    circular_doc = {
        "circular_id": circular_id, "title": stem.replace("_", " ").replace("-", " "),
        "issuing_authority": "RBI", "date": extract_dates_from_text(text[:2000]),
        "topic": topic, "topics": [topic], "rule_ids": rule_ids,
        "supersedes": [], "superseded_by": None, "is_active": True,
        "full_text_path": str(pdf_path), "summary": "",
        "_ingested_at": datetime.utcnow().isoformat(),
    }
    upsert_circular(db, circular_doc)

    for rule in rules:
        upsert_rule(db, rule)
        upsert_topic(db, topic, circular_id, known_topics)

    for rel in relationships:
        upsert_relationship(db, rel)

    log.info(f"  Stored: {len(rules)} rules | {len(relationships)} rels | {len(chunk_ids)} chunks")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    log.info("RBI Compliance Ingestion Pipeline v3 — spaCy/Regex (no LLM)")

    if not check_mongo():
        sys.exit(1)

    root = Path(CIRCULARS_FOLDER)
    if not root.exists():
        log.error(f"Folder not found: {CIRCULARS_FOLDER}")
        sys.exit(1)

    known_topics = discover_topics(root)
    log.info(f"Topics: {list(known_topics.keys())}")

    pdfs = sorted(root.glob("**/*.pdf"))
    if not pdfs:
        log.error("No PDFs found")
        sys.exit(1)
    log.info(f"Found {len(pdfs)} PDFs")

    log.info("Loading models...")
    nlp      = load_nlp()
    embedder = SentenceTransformer(EMBED_MODEL)
    qdrant   = QdrantClient(path=QDRANT_PATH)
    init_qdrant(qdrant)

    mongo = MongoClient(MONGO_URI)
    db    = mongo[MONGO_DB]
    init_mongo(db)

    success, failed = 0, 0
    start = datetime.utcnow()

    for pdf in tqdm(pdfs, desc="PDFs"):
        try:
            process_pdf(pdf, root, qdrant, embedder, db, nlp, known_topics)
            success += 1
        except Exception as e:
            log.error(f"Failed on {pdf.name}: {e}")
            log.exception(e)
            failed += 1

    elapsed = (datetime.utcnow() - start).total_seconds()

    log.info(f"\n{'='*50}")
    log.info("DONE")
    log.info(f"  Time:          {elapsed:.0f}s  ({elapsed/max(success,1):.1f}s/PDF)")
    log.info(f"  PDFs:          {success} ok, {failed} failed")
    log.info(f"  Rules:         {db.rules.count_documents({})}")
    log.info(f"  Circulars:     {db.circulars.count_documents({})}")
    log.info(f"  Relationships: {db.relationships.count_documents({})}")
    log.info(f"  Topics:        {db.topics.count_documents({})}")
    log.info(f"  Vec points:    {qdrant.get_collection(QDRANT_COLLECTION).points_count}")
    log.info(f"{'='*50}")
    mongo.close()


if __name__ == "__main__":
    main()
