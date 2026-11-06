from datetime import datetime, timezone
from pathlib import Path
import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.server_api import ServerApi


project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

mongodb_uri = os.getenv("MONGODB_URI")
database_name = os.getenv("MONGODB_DATABASE", "ai_itsm_helpdesk")

mongo_client = None
database = None


def initialize_database(articles):
    global mongo_client, database

    if not mongodb_uri:
        raise RuntimeError(
            "MONGODB_URI is missing. Check the .env file in the project folder."
        )

    mongo_client = MongoClient(
        mongodb_uri,
        server_api=ServerApi("1"),
        serverSelectionTimeoutMS=10000,
    )

    mongo_client.admin.command("ping")
    database = mongo_client[database_name]

    required_collections = [
        "tickets",
        "knowledge_articles",
        "chat_history",
        "software_requests",
        "automation_audit",
        "servicenow_incidents",
        "servicenow_requests",
    ]
    existing_collections = set(database.list_collection_names())

    for collection_name in required_collections:
        if collection_name not in existing_collections:
            database.create_collection(collection_name)

    database.tickets.create_index("created_at")
    database.chat_history.create_index("created_at")
    database.automation_audit.create_index("created_at")
    database.knowledge_articles.create_index("id", unique=True)

    for article in articles:
        database.knowledge_articles.update_one(
            {"id": article["id"]},
            {"$set": article},
            upsert=True,
        )

    print("MongoDB Atlas connected; sample knowledge articles saved.")


def persist_ticket(result):
    """Persist a confirmed ticket after its ServiceNow reference is attached."""
    if database is None:
        raise RuntimeError("MongoDB is not connected.")

    ticket_document = result.copy()
    ticket_document["created_at"] = datetime.now(timezone.utc)
    ticket_document.setdefault("status", "Open")
    inserted = database.tickets.insert_one(ticket_document)
    result["ticket_id"] = str(inserted.inserted_id)

    chat_document = {
        "ticket_id": result["ticket_id"],
        "question": result.get("original_description", ""),
        "answer": result.get("suggested_resolution", ""),
        "intent": result.get("intent"),
        "ticket_created": True,
        "created_at": ticket_document["created_at"],
    }
    chat_inserted = database.chat_history.insert_one(chat_document)
    result["chat_id"] = str(chat_inserted.inserted_id)
    return result


def persist_chat_turn(result):
    """Store an analyzed no-ticket conversation separately from the ticket queue."""
    if database is None:
        raise RuntimeError("MongoDB is not connected.")
    inserted = database.chat_history.insert_one({
        "question": result.get("original_description", ""),
        "answer": result.get("suggested_resolution", ""),
        "intent": result.get("intent"),
        "sources": result.get("knowledge_sources", []),
        "confidence": result.get("confidence"),
        "ticket_created": False,
        "created_at": datetime.now(timezone.utc),
    })
    result["chat_id"] = str(inserted.inserted_id)
    return result


def persist_knowledge_turn(question, answer, sources, confidence, found):
    """Save a knowledge search and its result in MongoDB chat history."""
    if database is None:
        raise RuntimeError("MongoDB is not connected.")

    document = {
        "question": question,
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
        "found": found,
        "created_at": datetime.now(timezone.utc),
    }

    inserted = database.chat_history.insert_one(document)
    return str(inserted.inserted_id)
