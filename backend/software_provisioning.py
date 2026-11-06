from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

import backend.database as db_module


router = APIRouter(
    prefix="/provisioning",
    tags=["Software Provisioning"],
)


SOFTWARE_CATALOG = [
    {
        "id": "SW001",
        "name": "Visual Studio Code",
        "status": "Available",
        "approval_required": True,
    },
    {
        "id": "SW002",
        "name": "Google Chrome",
        "status": "Available",
        "approval_required": True,
    },
]


@router.get("/catalog")
def get_software_catalog():
    return {"items": SOFTWARE_CATALOG}


@router.post("/requests/{request_number}/provision")
def start_provisioning(request_number: str):
    database = db_module.database

    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")

    service_request = database["servicenow_requests"].find_one(
        {"number": request_number}
    )

    if service_request is None:
        raise HTTPException(
            status_code=404,
            detail=f"Service request {request_number} was not found.",
        )

    software = service_request.get("software", "Software")
    catalog_item = next(
        (
            item for item in SOFTWARE_CATALOG
            if item["name"].lower() == software.lower()
        ),
        None,
    )

    if catalog_item is None:
        raise HTTPException(
            status_code=400,
            detail=f"{software} is not in the approved software catalogue.",
        )

    now = datetime.now(timezone.utc)

    database["servicenow_requests"].update_one(
        {"number": request_number},
        {
            "$set": {
                "status": "Provisioning",
                "updated_at": now,
                "work_notes": "Mock provisioning started.",
            }
        },
    )

    database["software_requests"].update_one(
        {"request_number": request_number},
        {
            "$set": {
                "request_number": request_number,
                "software": software,
                "catalog_item_id": catalog_item["id"],
                "status": "Provisioning",
                "updated_at": now,
                "mock": True,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    database["automation_audit"].insert_one(
        {
            "action": "software_provisioning",
            "request_number": request_number,
            "software": software,
            "status": "Provisioning",
            "steps": [
                {"step": "Catalogue Check", "result": "Approved item found"},
                {"step": "ServiceNow", "result": "Request found"},
                {"step": "Provisioning", "result": "Mock provisioning started"},
            ],
            "created_at": now,
        }
    )
    database["tickets"].update_one(
        {"servicenow.number": request_number},
        {"$set": {"status": "Provisioning", "updated_at": now}},
    )

    return {
        "request_id": request_number,
        "software": software,
        "status": "Provisioning",
        "servicenow_status": "Provisioning",
        "message": "Mock provisioning started; no software was installed.",
    }


@router.post("/requests/{request_number}/validate")
def validate_provisioning(request_number: str):
    database = db_module.database

    if database is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")

    software_request = database["software_requests"].find_one(
        {"request_number": request_number}
    )

    if software_request is None:
        raise HTTPException(
            status_code=404,
            detail="Provisioning request was not found. Start provisioning first.",
        )

    if software_request.get("status") != "Provisioning":
        raise HTTPException(
            status_code=400,
            detail="This request is not currently in Provisioning status.",
        )

    now = datetime.now(timezone.utc)
    software = software_request["software"]

    database["software_requests"].update_one(
        {"request_number": request_number},
        {
            "$set": {
                "status": "Provisioned",
                "validation": "Passed",
                "updated_at": now,
            }
        },
    )

    database["servicenow_requests"].update_one(
        {"number": request_number},
        {
            "$set": {
                "status": "Closed Complete",
                "updated_at": now,
                "work_notes": "Mock provisioning validated successfully.",
            }
        },
    )
    database["tickets"].update_one(
        {"servicenow.number": request_number},
        {"$set": {"status": "Closed Complete", "updated_at": now}},
    )

    database["automation_audit"].insert_one(
        {
            "action": "software_provisioning_validation",
            "request_number": request_number,
            "software": software,
            "status": "Completed",
            "validation": "Passed",
            "steps": [
                {"step": "Validate", "result": "Mock validation passed"},
                {
                    "step": "Update ServiceNow",
                    "result": "Request marked Closed Complete",
                },
            ],
            "created_at": now,
        }
    )

    return {
        "request_id": request_number,
        "software": software,
        "status": "Provisioned",
        "validation": "Passed",
        "servicenow_status": "Closed Complete",
        "message": "Mock provisioning was validated; no software was installed.",
    }
