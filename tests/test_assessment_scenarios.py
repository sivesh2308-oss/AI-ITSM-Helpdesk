import unittest
from unittest.mock import patch

from backend import main
from backend import self_heal
from backend.main import TicketRequest, _classify_ticket


def knowledge_result(found=True, score=0.82, article="KB001"):
    return {
        "found": found,
        "answer": "Follow the approved troubleshooting steps." if found else "I could not find an approved article.",
        "sources": ([{"id": article, "title": "Approved support article", "category": "IT"}] if found else []),
        "retrieval_score": score,
    }


class AssessmentScenarios(unittest.TestCase):
    def test_vpn_matches_assessment_incident_fields(self):
        with patch("backend.main.retrieve_knowledge", return_value=knowledge_result()):
            result = _classify_ticket("I cannot connect to VPN since this morning. Authentication keeps failing.")
        self.assertEqual(result["intent"], "Incident")
        self.assertEqual((result["category"], result["subcategory"], result["priority"]), ("Network", "VPN", "P2"))
        self.assertEqual((result["impact"], result["urgency"], result["assignment_group"]), ("Individual", "High", "Network Support"))
        self.assertEqual(result["short_description"], "VPN authentication failure")
        self.assertEqual(result["knowledge_sources"][0]["id"], "KB001")

    def test_password_issue_is_automatable_and_grounded(self):
        with patch("backend.main.retrieve_knowledge", return_value=knowledge_result(article="KB002")):
            result = _classify_ticket("My password has expired.")
        self.assertEqual(result["intent"], "Automatable Issue")
        self.assertEqual(result["knowledge_sources"][0]["id"], "KB002")

    def test_outlook_question_routes_to_knowledge(self):
        with patch("backend.main.retrieve_knowledge", return_value=knowledge_result(article="KB003")):
            result = _classify_ticket("How do I troubleshoot Outlook synchronization?")
        self.assertEqual(result["intent"], "Knowledge Question")
        self.assertEqual(result["knowledge_sources"][0]["id"], "KB003")

    def test_outlook_failure_routes_to_incident(self):
        with patch("backend.main.retrieve_knowledge", return_value=knowledge_result(article="KB003")):
            result = _classify_ticket("Outlook is not syncing and keeps failing.")
        self.assertEqual(result["intent"], "Incident")

    def test_software_request_detects_assessment_short_form(self):
        result = _classify_ticket("I need Visual Studio Code.")
        self.assertEqual(result["intent"], "Service Request")
        self.assertEqual(result["software"], "Visual Studio Code")
        self.assertTrue(result["software_catalog_supported"])

    def test_unlisted_software_is_a_service_request_for_catalogue_review(self):
        result = _classify_ticket("Please install SuperTool on my laptop.")
        self.assertEqual(result["intent"], "Service Request")
        self.assertFalse(result["software_catalog_supported"])
        self.assertTrue(result["needs_human_review"])

    def test_unknown_question_escalates_without_invented_answer(self):
        with patch("backend.main.retrieve_knowledge", return_value=knowledge_result(False, 0.12)):
            result = _classify_ticket("How do I repair my imaginary quantum toaster?")
        self.assertEqual(result["intent"], "Knowledge Question")
        self.assertTrue(result["needs_human_review"])
        self.assertEqual(result["confidence"], 0.12)
        self.assertEqual(result["knowledge_sources"], [])

    def test_checked_ticket_creates_one_itsm_record_and_persists_reference(self):
        incident_ref = {"created": True, "type": "Incident", "number": "INC100001", "status": "New"}
        with (
            patch("backend.main.retrieve_knowledge", return_value=knowledge_result()),
            patch("backend.main._create_incident", return_value=incident_ref) as create_incident,
            patch("backend.main.persist_ticket", side_effect=lambda result: result.update(ticket_id="db-ticket-1")),
        ):
            result = main.intake_ticket(TicketRequest(description="My printer is not working", create_ticket=True))
        create_incident.assert_called_once()
        self.assertTrue(result["ticket_created"])
        self.assertEqual(result["servicenow"]["number"], "INC100001")
        self.assertEqual(result["ticket_id"], "db-ticket-1")

    def test_unchecked_ticket_creates_no_service_now_record(self):
        with (
            patch("backend.main.retrieve_knowledge", return_value=knowledge_result(False, 0.1)),
            patch("backend.main._create_incident") as create_incident,
            patch("backend.main.persist_chat_turn", side_effect=lambda result: result),
        ):
            result = main.intake_ticket(TicketRequest(description="Printer is broken", create_ticket=False))
        create_incident.assert_not_called()
        self.assertFalse(result["ticket_created"])
        self.assertFalse(result["servicenow_created"])
        self.assertIsNone(result["servicenow"])

    def test_password_self_heal_updates_existing_incident_without_duplicate(self):
        from unittest.mock import MagicMock, Mock

        collections = {
            "knowledge_articles": Mock(),
            "servicenow_incidents": Mock(),
            "automation_audit": Mock(),
            "tickets": Mock(),
        }
        collections["knowledge_articles"].find_one.return_value = {
            "id": "KB002", "title": "Password Reset",
        }
        collections["servicenow_incidents"].find_one.return_value = {
            "number": "INC100042", "status": "New",
        }
        collections["automation_audit"].insert_one.return_value.inserted_id = "audit-1"
        database = MagicMock()
        database.__getitem__.side_effect = lambda name: collections[name]
        with (
            patch("backend.self_heal.db_module.database", database),
            patch("backend.self_heal._create_incident") as create_incident,
        ):
            result = self_heal.run_password_self_heal(
                "My password has expired.", "INC100042",
            )
        create_incident.assert_not_called()
        self.assertEqual(result["servicenow_incident"], "INC100042")
        self.assertEqual(result["incident_status"], "Resolved")
        collections["tickets"].update_one.assert_called_once()
        audit = collections["automation_audit"].insert_one.call_args.args[0]
        self.assertIn("Diagnose", [step["step"] for step in audit["steps"]])


if __name__ == "__main__":
    unittest.main()
