"""
functions.py  —  RBI Compliance Assistant  (Backend Logic)
===========================================================
Serves four features:
  1. Chat / RAG query answering        → answer_query()
  2. Visualization data                → get_visualization_data()
  3. Upload circular (PDF ingest)      → ingest_pdf_circular()
  4. Compliance checker                → check_compliance()

DB layout (from ingest pipeline):
  MongoDB  compliance_db
    ├── rules          { rule_id, title, topic, subtopic, conditions[], requirements[],
    │                    exceptions[], penalties[], plain_language_summary, tags[],
    │                    is_active, effective_date, source_circular_id, vec_chunk_ids[] }
    ├── circulars      { circular_id, title, topic, topics[], rule_ids[], is_active, date }
    ├── relationships  { _id, from_rule_id, to_rule_id, type, note }
    └── topics         { topic_id, label, subtopics[], related_topics[],
                         rule_count, circular_ids[], visualization_meta{} }

  Qdrant  compliance_rules  (local path)
    payload fields: record_type, rule_id, circular_id, topic, subtopic,
                    is_active, tags[], chunk_text, content_hash
"""

import os
import re
import json
import uuid
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz                                  # PyMuPDF
import spacy
from dotenv import load_dotenv
from google import genai
from google.genai import types
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

load_dotenv()
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL     = "gemini-flash-latest"
QDRANT_PATH      = os.getenv("QDRANT_PATH", "./qdrant_storage")
MONGO_URI        = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB         = os.getenv("MONGO_DB", "compliance_db")
COLLECTION_NAME  = "compliance_rules"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
EMBED_DIM        = 384
TOP_K            = 6
CHUNK_WORDS      = 300
CHUNK_OVERLAP    = 60

# ─────────────────────────────────────────────────────────────
# SINGLETONS  (lazy init — only created when first used)
# ─────────────────────────────────────────────────────────────

_gemini_client  = None
_embedder       = None
_qdrant         = None
_mongo_client   = None
_db             = None
_nlp            = None


def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set in environment")
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL_NAME)
    return _embedder


def _get_qdrant():
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantClient(path=QDRANT_PATH)
        _ensure_qdrant_collection(_qdrant)
    return _qdrant


def _get_db():
    global _mongo_client, _db
    if _db is None:
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        _db = _mongo_client[MONGO_DB]
    return _db


def _get_nlp():
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
            _nlp.max_length = 2_000_000
        except OSError:
            log.warning("spaCy model not found. Run: python -m spacy download en_core_web_sm")
            _nlp = None
    return _nlp


def _ensure_qdrant_collection(client: QdrantClient):
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        log.info(f"Created Qdrant collection: {COLLECTION_NAME}")


# ─────────────────────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────────────────────

def _safe(v, default=""):
    return v if v is not None else default


def _make_chunks(text: str, size: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP):
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunks.append(" ".join(words[i:i + size]))
        if i + size >= len(words):
            break
        i += size - overlap
    return [c for c in chunks if len(c.split()) > 15]


def _embed_and_upsert(texts: list, base_payload: dict) -> list:
    """Deduplicated upsert to Qdrant. Returns list of point IDs."""
    qdrant   = _get_qdrant()
    embedder = _get_embedder()
    ids, points = [], []
    for idx, text in enumerate(texts):
        h     = hashlib.sha256(text.encode()).hexdigest()
        pt_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, h))
        existing = qdrant.retrieve(collection_name=COLLECTION_NAME, ids=[pt_id], with_payload=False)
        if existing:
            ids.append(pt_id)
            continue
        vec = embedder.encode(text, normalize_embeddings=True).tolist()
        payload = {**base_payload, "chunk_index": idx, "chunk_text": text[:400],
                   "content_hash": h, "ingested_at": datetime.utcnow().isoformat()}
        points.append(PointStruct(id=pt_id, vector=vec, payload=payload))
        ids.append(pt_id)
    if points:
        qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
    return ids


# ─────────────────────────────────────────────────────────────
# TOPIC TAXONOMY  (mirrors ingest pipeline)
# ─────────────────────────────────────────────────────────────

FOLDER_SUBTOPICS = {
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

TOPIC_COLORS = {
    "commercial_banks": "#378ADD", "NBFC": "#7F77DD", "payment_banks": "#1D9E75",
    "small_financial_banks": "#639922", "Regional_Rural_Bank": "#BA7517",
    "local_area_banks": "#BA7517", "Urban_Cooperative_Bank": "#D85A30",
    "Rural_Cooperative_Bank": "#D85A30", "All_India_Financial_Institutions": "#D4537E",
    "Asset_Reconstruction_Companies": "#E24B4A", "Credit_Information_Services": "#888780",
    "KYC": "#1D9E75", "AML": "#D85A30", "PMLA": "#D85A30",
    "forex": "#7F77DD", "governance": "#888780", "general": "#888780",
}

# ─────────────────────────────────────────────────────────────
# REGEX patterns (same as ingest pipeline)
# ─────────────────────────────────────────────────────────────

SECTION_PATTERNS = [
    re.compile(r"^(\d+\.(?:\d+\.)*\d*)\s+(.+)", re.MULTILINE),
    re.compile(r"^([A-Z]+\.)\s+(.+)", re.MULTILINE),
    re.compile(r"^(?:Paragraph|Clause|Section|Para|Article)\s+(\d+[A-Z]?)\s*[:\-–]?\s*(.+)", re.MULTILINE | re.IGNORECASE),
]
OBLIGATION_KW  = re.compile(r"\b(shall|must|required to|mandated|prohibited|not permitted|obligatory|compulsory|ensure|comply|compliance|adhere|maintain|submit|report|disclose|obtain|furnish|provide|establish)\b", re.IGNORECASE)
MONEY_PATTERN  = re.compile(r"(?:Rs\.?|INR|₹)\s*(\d[\d,]*(?:\.\d+)?)\s*(crore|lakh|thousand|cr\.?|lac|lakhs|crores)?", re.IGNORECASE)
PERCENT_PAT    = re.compile(r"(\d+(?:\.\d+)?)\s*(?:per\s*cent|percent|%)", re.IGNORECASE)
DATE_PAT       = re.compile(r"\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b", re.IGNORECASE)
CIRCULAR_REF   = re.compile(r"(?:RBI/\d{4}[-–]\d{2,4}/\d+|[A-Z]{2,}\.(?:No\.)?[A-Z0-9/.]+/\d{4}[-–]\d{2,4})", re.IGNORECASE)

SUBTOPIC_KW = {
    "KYC":              {"small_account": ["small account","simplified kyc"],"re_kyc": ["re-kyc","re kyc","periodic updation"],"video_kyc": ["v-cip","video kyc","video based"],"aadhaar_kyc": ["aadhaar","uid","biometric"]},
    "AML":              {"suspicious_transactions": ["suspicious","str"],"cash_transactions": ["ctr","cash transaction"]},
    "commercial_banks": {"NPA": ["npa","non-performing","bad loan"],"capital_adequacy": ["crar","capital adequacy","tier 1","tier 2"],"deposits": ["deposit","savings","fixed deposit"],"credit": ["loan","credit","advance"],"interest_rate": ["interest rate","base rate","mclr"]},
    "NBFC":             {"registration": ["certificate of registration","cor"],"prudential_norms": ["npa","provisioning","crar"],"fair_practices": ["fair practice","grievance"],"systemic_risk": ["systemically important","si-nbfc"]},
    "governance":       {"board_composition": ["board","director","independent director"],"audit": ["audit","auditor"],"disclosure": ["disclosure","publish","annual report"],"risk_management": ["risk","alm","liquidity"]},
}


def _detect_subtopic(text: str, topic: str) -> str:
    text_lower = text.lower()
    kw_map     = SUBTOPIC_KW.get(topic, {})
    best, best_n = None, 0
    for sub, kws in kw_map.items():
        n = sum(1 for k in kws if k in text_lower)
        if n > best_n:
            best_n, best = n, sub
    if best and best_n > 0:
        return best
    return FOLDER_SUBTOPICS.get(topic, ["general"])[0]


def _extract_date(text: str) -> Optional[str]:
    m = DATE_PAT.search(text)
    if not m:
        return None
    raw = m.group(0).strip()
    for fmt in ("%d/%m/%Y","%d-%m-%Y","%Y-%m-%d","%B %d, %Y","%d %B %Y","%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return raw


def _extract_requirements(text: str) -> list:
    reqs = []
    for m in MONEY_PATTERN.finditer(text):
        raw = m.group(1).replace(",","")
        try:
            val = float(raw)
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        mult = {"crore":1e7,"cr":1e7,"crores":1e7,"lakh":1e5,"lac":1e5,"lakhs":1e5,"thousand":1e3}
        reqs.append({"type":"limit","field":"monetary_limit","value":val*mult.get(unit,1),"currency":"INR","description":m.group(0).strip()})
    for m in PERCENT_PAT.finditer(text):
        try:
            reqs.append({"type":"percentage_limit","field":"percentage","value":float(m.group(1)),"currency":None,"description":m.group(0).strip()})
        except ValueError:
            pass
    return reqs[:5]


def _extract_tags(text: str, topic: str) -> list:
    tags = [topic]
    tl   = text.lower()
    kw_tags = {"KYC":["kyc","know your customer"],"AML":["aml","anti-money laundering"],"NPA":["npa","non-performing"],"capital":["capital","crar"],"deposit":["deposit","savings"],"loan":["loan","credit","advance"],"penalty":["penalty","fine"],"reporting":["report","submit","furnish"],"audit":["audit"],"governance":["board","director"],"digital":["digital","online","electronic"],"forex":["forex","fema","foreign exchange"],"priority_sector":["priority sector","psl"]}
    for tag, kws in kw_tags.items():
        if tag not in tags and any(k in tl for k in kws):
            tags.append(tag)
    return tags[:8]


def _split_clauses(text: str) -> list:
    clauses, lines = [], text.split("\n")
    cur_num, cur_text = "", []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        matched = False
        for pat in SECTION_PATTERNS:
            m = pat.match(line)
            if m:
                if cur_text:
                    body = " ".join(cur_text).strip()
                    if len(body.split()) >= 8:
                        clauses.append((cur_num, body))
                cur_num  = m.group(1)
                cur_text = [m.group(2)] if len(m.groups()) > 1 else []
                matched  = True
                break
        if not matched and cur_num:
            cur_text.append(line)
    if cur_text and cur_num:
        body = " ".join(cur_text).strip()
        if len(body.split()) >= 8:
            clauses.append((cur_num, body))
    return clauses


def _clauses_to_rules(clauses: list, circular_id: str, topic: str) -> list:
    rules, seen, ctr = [], set(), 1
    for sec_num, clause_text in clauses:
        if not OBLIGATION_KW.search(clause_text):
            continue
        clean = re.sub(r"[^A-Za-z0-9]","_",sec_num).strip("_")
        rid   = re.sub(r"_+","_",f"{topic[:8]}_{circular_id[-12:]}_{clean}_{ctr:03d}")[:50]
        if rid in seen:
            rid = f"{rid}_{ctr}"
        seen.add(rid)
        ctr  += 1
        sents = re.split(r"(?<=[.!?])\s+", clause_text)
        summary = " ".join(sents[:2])[:300]
        rules.append({
            "rule_id":                rid,
            "title":                  clause_text[:80].rstrip(".,;:"),
            "topic":                  topic,
            "subtopic":               _detect_subtopic(clause_text, topic),
            "source_circular_id":     circular_id,
            "effective_date":         _extract_date(clause_text),
            "is_active":              True,
            "superseded_by":          None,
            "conditions":             [],
            "requirements":           _extract_requirements(clause_text),
            "exceptions":             [],
            "penalties":              [],
            "plain_language_summary": summary,
            "tags":                   _extract_tags(clause_text, topic),
            "related_rule_ids":       [],
            "vec_chunk_ids":          [],
            "raw_clause_text":        clause_text[:500],
            "section_number":         sec_num,
            "visualization_meta":     {"cluster_color": TOPIC_COLORS.get(topic,"#888780"),"node_label":clause_text[:40].rstrip(".,;"),"cluster":topic},
            "_validation_warnings":   [],
            "_ingested_at":           datetime.utcnow().isoformat(),
        })
    return rules


# ─────────────────────────────────────────────────────────────
# MONGODB UPSERT HELPERS
# ─────────────────────────────────────────────────────────────

def _upsert_rule(rule: dict):
    db  = _get_db()
    rid = rule["rule_id"]
    ex  = db.rules.find_one({"rule_id": rid}, {"vec_chunk_ids":1})
    if ex:
        merged = list(set(ex.get("vec_chunk_ids",[]))|set(rule.get("vec_chunk_ids",[])))
        rule["vec_chunk_ids"] = merged
        db.rules.replace_one({"rule_id": rid}, rule)
    else:
        try:
            db.rules.insert_one(rule)
        except DuplicateKeyError:
            pass


def _upsert_circular(circular: dict):
    db  = _get_db()
    cid = circular["circular_id"]
    ex  = db.circulars.find_one({"circular_id": cid}, {"rule_ids":1})
    if ex:
        circular["rule_ids"] = list(set(ex.get("rule_ids",[]))|set(circular.get("rule_ids",[])))
        db.circulars.replace_one({"circular_id": cid}, circular)
    else:
        try:
            db.circulars.insert_one(circular)
        except DuplicateKeyError:
            pass


def _upsert_topic(topic_id: str, circular_id: str):
    db      = _get_db()
    related = [t for t in FOLDER_SUBTOPICS if t != topic_id][:5]
    ex      = db.topics.find_one({"topic_id": topic_id})
    if ex:
        db.topics.update_one({"topic_id": topic_id},
            {"$inc":{"rule_count":1},"$addToSet":{"circular_ids":circular_id},
             "$set":{"last_updated":datetime.utcnow().isoformat()}})
    else:
        try:
            db.topics.insert_one({
                "topic_id": topic_id, "label": topic_id.replace("_"," "),
                "parent_topic": None, "subtopics": FOLDER_SUBTOPICS.get(topic_id,["general"]),
                "related_topics": related, "rule_count":1, "active_rule_count":1,
                "circular_ids":[circular_id], "last_updated":datetime.utcnow().isoformat(),
                "visualization_meta":{"cluster_color":TOPIC_COLORS.get(topic_id,"#888780"),"node_size":"medium","x_hint":0.5,"y_hint":0.5},
            })
        except DuplicateKeyError:
            pass


# ─────────────────────────────────────────────────────────────
# 1. CHAT / QUERY  ANSWERING
# ─────────────────────────────────────────────────────────────

def _retrieve_rag_context(query: str, topic_filter: Optional[str] = None) -> list[dict]:
    """Semantic search in Qdrant. Optionally filter by topic."""
    try:
        qdrant   = _get_qdrant()
        embedder = _get_embedder()
        vec      = embedder.encode(query, normalize_embeddings=True).tolist()

        filters = None
        if topic_filter:
            filters = Filter(must=[FieldCondition(key="topic", match=MatchValue(value=topic_filter))])

        results = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=vec,
            limit=TOP_K,
            query_filter=filters,
        )
        return [hit.payload for hit in results.points if hit.payload]
    except Exception as e:
        log.warning(f"RAG retrieval error: {e}")
        return []


def _fetch_related_rules(context_chunks: list[dict], query: str) -> list[dict]:
    """From RAG hits, fetch full rule documents from MongoDB."""
    db = _get_db()
    rule_ids = list({c.get("rule_id") for c in context_chunks if c.get("rule_id") and c.get("record_type") == "rule"})
    if not rule_ids:
        return []
    rules = list(db.rules.find({"rule_id": {"$in": rule_ids}, "is_active": True}, {"_id":0,"raw_clause_text":0,"vec_chunk_ids":0}))
    return rules[:6]


def _call_gemini(prompt: str, json_mode: bool = True) -> str:
    """Call Gemini with error handling and retry."""
    client = _get_gemini()
    cfg    = types.GenerateContentConfig(
        temperature=0.1,
        response_mime_type="application/json" if json_mode else "text/plain",
    )
    try:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=cfg)
        return resp.text.strip()
    except Exception as e:
        log.error(f"Gemini call failed: {e}")
        raise


def answer_query(query: str, topic_filter: Optional[str] = None) -> dict:
    """
    Full RAG pipeline:
      1. Semantic search → relevant chunks
      2. Fetch full rules from MongoDB
      3. Build prompt and call Gemini
      4. Fallback to direct Gemini if no context found
    """
    if not query or not query.strip():
        return {"error": "Query cannot be empty", "query": query}

    query = query.strip()[:1000]   # safety cap

    # Step 1 — RAG retrieval
    context_chunks = _retrieve_rag_context(query, topic_filter)
    rules          = _fetch_related_rules(context_chunks, query)

    has_context = bool(context_chunks or rules)

    # Step 2 — build prompt
    context_text = "\n\n---\n\n".join(
        c.get("chunk_text", json.dumps(c))[:600] for c in context_chunks
    ) if context_chunks else ""

    rules_text = "\n\n".join(
        f"Rule {r.get('rule_id','?')} [{r.get('topic','?')}/{r.get('subtopic','?')}]:\n"
        f"Title: {r.get('title','')}\n"
        f"Summary: {r.get('plain_language_summary','')}\n"
        f"Requirements: {json.dumps(r.get('requirements',[]))}"
        for r in rules
    ) if rules else ""

    fallback_note = "" if has_context else "\n[NOTE: No specific circular content was found for this query. Answer from general RBI regulatory knowledge.]\n"

    prompt = f"""You are an expert RBI compliance assistant helping bank employees understand regulations.

{'## Retrieved Circular Excerpts' if context_text else ''}
{context_text}

{'## Matched Compliance Rules' if rules_text else ''}
{rules_text}
{fallback_note}

## Question
{query}

## Instructions
- Answer clearly in plain language a bank employee can understand.
- If rules apply, reference them by rule_id.
- Use bullet points for multi-part answers.
- State confidence: high (direct rule match), medium (inferred), low (general knowledge only).

Respond as JSON:
{{
  "answer": "<your answer>",
  "relevant_rule_ids": ["rule_id_1"],
  "confidence": "high|medium|low",
  "source_circulars": ["circular_id_1"],
  "fallback_used": {str(not has_context).lower()}
}}"""

    try:
        raw    = _call_gemini(prompt, json_mode=True)
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"answer": raw if "raw" in dir() else "Could not parse response.", "relevant_rule_ids":[], "confidence":"low", "fallback_used": not has_context}
    except Exception as e:
        return {
            "query": query,
            "answer": f"Service temporarily unavailable: {e}",
            "relevant_rule_ids": [],
            "confidence": "low",
            "sources_used": 0,
            "rules_matched": 0,
            "fallback_used": True,
            "error": str(e),
        }

    return {
        "query":             query,
        "answer":            parsed.get("answer",""),
        "relevant_rule_ids": parsed.get("relevant_rule_ids",[]),
        "source_circulars":  parsed.get("source_circulars",[]),
        "confidence":        parsed.get("confidence","low"),
        "sources_used":      len(context_chunks),
        "rules_matched":     len(rules),
        "fallback_used":     parsed.get("fallback_used", not has_context),
        "rules_detail":      rules,
    }


# ─────────────────────────────────────────────────────────────
# 2. VISUALIZATION DATA
# ─────────────────────────────────────────────────────────────

def get_visualization_data(
    topic: Optional[str]    = None,
    subtopic: Optional[str] = None,
    is_active: Optional[bool] = True,
    tag: Optional[str]      = None,
    search: Optional[str]   = None,
    limit: int              = 200,
) -> dict:
    """
    Returns structured graph data for the frontend visualizer.
    Nodes = rules (+ topic cluster nodes)
    Edges = relationships between rules
    Also returns summary stats and filter options.
    """
    db     = _get_db()
    query  = {}

    if topic:
        query["topic"] = topic
    if subtopic:
        query["subtopic"] = subtopic
    if is_active is not None:
        query["is_active"] = is_active
    if tag:
        query["tags"] = tag
    if search:
        query["$or"] = [
            {"title":                  {"$regex": search, "$options": "i"}},
            {"plain_language_summary": {"$regex": search, "$options": "i"}},
            {"tags":                   {"$regex": search, "$options": "i"}},
        ]

    # Fetch rules
    rules = list(db.rules.find(query, {
        "_id":0, "rule_id":1, "title":1, "topic":1, "subtopic":1,
        "is_active":1, "tags":1, "plain_language_summary":1,
        "source_circular_id":1, "effective_date":1,
        "requirements":1, "visualization_meta":1,
    }).limit(limit))

    rule_ids = {r["rule_id"] for r in rules}

    # Fetch relationships for these rules
    rels = list(db.relationships.find({
        "$or": [{"from_rule_id":{"$in":list(rule_ids)}},
                {"to_rule_id":  {"$in":list(rule_ids)}}]
    }, {"_id":0, "from_rule_id":1, "to_rule_id":1, "type":1, "note":1}))

    # Fetch topic summaries
    topic_filter = {"topic_id": topic} if topic else {}
    topics_docs  = list(db.topics.find(topic_filter, {"_id":0}))

    # Build graph nodes
    nodes = []

    # Topic cluster nodes (big circles in the graph)
    topic_set = {r["topic"] for r in rules}
    for tid in topic_set:
        tdoc = next((t for t in topics_docs if t["topic_id"] == tid), {})
        nodes.append({
            "id":         f"topic_{tid}",
            "label":      tid.replace("_"," "),
            "type":       "topic",
            "topic":      tid,
            "color":      TOPIC_COLORS.get(tid,"#888780"),
            "size":       40,
            "rule_count": tdoc.get("rule_count", 0),
            "subtopics":  tdoc.get("subtopics",[]),
        })

    # Rule nodes
    for r in rules:
        nodes.append({
            "id":       r["rule_id"],
            "label":    r["title"][:50],
            "type":     "rule",
            "topic":    r["topic"],
            "subtopic": r["subtopic"],
            "color":    r.get("visualization_meta",{}).get("cluster_color", TOPIC_COLORS.get(r["topic"],"#888780")),
            "size":     20,
            "is_active":        r["is_active"],
            "tags":             r.get("tags",[]),
            "summary":          r.get("plain_language_summary",""),
            "circular_id":      r.get("source_circular_id",""),
            "effective_date":   r.get("effective_date",""),
            "requirements":     r.get("requirements",[]),
            "parent":           f"topic_{r['topic']}",   # links to topic cluster
        })

    # Edges
    edge_type_colors = {
        "modifies":   "#EF9F27", "overrides":  "#E24B4A",
        "depends_on": "#7F77DD", "references": "#888780",
        "clarifies":  "#1D9E75", "supersedes": "#D85A30",
    }
    edges = []
    for rel in rels:
        # only include edges where BOTH ends are in our node set
        frm, to = rel["from_rule_id"], rel["to_rule_id"]
        if frm not in rule_ids and not frm.startswith("RBI"):
            continue
        edges.append({
            "source":    frm,
            "target":    to,
            "type":      rel.get("type","references"),
            "color":     edge_type_colors.get(rel.get("type","references"),"#888780"),
            "label":     rel.get("type",""),
            "note":      rel.get("note",""),
        })

    # Also add topic→rule edges so the graph shows clustering
    for r in rules:
        edges.append({
            "source": f"topic_{r['topic']}",
            "target": r["rule_id"],
            "type":   "contains",
            "color":  TOPIC_COLORS.get(r["topic"],"#888780") + "55",   # semi-transparent
            "label":  "",
        })

    # Stats per topic
    topic_stats = {}
    for r in rules:
        t = r["topic"]
        if t not in topic_stats:
            topic_stats[t] = {"total":0,"active":0,"color":TOPIC_COLORS.get(t,"#888780")}
        topic_stats[t]["total"] += 1
        if r["is_active"]:
            topic_stats[t]["active"] += 1

    # Available filter options (for frontend dropdowns)
    all_topics   = sorted({r["topic"]   for r in rules})
    all_subtopics= sorted({r["subtopic"]for r in rules})
    all_tags     = sorted({tag for r in rules for tag in r.get("tags",[])})

    return {
        "nodes":           nodes,
        "edges":           edges,
        "stats": {
            "total_rules":  len(rules),
            "total_nodes":  len(nodes),
            "total_edges":  len(edges),
            "topic_stats":  topic_stats,
        },
        "filters": {
            "topics":    all_topics,
            "subtopics": all_subtopics,
            "tags":      all_tags,
        },
        "edge_legend": edge_type_colors,
    }


# ─────────────────────────────────────────────────────────────
# 3. UPLOAD CIRCULAR  (PDF ingest)
# ─────────────────────────────────────────────────────────────

def ingest_pdf_circular(
    pdf_bytes: bytes,
    filename: str,
    topic: str = "general",
    title: Optional[str] = None,
) -> dict:
    """
    Ingests a PDF circular:
      1. Extract text via PyMuPDF
      2. Split into clauses → extract rules (spaCy/regex, no LLM)
      3. Embed chunks → Qdrant
      4. Store rules + circular + topic in MongoDB
    """
    db = _get_db()

    # Build circular_id from topic + filename stem
    stem        = Path(filename).stem
    circular_id = re.sub(r"[^A-Za-z0-9_]","_",f"{topic}__{stem}")[:60]

    # Duplicate check
    if db.circulars.find_one({"circular_id": circular_id}):
        return {"success": False, "error": "Circular already ingested. Delete from DB to re-process.", "circular_id": circular_id, "duplicate": True}

    # Extract text
    try:
        doc  = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(p.get_text("text") for p in doc)
        doc.close()
        text = re.sub(r"\n{3,}","\n\n", text)
        text = re.sub(r" {2,}"," ", text).strip()
    except Exception as e:
        return {"success": False, "error": f"PDF extraction failed: {e}"}

    if len(text.split()) < 30:
        return {"success": False, "error": "PDF has too little extractable text (possibly scanned image)."}

    # Extract rules
    clauses = _split_clauses(text)
    rules   = _clauses_to_rules(clauses, circular_id, topic)

    # Embed full-text chunks → Qdrant
    chunks    = _make_chunks(text)
    base_meta = {"record_type":"chunk","circular_id":circular_id,"topic":topic,"subtopic":"general","is_active":True,"tags":[topic]}
    chunk_ids = _embed_and_upsert(chunks, base_meta)

    # Embed each rule summary separately
    for rule in rules:
        rule_text = f"{rule['title']}. {rule['plain_language_summary']} Topic: {rule['topic']}/{rule['subtopic']}. Tags: {', '.join(rule['tags'])}."
        rule_meta = {"record_type":"rule","rule_id":rule["rule_id"],"circular_id":circular_id,"topic":topic,"subtopic":rule["subtopic"],"is_active":True,"tags":rule["tags"]}
        rule["vec_chunk_ids"] = _embed_and_upsert(_make_chunks(rule_text, size=100, overlap=10), rule_meta)

    # Circular doc
    circ_doc = {
        "circular_id":       circular_id,
        "title":             title or stem.replace("_"," ").replace("-"," "),
        "issuing_authority": "RBI",
        "date":              _extract_date(text[:2000]),
        "topic":             topic,
        "topics":            [topic],
        "rule_ids":          [r["rule_id"] for r in rules],
        "supersedes":        [],
        "superseded_by":     None,
        "is_active":         True,
        "full_text_path":    filename,
        "summary":           "",
        "_ingested_at":      datetime.utcnow().isoformat(),
    }

    # Write to MongoDB
    _upsert_circular(circ_doc)
    for rule in rules:
        _upsert_rule(rule)
        _upsert_topic(topic, circular_id)

    return {
        "success":         True,
        "circular_id":     circular_id,
        "title":           circ_doc["title"],
        "topic":           topic,
        "rules_extracted": len(rules),
        "chunks_embedded": len(chunk_ids),
        "word_count":      len(text.split()),
    }


# ─────────────────────────────────────────────────────────────
# 4. COMPLIANCE CHECKER
# ─────────────────────────────────────────────────────────────

def _parse_input_data(raw: str) -> dict:
    """Try to parse input as JSON; fall back to key:value plain text."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # try key: value lines
    parsed = {}
    for line in raw.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k:
                parsed[k] = v
    return parsed


def _check_rule_against_data(rule: dict, data: dict) -> dict:
    """
    Checks a single rule's conditions and requirements against provided data.
    Returns {rule_id, status, violations[], passed[]}
    """
    violations, passed = [], []

    for req in rule.get("requirements", []):
        req_type = req.get("type","")
        field    = req.get("field","")
        limit    = req.get("value")
        desc     = req.get("description","")

        if req_type in ("limit","monetary_limit") and field and limit is not None:
            # look for matching key in data (case-insensitive)
            data_val = None
            for k, v in data.items():
                if field.lower() in k.lower() or k.lower() in field.lower():
                    try:
                        data_val = float(str(v).replace(",","").replace("₹","").replace("Rs","").strip())
                    except ValueError:
                        pass
                    break
            if data_val is not None:
                if data_val > limit:
                    violations.append(f"Field '{field}': value {data_val:,.0f} exceeds limit {limit:,.0f} — {desc}")
                else:
                    passed.append(f"Field '{field}': {data_val:,.0f} within limit {limit:,.0f}")

        elif req_type == "percentage_limit" and limit is not None:
            for k, v in data.items():
                if "percent" in k.lower() or "%" in k or "ratio" in k.lower():
                    try:
                        pval = float(str(v).replace("%","").strip())
                        if pval > limit:
                            violations.append(f"'{k}': {pval}% exceeds limit {limit}% — {desc}")
                        else:
                            passed.append(f"'{k}': {pval}% within limit {limit}%")
                    except ValueError:
                        pass

    status = "VIOLATION" if violations else ("CHECKED" if passed else "SKIPPED")
    return {
        "rule_id":    rule["rule_id"],
        "title":      rule["title"],
        "topic":      rule["topic"],
        "subtopic":   rule["subtopic"],
        "status":     status,
        "violations": violations,
        "passed":     passed,
        "summary":    rule.get("plain_language_summary",""),
        "source":     rule.get("source_circular_id",""),
    }


def check_compliance(
    input_data: str,
    topic: Optional[str] = None,
    entity_type: Optional[str] = None,
) -> dict:
    """
    Compliance checker:
      1. Parse input (JSON or key:value text)
      2. Retrieve relevant rules from MongoDB (by topic if specified)
      3. Run rule checks against numeric fields
      4. Use Gemini to generate a plain-language report summary
    """
    if not input_data or not input_data.strip():
        return {"error": "Input data cannot be empty"}

    db      = _get_db()
    parsed  = _parse_input_data(input_data)

    if not parsed:
        return {"error": "Could not parse input data. Use JSON or 'field: value' format."}

    # Fetch relevant rules
    rule_query: dict = {"is_active": True}
    if topic:
        rule_query["topic"] = topic
    if entity_type:
        rule_query["tags"] = {"$in": [entity_type, entity_type.lower()]}

    rules = list(db.rules.find(rule_query, {"_id":0,"raw_clause_text":0,"vec_chunk_ids":0}).limit(50))

    if not rules:
        # Broaden search if no topic match
        rules = list(db.rules.find({"is_active":True}, {"_id":0,"raw_clause_text":0,"vec_chunk_ids":0}).limit(30))

    # Run checks
    results = [_check_rule_against_data(r, parsed) for r in rules]

    violations_list = [r for r in results if r["status"] == "VIOLATION"]
    passed_list     = [r for r in results if r["status"] == "CHECKED"]
    skipped_list    = [r for r in results if r["status"] == "SKIPPED"]

    # Gemini summary (only if there are violations or checks to explain)
    summary_text = ""
    if violations_list or passed_list:
        v_text = "\n".join(f"- [{r['rule_id']}] {r['title']}: {'; '.join(r['violations'])}" for r in violations_list[:10]) or "None"
        p_text = "\n".join(f"- [{r['rule_id']}] {r['title']}" for r in passed_list[:5]) or "None"
        prompt = f"""You are an RBI compliance officer. Write a concise compliance report for a bank employee.

Input data provided: {json.dumps(parsed, indent=2)}

VIOLATIONS found:
{v_text}

PASSED checks:
{p_text}

Write a plain-language summary (3-5 sentences) explaining:
1. What was checked
2. What violations were found (if any)
3. What action is required

Be direct and practical. Do not use legal jargon."""
        try:
            summary_text = _call_gemini(prompt, json_mode=False)
        except Exception as e:
            summary_text = f"Could not generate summary: {e}"

    overall_status = "NON_COMPLIANT" if violations_list else ("COMPLIANT" if passed_list else "INSUFFICIENT_DATA")

    return {
        "overall_status":    overall_status,
        "input_parsed":      parsed,
        "topic_checked":     topic or "all",
        "rules_evaluated":   len(results),
        "violations_count":  len(violations_list),
        "passed_count":      len(passed_list),
        "skipped_count":     len(skipped_list),
        "violations":        violations_list,
        "passed":            passed_list,
        "summary":           summary_text,
        "checked_at":        datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# LEGACY SHIM  (keeps old main.py working during transition)
# ─────────────────────────────────────────────────────────────

def ingest_circular(text: str, metadata: dict = None) -> dict:
    """Legacy text-based ingest (kept for backwards compatibility)."""
    chunks    = _make_chunks(text)
    topic     = (metadata or {}).get("topic","general")
    base_meta = {"record_type":"chunk","circular_id":(metadata or {}).get("circular_id","legacy"),"topic":topic,"is_active":True,"tags":[topic],**(metadata or {})}
    ids       = _embed_and_upsert(chunks, base_meta)
    return {"ingested_chunks":len(ids),"success":True}
