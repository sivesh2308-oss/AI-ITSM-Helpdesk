# AI ITSM Helpdesk

An assessment prototype for employee self-service, grounded IT knowledge search, ticket routing, mock ServiceNow integration, and safe simulated automation.

## Architecture

- React + Vite employee portal in `frontend/`.
- Python + FastAPI API in `backend/` (`uvicorn backend.main:app --reload --port 8001`).
- MongoDB Atlas stores tickets, knowledge metadata, chat history, software requests, mock ServiceNow records, and automation audit events.
- `sentence-transformers/all-MiniLM-L6-v2` creates embeddings; Chroma persists article chunks under `backend/chroma_db/`.
- `google/flan-t5-small` is the open Hugging Face generation model. It is used to select text grounded in the retrieved approved passage; if model loading fails, the retrieved approved passage is returned. Generated text is accepted only when it is an exact substring of that passage.
- ServiceNow is represented by a MongoDB-backed mock API. It does not connect to a live ServiceNow instance. A production integration would replace the functions in `backend/mock_servicenow.py` with authenticated REST calls.

## Setup

1. Install Python 3.10+ and Node.js 20.19+ (or 22.12+).
2. The project environment is named `venv` and was used with Python 3.12.10. If you need to create it, run:

   ```powershell
   py -3.12 -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install fastapi uvicorn pymongo python-dotenv chromadb sentence-transformers transformers torch
   ```

   If `venv` already exists, activate it instead of creating it again.

3. Keep the existing `.env` in the project root with your MongoDB Atlas connection. Optionally set `MONGODB_DATABASE` (defaults to `ai_itsm_helpdesk`) and comma-separated `FRONTEND_ORIGINS` for deployed web origins. Never commit this file or share its values.
4. Start the backend from the project root: `uvicorn backend.main:app --reload --host 127.0.0.1 --port 8001`. You can also run `\.\venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8001` to select the project interpreter explicitly. First startup loads the embedding and Hugging Face models; model downloads may be required.
5. In another terminal, copy `frontend/.env.example` to `frontend/.env.local` if you need a different backend URL. The example points `VITE_API_URL` to `http://127.0.0.1:8001`. Run `cd frontend; npm install; npm run dev`, then open the Vite URL printed in the terminal (usually `http://localhost:5173`).

## API overview

- `POST /tickets/intake` with `{ "description": "...", "create_ticket": true }` classifies a request. If selected, it creates exactly one mock ServiceNow Incident or Request, then saves the linked ticket. If unchecked, it only saves the chat analysis and creates no ITSM record.
- `GET /knowledge/search?q=...` performs Chroma semantic retrieval, returns a grounded answer, source metadata, and retrieval confidence.
- `POST /automation/password-reset` accepts `description` and the intake `incident_number`, simulates password self-help, resolves that same mock incident, updates its ticket, and records every step in `automation_audit`.
- `POST /automation/vpn-check` accepts `description` and the intake `incident_number`, simulates read-only VPN diagnostics, updates the same incident's work notes/status, and records every step. It does not alter network configuration.
- `GET /provisioning/catalog`, `POST /provisioning/requests/{number}/provision`, and `POST /provisioning/requests/{number}/validate` implement the mock provisioning lifecycle.
- `GET /dashboard/summary`, `GET /dashboard/automations`, `GET /knowledge/articles`, and `/mock-servicenow/...` expose dashboard, recent automation state, knowledge, and mock ITSM data. The AI Analysis screen includes incident retrieval and update controls. Interactive API docs are at `/docs`.

The mock ServiceNow API includes `POST /mock-servicenow/incidents`, `GET` and `PATCH /mock-servicenow/incidents/{number}`, and `POST /mock-servicenow/requests`. The mock stores its records in the MongoDB collections `servicenow_incidents` and `servicenow_requests`.

## Request routing

The current intake router in `backend/main.py` uses rules and keyword checks, rather than a trained intent-classification model. Its intended assessment paths include VPN incidents, password/account-access automation, Outlook knowledge questions or incidents, Wi-Fi incidents, laptop-performance incidents, supported software requests (Visual Studio Code and Google Chrome), and unsupported questions that can be escalated. Unknown software catalogue items are flagged for review. This is a prototype rule set; requests outside its recognized patterns may need human review.

For ticket intake, known scenarios restrict retrieval to their corresponding approved article (VPN → KB001, password/account access → KB002, Outlook → KB003, Wi-Fi → KB004, laptop performance → KB005). Retrieval selects the best matching article and suppresses sources below the confidence threshold. The separate `/knowledge/search` endpoint searches across the full approved knowledge base.

## RAG and safety

Five approved Markdown articles in `knowledge_base/` are split into overlapping 45-word chunks (10-word overlap), embedded with MiniLM, and upserted into cosine-distance Chroma. Search rejects a best similarity below the 0.35 confidence threshold and returns an explicit unavailable answer with no sources. Answers are restricted to exact text from the retrieved approved passage. Results show article sources and retrieval confidence. Unknown questions and unclassified incidents are flagged for review; when ticket creation is enabled they create an Incident, and when disabled only a chat analysis is saved. Knowledge searches are also stored in chat history.

## Demonstration scenarios

1. VPN authentication failure: Incident classification, Network/VPN, P2, Individual/High, Network Support, KB source, and one mock ServiceNow reference; then run mock VPN diagnostics against that same incident and inspect audit steps.
2. Password expired: Automatable Issue classification, KB002 grounded guidance, then simulated reset, validation, resolution of the same intake incident, and audit log.
3. Outlook synchronization: knowledge retrieval from KB003 with source and confidence.
4. Visual Studio Code installation: service request, catalogue item, mock ServiceNow REQ, provisioning, and validation.
5. Unsupported question: unavailable approved guidance, low confidence, human review, and incident escalation. Uncheck ticket creation to inspect analysis without creating an Incident or Request.

The frontend includes Employee Self-Service with a conversation transcript, a separate AI Analysis view, a dashboard with recent automation statuses, and category-filtered Knowledge Base search with confidence and sources.

## Limitations

The ServiceNow API is a MongoDB-backed mock, not a live ServiceNow integration. Password reset, VPN diagnostics, and software provisioning are simulations; no real account, network, or device is changed. The small rule-based intent router is a hackathon baseline, not a production intent model. MongoDB Atlas connectivity and first-run model downloads are required for the complete live flow. Use least-privilege credentials and a developer/test ServiceNow instance when replacing the mock.

## Verification

Run the scenario checks from the repository root with `py -m unittest discover -s tests -v`. Run the frontend production build with `cd frontend; npm run build`.
