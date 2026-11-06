from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import backend.database as db_module
from backend.mock_servicenow import _create_incident


router = APIRouter(
    prefix="/automation",
    tags=["Self-Heal Automation"],
)


class SelfHealRequest(BaseModel):
    description: str
    incident_number: str | None = None


def _get_or_create_incident(description: str, incident_number: str | None, fields: dict):
    database = db_module.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")

    if incident_number:
        incident = database["servicenow_incidents"].find_one({"number": incident_number})
        if incident is None:
            raise HTTPException(status_code=404, detail=f"Incident {incident_number} was not found.")
        return {"number": incident_number, "status": incident.get("status", "New")}
    existing = database["servicenow_incidents"].find_one({
        "description": description,
        "status": {"$nin": ["Resolved", "Closed", "Closed Complete"]},
    })
    if existing is not None:
        return {"number": existing["number"], "status": existing.get("status", "New")}
    return _create_incident({**fields, "original_description": description})


def _update_ticket_status(incident_number: str, status: str):
    db_module.database["tickets"].update_one(
        {"servicenow.number": incident_number},
        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}},
    )


def run_password_self_heal(description: str, incident_number: str | None = None):
    database = db_module.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")

    # Find the approved password article in MongoDB.
    article = database["knowledge_articles"].find_one({"id": "KB002"})

    if article is None:
        raise HTTPException(
            status_code=503,
            detail="The approved password-reset article KB002 is missing.",
        )

    incident = _get_or_create_incident(description, incident_number, {
            "short_description": "Password or account access issue",
            "category": "Account Access",
            "subcategory": "Password Reset",
            "priority": "P2",
            "assignment_group": "Identity Support",
            "impact": "Individual",
            "urgency": "High",
        })

    audit = {
        "action": "password_reset_simulation",
        "description": description,
        "knowledge_source": {
            "id": article["id"],
            "title": article["title"],
        },
        "servicenow_incident": incident["number"],
        "steps": [
            {"step": "Identify", "result": "Password issue recognized"},
            {"step": "Diagnose", "result": "Password reset is eligible for the approved simulation"},
            {
                "step": "Knowledge Search",
                "result": "Approved article KB002 found",
            },
            {
                "step": "Determine Automation",
                "result": "Password reset is eligible for mock automation",
            },
            {
                "step": "Execute",
                "result": "Mock password reset completed",
            },
            {
                "step": "Validate",
                "result": "Mock validation passed",
            },
            {
                "step": "Update ServiceNow",
                "result": "Incident marked Resolved",
            },
        ],
        "created_at": datetime.now(timezone.utc),
        "status": "Completed",
    }

    # Mock action: no real password is changed.
    # The incident and audit record show the simulated workflow.
    database["servicenow_incidents"].update_one(
        {"number": incident["number"]},
        {
            "$set": {
                "status": "Resolved",
                "work_notes": (
                    "Mock password reset completed and validation passed. "
                    "See automation audit record."
                ),
            }
        },
    )
    _update_ticket_status(incident["number"], "Resolved")

    audit_result = database["automation_audit"].insert_one(audit)

    return {
        "intent": "Automatable Issue",
        "action": "Password reset simulation",
        "result": "Completed",
        "validation": "Passed",
        "knowledge_source": audit["knowledge_source"],
        "servicenow_incident": incident["number"],
        "incident_status": "Resolved",
        "audit_id": str(audit_result.inserted_id),
        "message": (
            "This is a simulated reset for the hackathon prototype. "
            "No real password was changed."
        ),
    }


def run_vpn_self_heal(description: str, incident_number: str | None = None):
    """Record a safe, simulated VPN diagnostics and status check."""
    database = db_module.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")

    article = database["knowledge_articles"].find_one({"id": "KB001"})
    if article is None:
        raise HTTPException(status_code=503, detail="The approved VPN article KB001 is missing.")

    incident = _get_or_create_incident(description, incident_number, {
        "short_description": "VPN authentication failure",
        "category": "Network", "subcategory": "VPN", "priority": "P2",
        "assignment_group": "Network Support", "impact": "Individual", "urgency": "High",
    })
    steps = [
        {"step": "Identify", "result": "VPN connection issue recognized"},
        {"step": "Diagnose", "result": "Authentication failure classified as P2"},
        {"step": "Knowledge Search", "result": "Approved article KB001 found"},
        {"step": "Determine Automation", "result": "Read-only VPN status check is safe to simulate"},
        {"step": "Execute", "result": "Mock VPN status check completed"},
        {"step": "Validate", "result": "VPN status check completed; authentication still requires support review"},
        {"step": "Update ServiceNow", "result": "Incident updated with diagnostic notes"},
    ]
    now = datetime.now(timezone.utc)
    database["servicenow_incidents"].update_one(
        {"number": incident["number"]},
        {"$set": {
            "status": "In Progress",
            "work_notes": "Mock VPN status check completed; user authentication requires support follow-up.",
            "updated_at": now,
        }},
    )
    _update_ticket_status(incident["number"], "Open")
    audit_result = database["automation_audit"].insert_one({
        "action": "vpn_status_check_simulation", "description": description,
        "knowledge_source": {"id": article["id"], "title": article["title"]},
        "servicenow_incident": incident["number"], "steps": steps,
        "created_at": now, "status": "Completed",
    })
    return {
        "intent": "Incident", "action": "VPN status check simulation",
        "result": "Completed", "validation": "Passed",
        "knowledge_source": {"id": article["id"], "title": article["title"]},
        "servicenow_incident": incident["number"], "incident_status": "In Progress",
        "audit_id": str(audit_result.inserted_id), "steps": steps,
        "message": "Mock VPN diagnostics completed. Authentication still needs support review; no network settings were changed.",
    }


@router.post("/password-reset")
def password_reset(request: SelfHealRequest):
    text = request.description.lower()

    password_terms = [
        "password expired",
        "password has expired",
        "my password expired",
        "my password has expired",
        "reset my password",
        "forgot my password",
        "account locked",
        "account is locked",
        "unlock my account",
    ]

    if not any(term in text for term in password_terms):
        raise HTTPException(
            status_code=400,
            detail=(
                "This workflow only handles recognized password or account-lockout "
                "requests."
            ),
        )

    return run_password_self_heal(request.description.strip(), request.incident_number)


@router.post("/vpn-check")
def vpn_status_check(request: SelfHealRequest):
    if not any(term in request.description.lower() for term in ("vpn", "virtual private network")):
        raise HTTPException(status_code=400, detail="This workflow only handles VPN connection requests.")
    return run_vpn_self_heal(request.description.strip(), request.incident_number)
