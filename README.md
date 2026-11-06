# AI ITSM Helpdesk

## About the project

AI ITSM Helpdesk is an employee self-service prototype for common IT support needs. Employees can describe an issue, search approved IT knowledge, submit incident or software requests, and follow simulated support and automation workflows.

The project combines a web portal with a Python API and a retrieval-augmented knowledge assistant. Ticket categorization is based on rules and keywords. ServiceNow, password reset, VPN diagnostics, and software provisioning are simulated for demonstration; the project does not connect to a live ServiceNow instance or make real account, network, or device changes.

## Technologies

- **Frontend:** React 19 and Vite
- **Backend API:** Python and FastAPI
- **Database:** MongoDB Atlas with PyMongo for tickets, chat history, requests, mock ITSM records, and automation audit events
- **Knowledge retrieval:** ChromaDB with `sentence-transformers/all-MiniLM-L6-v2` embeddings
- **Answer generation:** Hugging Face Transformers with `google/flan-t5-small`; answers are constrained to text from retrieved, approved knowledge passages
- **Knowledge content:** Approved Markdown articles in `knowledge_base/`

## Workflow

1. **Employee submits a request** through the self-service portal, or searches the knowledge base.
2. **The backend analyzes the request** using rules and keywords to identify its category and determine whether it is an incident, a service request, a knowledge question, or needs human review.
3. **Relevant approved guidance is retrieved** from the knowledge base using semantic search. The system checks retrieval confidence and grounds answers in the retrieved passage; it avoids presenting unsupported guidance when a match is not confident.
4. **The system records and routes the request.** When ticket creation is selected, it saves the ticket and creates a corresponding mock ServiceNow incident or request. Requests that are not recognized can be flagged for human review.
5. **Demonstration automations run as simulations.** Password self-help, read-only VPN diagnostics, and software provisioning update the corresponding mock records and record their activity for review.
6. **Staff can review activity** in the dashboard, including ticket and automation status, knowledge sources, and audit history.
