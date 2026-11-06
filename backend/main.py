from pathlib import Path
import re
import os

import chromadb
from backend.answer_generator import generate_grounded_answer
from backend.dashboard import router as dashboard_router
from backend.database import initialize_database, persist_chat_turn, persist_ticket
from backend.mock_servicenow import (
    _create_incident,
    _create_service_request,
    router as mock_servicenow_router,
)
from backend.self_heal import router as self_heal_router
from backend.software_provisioning import router as provisioning_router
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer


app = FastAPI(
    title="AI ITSM Helpdesk",
    description="AI-powered IT support and automation platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ] + [
        origin.strip()
        for origin in os.getenv("FRONTEND_ORIGINS", "").split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mock_servicenow_router)
app.include_router(self_heal_router)
app.include_router(provisioning_router)
app.include_router(dashboard_router)


class TicketRequest(BaseModel):
    description: str
    create_ticket: bool = True


def load_knowledge_articles():
    """Read approved sample articles from standalone Markdown files."""
    articles = []
    articles_dir = Path(__file__).resolve().parent.parent / "knowledge_base"

    for article_path in sorted(articles_dir.glob("KB*.md")):
        raw = article_path.read_text(encoding="utf-8")

        if not raw.startswith("---\n"):
            raise ValueError(f"Missing metadata header in {article_path.name}")

        _, metadata_text, content = raw.split("---\n", 2)
        metadata = {}

        for line in metadata_text.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip()

        article = {
            "id": metadata.get("id", ""),
            "title": metadata.get("title", ""),
            "category": metadata.get("category", ""),
            "content": content.strip(),
        }

        if not all(article.values()):
            raise ValueError(
                f"Incomplete article metadata or content: {article_path.name}"
            )

        articles.append(article)

    if not 5 <= len(articles) <= 10:
        raise ValueError(
            f"Expected 5–10 knowledge articles, found {len(articles)}."
        )

    if len({article["id"] for article in articles}) != len(articles):
        raise ValueError("Knowledge article IDs must be unique.")

    return articles


KNOWLEDGE_ARTICLES = load_knowledge_articles()


@app.on_event("startup")
def connect_to_mongodb():
    initialize_database(KNOWLEDGE_ARTICLES)


_rag_components = None
CONFIDENCE_THRESHOLD = 0.35


def split_into_chunks(text: str, chunk_size: int = 45, overlap: int = 10):
    """Split article text into small overlapping word chunks."""
    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))

        if end == len(words):
            break

        start = end - overlap

    return chunks


def get_rag_components():
    """Load the embedding model and synchronize the local Chroma collection."""
    global _rag_components

    if _rag_components is not None:
        return _rag_components

    embedding_model = SentenceTransformer(
        "sentence-transformers/all-MiniLM-L6-v2"
    )

    database_path = Path(__file__).resolve().parent / "chroma_db"
    chroma_client = chromadb.PersistentClient(path=str(database_path))
    collection = chroma_client.get_or_create_collection(
        name="helpdesk_knowledge",
        metadata={"hnsw:space": "cosine"},
    )

    documents = []
    ids = []
    metadatas = []

    for article in KNOWLEDGE_ARTICLES:
        for chunk_number, chunk in enumerate(
            split_into_chunks(article["content"])
        ):
            documents.append(chunk)
            ids.append(f"{article['id']}-chunk-{chunk_number}")
            metadatas.append(
                {
                    "article_id": article["id"],
                    "title": article["title"],
                    "category": article["category"],
                }
            )

    # Delete old chunks for articles that have since been removed.
    existing_ids = collection.get(include=["metadatas"]).get("ids", [])
    stale_ids = [
        document_id for document_id in existing_ids if document_id not in ids
    ]

    if stale_ids:
        collection.delete(ids=stale_ids)

    # Insert new chunks and update chunks whose article text changed.
    vectors = embedding_model.encode(
        documents,
        normalize_embeddings=True,
    ).tolist()

    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=vectors,
    )

    _rag_components = (embedding_model, collection)
    return _rag_components


def retrieve_knowledge(question: str, *, allowed_article_ids: set[str] | None = None):
    """Find the best matching approved article chunk and its source."""
    embedding_model, collection = get_rag_components()

    query_vector = embedding_model.encode(
        [question],
        normalize_embeddings=True,
    ).tolist()

    matches = collection.query(
        query_embeddings=query_vector,
        n_results=len(KNOWLEDGE_ARTICLES),
        include=["documents", "metadatas", "distances"],
    )

    ranked = list(zip(
        matches["documents"][0],
        matches["metadatas"][0],
        matches["distances"][0],
    ))
    if allowed_article_ids is not None:
        ranked = [item for item in ranked if item[1]["article_id"] in allowed_article_ids]

    # Score articles as a whole, rather than exposing every retrieved chunk.
    # This prevents near-tied, unrelated KB entries from appearing as sources.
    best_by_article = {}
    for document, metadata, distance in ranked:
        article_id = metadata["article_id"]
        if article_id not in best_by_article or distance < best_by_article[article_id][2]:
            best_by_article[article_id] = (document, metadata, distance)
    ranked = sorted(best_by_article.values(), key=lambda item: item[2])[:1]

    documents = [item[0] for item in ranked]
    metadatas = [item[1] for item in ranked]
    distances = [item[2] for item in ranked]

    if not documents:
        return {
            "found": False,
            "answer": (
                "I could not find an approved article for this question. "
                "Please contact IT Support."
            ),
            "sources": [],
            "retrieval_score": 0.0,
        }

    best_similarity = 1.0 - float(distances[0])

    # Reject weak matches so unrelated questions are escalated.
    if best_similarity < CONFIDENCE_THRESHOLD:
        return {
            "found": False,
            "answer": (
                "I could not find an approved article for this question. "
                "Please contact IT Support."
            ),
            "sources": [],
            "retrieval_score": round(best_similarity, 3),
        }

    sources = []
    seen_articles = set()
    for metadata in metadatas:
        article_id = metadata["article_id"]
        if article_id not in seen_articles:
            seen_articles.add(article_id)
            sources.append({
                "id": article_id,
                "title": metadata["title"],
                "category": metadata["category"],
            })
    approved_context = "\n\n".join(documents)

    # If the answer model is unavailable, use the approved retrieved passage.
    try:
        generated_answer = generate_grounded_answer(question, approved_context)
    except Exception:
        generated_answer = documents[0]

    # Accept only text copied exactly from the approved passage.
    if (
        generated_answer == "NO_ANSWER"
        or generated_answer not in approved_context
    ):
        generated_answer = documents[0]

    return {
        "found": True,
        "answer": generated_answer,
        "sources": sources,
        "retrieval_score": round(best_similarity, 3),
    }


def _is_question(text: str) -> bool:
    return bool(re.search(r"\b(how|what|where|why|when|which|can you explain|tell me how)\b", text))


def _looks_like_incident(text: str) -> bool:
    return bool(re.search(
        r"\b(not working|doesn't work|does not work|isn't working|cannot|can't|unable to|won't|failed|failing|error|broken|keeps crashing|stopped working|not connecting|can't connect|cannot connect)\b",
        text,
    ))


def _with_knowledge(result, **fields):
    return {
        **fields,
        "suggested_resolution": result["answer"],
        "knowledge_sources": result["sources"],
        "confidence": result["retrieval_score"],
        "needs_human_review": not result["found"],
    }


def _classify_ticket(description: str):
    """Classify the request type and attach a safe knowledge result when relevant."""
    text = re.sub(r"\s+", " ", description.lower()).strip()
    software_catalog = {
        "visual studio code": "Visual Studio Code",
        "vs code": "Visual Studio Code",
        "google chrome": "Google Chrome",
    }
    software = next((name for phrase, name in software_catalog.items() if phrase in text), None)
    explicit_request = any(term in text for term in (
        "install", "software", "access", "provision", "i need", "i want", "request", "please add",
    ))
    if explicit_request and (software or any(term in text for term in (
        "request access", "need access", "new access", "add me to", "install ", "installation",
    ))):
        supported = software is not None
        return {
            "intent": "Service Request",
            "category": "Software" if software or "install" in text else "Access Management",
            "subcategory": "Installation or Access" if supported else "Catalogue Review",
            "priority": "P3",
            "assignment_group": "Service Catalogue",
            "short_description": f"Install {software}" if software else "Unlisted service catalogue request",
            "confidence": 0.96 if supported else 0.5,
            "needs_human_review": not supported,
            "software": software or "Unlisted request",
            "software_catalog_supported": supported,
            "suggested_resolution": (
                "The request will be sent to the approved software catalogue for fulfilment."
                if supported else
                "This request is recorded for Service Catalogue review. The requested item is not in the current approved catalogue."
            ),
            "knowledge_sources": [],
        }

    if any(term in text for term in (
        "password", "account locked", "account is locked", "unlock my account",
    )):
        result = retrieve_knowledge(description, allowed_article_ids={"KB002"})
        return _with_knowledge(result,
            intent="Automatable Issue", category="Account Access",
            subcategory="Password or Account Unlock", priority="P2",
            impact="Individual", urgency="High", assignment_group="Identity Support",
            short_description="Password or account access issue",
        )

    # VPN trouble is an Incident per the assessment; a separate safe diagnostic is available.
    if "vpn" in text or "virtual private network" in text:
        result = retrieve_knowledge(description, allowed_article_ids={"KB001"})
        return _with_knowledge(result,
            intent="Incident", category="Network", subcategory="VPN",
            priority="P2", impact="Individual", urgency="High",
            assignment_group="Network Support",
            short_description="VPN authentication failure",
        )

    if any(term in text for term in ("laptop", "slow computer", "slow pc", "performance")):
        result = retrieve_knowledge(description, allowed_article_ids={"KB005"})
        return _with_knowledge(result,
            intent="Incident", category="Hardware", subcategory="Laptop Performance",
            priority="P3", impact="Individual", urgency="Medium",
            assignment_group="Desktop Support", short_description="Laptop performance issue",
        )

    if any(term in text for term in ("wifi", "wi-fi", "internet", "network")):
        result = retrieve_knowledge(description, allowed_article_ids={"KB004"})
        return _with_knowledge(result,
            intent="Incident", category="Network", subcategory="Wi-Fi or Internet",
            priority="P3", impact="Individual", urgency="Medium",
            assignment_group="Network Support", short_description="Network connectivity issue",
        )

    if any(term in text for term in ("outlook", "synchronization", "sync")):
        result = retrieve_knowledge(description, allowed_article_ids={"KB003"})
        question = _is_question(text) and not _looks_like_incident(text)
        return _with_knowledge(result,
            intent="Knowledge Question" if question else "Incident",
            category="Email and Collaboration", subcategory="Outlook Synchronization",
            priority=None if question else "P3",
            impact=None if question else "Individual", urgency=None if question else "Medium",
            assignment_group="Knowledge Base" if question else "Messaging Support",
            short_description="Outlook synchronization guidance" if question else "Outlook synchronization issue",
        )

    if _is_question(text) and not _looks_like_incident(text):
        result = retrieve_knowledge(description, allowed_article_ids={"KB003", "KB004"})
        return _with_knowledge(result,
            intent="Knowledge Question", category="General", subcategory="IT How-to",
            priority=None, assignment_group="Knowledge Base",
            short_description="IT how-to question" if result["found"] else "Unsupported knowledge question",
        )

    # Unmatched reports default to an Incident, with review required when uncertain.
    result = retrieve_knowledge(description, allowed_article_ids={"KB005"})
    classified = _with_knowledge(result,
        intent="Incident", category="General", subcategory="Unclassified",
        priority="P3", impact="Individual", urgency="Medium",
        assignment_group="IT Support", short_description="Unclassified IT issue",
    )
    classified["needs_human_review"] = True
    return classified


@app.get("/")
def home():
    return {
        "message": "Welcome to AI ITSM Helpdesk",
        "status": "Running",
    }


@app.get("/knowledge/search")
def knowledge_search(q: str = Query(..., min_length=2, max_length=500)):
    result = retrieve_knowledge(q)
    
    from backend.database import persist_knowledge_turn

    persist_knowledge_turn(
        q,
        result["answer"],
        result["sources"],
        result["retrieval_score"],
        result["found"],
    )

    return {
        "found": result["found"],
        "answer": result["answer"],
        "sources": result["sources"],
        "retrieval_score": result["retrieval_score"],
    }


@app.post("/tickets/intake")
def intake_ticket(ticket: TicketRequest):
    description = ticket.description.strip()
    if len(description) < 4:
        raise HTTPException(status_code=422, detail="Please describe the request using at least 4 characters.")
    if len(description) > 2000:
        raise HTTPException(status_code=422, detail="Request descriptions must be 2000 characters or fewer.")

    result = _classify_ticket(description)
    result["original_description"] = description
    result.update({
        "ticket_created": False,
        "servicenow_created": False,
        "ticket_id": None,
        "servicenow": None,
    })

    if ticket.create_ticket:
        if result["intent"] == "Service Request":
            reference = _create_service_request(result)
        else:
            if result["intent"] == "Knowledge Question" and not result["needs_human_review"]:
                result["short_description"] = "Knowledge follow-up request"
            reference = _create_incident(result)
        result["servicenow"] = reference
        result["servicenow_created"] = True
        result["ticket_created"] = True
        result["record_status"] = reference["status"]
        persist_ticket(result)
    else:
        result["record_status"] = "Not created"
        persist_chat_turn(result)

    return result
