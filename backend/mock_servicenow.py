from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import backend.database as db_module


router = APIRouter(
    prefix="/mock-servicenow",
    tags=["Mock ServiceNow"],
)


class IncidentCreate(BaseModel):
    short_description: str
    description: str
    category: str = "General"
    subcategory: str = "Other"
    priority: str = "P3"
    assignment_group: str = "IT Support"
    impact: str | None = None
    urgency: str | None = None


class ServiceRequestCreate(BaseModel):
    software: str
    description: str


class IncidentUpdate(BaseModel):
    status: str | None = None
    work_notes: str | None = None


def _create_incident(data: dict):
    database = db_module.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")

    collection = database["servicenow_incidents"]
    number = f"INC{100001 + collection.count_documents({}):06d}"

    document = {
        "number": number,
        "short_description": data.get("short_description", "IT issue"),
        "description": data.get("original_description", data.get("description", "")),
        "category": data.get("category", "General"),
        "subcategory": data.get("subcategory", "Other"),
        "priority": data.get("priority", "P3"),
        "assignment_group": data.get("assignment_group", "IT Support"),
        "impact": data.get("impact"),
        "urgency": data.get("urgency"),
        "intent": data.get("intent", "Incident"),
        "confidence": data.get("confidence"),
        "needs_human_review": data.get("needs_human_review", False),
        "status": "New",
        "work_notes": "",
        "created_at": datetime.now(timezone.utc),
    }

    inserted = collection.insert_one(document)
    return {
        "created": True,
        "type": "Incident",
        "number": number,
        "sys_id": str(inserted.inserted_id),
        "status": "New",
        "system": "Mock ServiceNow",
    }


def _create_service_request(data: dict):
    database = db_module.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")

    collection = database["servicenow_requests"]
    number = f"REQ{1245 + collection.count_documents({}):06d}"

    document = {
        "number": number,
        "software": data.get("software", "Software"),
        "short_description": data.get("short_description", f"Install {data.get('software', 'Software')}"),
        "description": data.get("original_description", data.get("description", "")),
        "category": data.get("category", "Software"),
        "assignment_group": data.get("assignment_group", "Service Catalogue"),
        "intent": "Service Request",
        "status": "Requested",
        "created_at": datetime.now(timezone.utc),
    }

    inserted = collection.insert_one(document)
    return {
        "created": True,
        "type": "Service Request",
        "number": number,
        "sys_id": str(inserted.inserted_id),
        "status": "Requested",
        "system": "Mock ServiceNow",
    }


def create_record_from_ticket(ticket: dict):
    """Create the appropriate mock ServiceNow record for an intake result."""
    intent = ticket.get("intent")

    if intent == "Service Request":
        return _create_service_request(ticket)
    return _create_incident(ticket)


@router.post("/incidents")
def create_incident_api(incident: IncidentCreate):
    return _create_incident(incident.model_dump())


@router.get("/incidents/{number}")
def get_incident(number: str):
    database = db_module.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")

    document = database["servicenow_incidents"].find_one({"number": number})
    if document is None:
        raise HTTPException(status_code=404, detail="Incident not found.")

    document["sys_id"] = str(document.pop("_id"))
    return document


@router.patch("/incidents/{number}")
def update_incident(number: str, update: IncidentUpdate):
    database = db_module.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")

    updates = update.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=400,
            detail="Provide a status or work_notes value to update.",
        )

    result = database["servicenow_incidents"].update_one(
        {"number": number},
        {"$set": updates},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Incident not found.")

    if "status" in updates:
        ticket_status = {
            "New": "Open",
            "In Progress": "Open",
            "Resolved": "Resolved",
            "Closed Complete": "Closed Complete",
            "Closed": "Closed",
        }.get(updates["status"])
        if ticket_status:
            database["tickets"].update_one(
                {"servicenow.number": number},
                {"$set": {"status": ticket_status, "updated_at": datetime.now(timezone.utc)}},
            )

    return get_incident(number)


@router.post("/requests")
def create_service_request_api(request: ServiceRequestCreate):
    return _create_service_request(request.model_dump())
