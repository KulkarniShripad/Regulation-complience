"""
main.py  —  RBI Compliance Assistant  API
==========================================
Routes:
  GET  /               health check
  GET  /ask            chat / RAG query
  GET  /visualization  graph data for rule visualizer
  POST /upload         upload PDF circular
  POST /compliance     compliance checker
  GET  /topics         list all topics + stats
  GET  /rules          paginated rule listing
  GET  /test           service status

Run:
  uvicorn main:app --reload --port 8000
"""

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from functions import (
    answer_query,
    get_visualization_data,
    ingest_pdf_circular,
    check_compliance,
    ingest_circular,          # legacy shim
    _get_db,
    TOPIC_COLORS,
    FOLDER_SUBTOPICS,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="RBI Circular Assistant",
    version="2.0",
    description="AI-powered RBI compliance assistant with RAG, visualization, and compliance checking.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────

class IngestTextRequest(BaseModel):
    text:     str
    metadata: dict = {}


class ComplianceRequest(BaseModel):
    data:        str             # JSON string or key:value text
    topic:       Optional[str] = None
    entity_type: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "service": "RBI Circular Assistant", "version": "2.0"}


@app.get("/ask")
def ask(
    query:  str           = Query(..., description="Your compliance question"),
    topic:  Optional[str] = Query(None, description="Filter context by topic"),
):
    """
    Chat / RAG endpoint.
    Retrieves relevant circular chunks + rules, then answers via Gemini.
    Falls back to direct Gemini if no context is found.
    """
    if not query.strip():
        raise HTTPException(400, "Query cannot be empty.")

    result = answer_query(query.strip(), topic_filter=topic)

    if result.get("error") and "unavailable" in result.get("error","").lower():
        raise HTTPException(503, detail=result["error"])

    return result


@app.get("/visualization")
def visualization(
    topic:     Optional[str]  = Query(None,  description="Filter by topic"),
    subtopic:  Optional[str]  = Query(None,  description="Filter by subtopic"),
    is_active: Optional[bool] = Query(True,  description="Show only active rules"),
    tag:       Optional[str]  = Query(None,  description="Filter by tag"),
    search:    Optional[str]  = Query(None,  description="Search rule titles/summaries"),
    limit:     int            = Query(200,   description="Max rules to return", ge=1, le=500),
):
    """
    Returns graph data (nodes + edges) for the rule visualizer frontend.
    Also returns filter options and summary statistics.
    """
    try:
        data = get_visualization_data(
            topic=topic, subtopic=subtopic, is_active=is_active,
            tag=tag, search=search, limit=limit,
        )
        return data
    except Exception as e:
        log.error(f"/visualization error: {e}")
        raise HTTPException(500, f"Visualization data error: {e}")


@app.post("/upload")
async def upload_circular(
    file:  UploadFile        = File(...),
    topic: str               = Form("general"),
    title: Optional[str]     = Form(None),
):
    """
    Upload a PDF circular. Extracts text, generates rules, embeds to Qdrant, stores in MongoDB.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted.")

    if file.size and file.size > 50 * 1024 * 1024:   # 50 MB cap
        raise HTTPException(413, "File too large (max 50 MB).")

    if topic not in FOLDER_SUBTOPICS:
        topic = "general"

    try:
        pdf_bytes = await file.read()
    except Exception as e:
        raise HTTPException(400, f"Could not read file: {e}")

    result = ingest_pdf_circular(
        pdf_bytes=pdf_bytes,
        filename=file.filename,
        topic=topic,
        title=title,
    )

    if result.get("duplicate"):
        raise HTTPException(409, result.get("error","Duplicate circular."))

    if not result.get("success"):
        raise HTTPException(422, result.get("error","Ingestion failed."))

    return result


@app.post("/compliance")
def compliance_check(body: ComplianceRequest):
    """
    Compliance checker.
    Accepts JSON data or plain 'field: value' text, checks against stored rules.
    Returns violations, passed checks, and a Gemini-generated summary.
    """
    if not body.data.strip():
        raise HTTPException(400, "Input data cannot be empty.")

    result = check_compliance(
        input_data=body.data,
        topic=body.topic,
        entity_type=body.entity_type,
    )

    if result.get("error"):
        raise HTTPException(422, result["error"])

    return result


@app.get("/topics")
def list_topics():
    """
    Returns all topics with rule counts, subtopics, and colors.
    Used for filter dropdowns in the frontend.
    """
    try:
        db     = _get_db()
        topics = list(db.topics.find({}, {"_id":0}))
        # enrich with color if missing
        for t in topics:
            if "visualization_meta" not in t:
                t["visualization_meta"] = {"cluster_color": TOPIC_COLORS.get(t["topic_id"],"#888780")}
        return {"topics": topics, "total": len(topics)}
    except Exception as e:
        log.error(f"/topics error: {e}")
        raise HTTPException(500, f"Could not fetch topics: {e}")


@app.get("/rules")
def list_rules(
    topic:    Optional[str]  = Query(None),
    subtopic: Optional[str]  = Query(None),
    tag:      Optional[str]  = Query(None),
    search:   Optional[str]  = Query(None),
    page:     int            = Query(1, ge=1),
    per_page: int            = Query(20, ge=1, le=100),
):
    """Paginated rule listing with filters."""
    try:
        db    = _get_db()
        query = {"is_active": True}
        if topic:
            query["topic"] = topic
        if subtopic:
            query["subtopic"] = subtopic
        if tag:
            query["tags"] = tag
        if search:
            query["$or"] = [
                {"title":                  {"$regex": search, "$options":"i"}},
                {"plain_language_summary": {"$regex": search, "$options":"i"}},
            ]

        total = db.rules.count_documents(query)
        skip  = (page - 1) * per_page
        rules = list(db.rules.find(query, {
            "_id":0,"raw_clause_text":0,"vec_chunk_ids":0,"_validation_warnings":0
        }).skip(skip).limit(per_page))

        return {
            "rules":    rules,
            "total":    total,
            "page":     page,
            "per_page": per_page,
            "pages":    (total + per_page - 1) // per_page,
        }
    except Exception as e:
        log.error(f"/rules error: {e}")
        raise HTTPException(500, f"Could not fetch rules: {e}")


@app.post("/ingest")
def ingest_text(body: IngestTextRequest):
    """Legacy plain-text ingest endpoint (kept for backwards compatibility)."""
    if not body.text.strip():
        raise HTTPException(400, "Circular text cannot be empty.")
    result = ingest_circular(body.text, body.metadata)
    return result


@app.get("/test")
def test_services():
    """Service health check — verifies Gemini, Qdrant, MongoDB are reachable."""
    from functions import _get_qdrant, GEMINI_API_KEY
    status = {}

    # Gemini
    try:
        status["gemini"] = "ok" if GEMINI_API_KEY else "missing_api_key"
    except Exception as e:
        status["gemini"] = f"error: {e}"

    # Qdrant
    try:
        q = _get_qdrant()
        cols = [c.name for c in q.get_collections().collections]
        status["qdrant"] = {"status":"ok","collections":cols}
    except Exception as e:
        status["qdrant"] = f"error: {e}"

    # MongoDB
    try:
        db    = _get_db()
        rules = db.rules.count_documents({})
        circs = db.circulars.count_documents({})
        topics= db.topics.count_documents({})
        status["mongodb"] = {"status":"ok","rules":rules,"circulars":circs,"topics":topics}
    except Exception as e:
        status["mongodb"] = f"error: {e}"

    overall = "ok" if all(
        (isinstance(v,dict) and v.get("status")=="ok") or v=="ok"
        for v in status.values()
    ) else "degraded"

    return {"overall": overall, "services": status}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
