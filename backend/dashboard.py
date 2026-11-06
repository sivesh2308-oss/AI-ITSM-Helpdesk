from fastapi import APIRouter, HTTPException

import backend.database as db_module


router = APIRouter(tags=["Dashboard and Knowledge Base"])


@router.get("/dashboard/summary")
def dashboard_summary():
    database = db_module.database

    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")

    total_tickets = database["tickets"].count_documents({})
    open_tickets = database["tickets"].count_documents({"status": "Open"})
    escalated_tickets = database["tickets"].count_documents(
        {"needs_human_review": True, "status": "Open"}
    )
    ai_resolved = database["tickets"].count_documents(
        {"status": {"$in": ["Resolved", "Closed Complete"]}}
    )
    software_requests = database["servicenow_requests"].count_documents({})
    provisioning_in_progress = database["software_requests"].count_documents(
        {"status": "Provisioning"}
    )
    automation_runs = database["automation_audit"].count_documents({})
    completed_automations = database["automation_audit"].count_documents(
        {"status": "Completed"}
    )

    return {
        "total_tickets": total_tickets,
        "open_tickets": open_tickets,
        "ai_resolved": ai_resolved,
        "escalated_tickets": escalated_tickets,
        "software_requests": software_requests,
        "provisioning_in_progress": provisioning_in_progress,
        "automation_runs": automation_runs,
        "completed_automations": completed_automations,
    }


@router.get("/dashboard/automations")
def recent_automations(limit: int = 8):
    database = db_module.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")
    limit = max(1, min(limit, 25))
    records = list(database["automation_audit"].find({}).sort("created_at", -1).limit(limit))
    for record in records:
        record["id"] = str(record.pop("_id"))
        created_at = record.get("created_at")
        if created_at:
            record["created_at"] = created_at.isoformat()
    return {"automations": records}


@router.get("/knowledge/articles")
def list_knowledge_articles():
    database = db_module.database

    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")

    articles = list(
        database["knowledge_articles"].find(
            {},
            {
                "_id": 0,
                "id": 1,
                "title": 1,
                "category": 1,
                "content": 1,
            },
        ).sort("title", 1)
    )

    return {"articles": articles}
