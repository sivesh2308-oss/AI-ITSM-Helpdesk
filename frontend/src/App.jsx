import { useEffect, useState } from "react";
import "./App.css";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8001";

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request failed.");
  return data;
}

function DashboardView() {
  const [summary, setSummary] = useState(null);
  const [automations, setAutomations] = useState([]);
  const [error, setError] = useState("");

  async function refresh() {
    setError("");
    try {
      const [metrics, recent] = await Promise.all([
        api("/dashboard/summary"),
        api("/dashboard/automations"),
      ]);
      setSummary(metrics);
      setAutomations(recent.automations || []);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => { refresh(); }, []);

  if (error) return <div className="card error">{error}</div>;
  if (!summary) return <div className="card">Loading dashboard...</div>;

  const cards = [
    ["Total tickets", summary.total_tickets],
    ["Open tickets", summary.open_tickets],
    ["AI resolved", summary.ai_resolved],
    ["Escalated", summary.escalated_tickets],
    ["Software requests", summary.software_requests],
    ["Provisioning in progress", summary.provisioning_in_progress],
    ["Automation runs", summary.automation_runs],
    ["Completed automations", summary.completed_automations],
  ];

  return (
    <section>
      <div className="hero">
        <p className="eyebrow">SUPPORT OVERVIEW</p>
        <h1>ITSM Dashboard</h1>
        <p>Live totals from your helpdesk database.</p>
        <button className="secondary" onClick={refresh}>Refresh dashboard</button>
      </div>
      <div className="dashboard-grid">
        {cards.map(([label, value]) => (
          <div className="card metric-card" key={label}>
            <small>{label}</small>
            <strong>{value ?? 0}</strong>
          </div>
        ))}
      </div>
      <h2 className="article-heading">Recent automation status</h2>
      {automations.length === 0 ? <p className="muted">No automation runs recorded yet.</p> : (
        <div className="automation-list">{automations.map((run) => (
          <article className="card automation-row" key={run.id}>
            <div><b>{run.action?.replaceAll("_", " ") || "Automation"}</b><small>{run.request_number || run.servicenow_incident || ""}</small></div>
            <span className={`badge ${run.status === "Completed" ? "success" : "pending"}`}>{run.status || "In progress"}</span>
            <small>{run.created_at ? new Date(run.created_at).toLocaleString() : ""}</small>
          </article>
        ))}</div>
      )}
    </section>
  );
}

function KnowledgeView() {
  const [articles, setArticles] = useState([]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("All");

  useEffect(() => {
    api("/knowledge/articles")
      .then((data) => setArticles(data.articles || []))
      .catch((err) => setError(err.message));
  }, []);

  async function search(event) {
    event.preventDefault();
    setError("");
    setAnswer(null);
    try {
      const query = encodeURIComponent(question);
      setAnswer(await api(`/knowledge/search?q=${query}`));
    } catch (err) {
      setError(err.message);
    }
  }

  const categories = ["All", ...new Set(articles.map((article) => article.category))];
  const visibleArticles = category === "All"
    ? articles
    : articles.filter((article) => article.category === category);

  return (
    <section>
      <div className="hero">
        <p className="eyebrow">APPROVED IT GUIDANCE</p>
        <h1>Knowledge Base</h1>
        <p>Search support articles and see which source supports the answer.</p>
      </div>

      <div className="card knowledge-search">
        <form onSubmit={search}>
          <label htmlFor="kb-question">Ask a support question</label>
          <div className="search-row">
            <input
              id="kb-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="For example: How do I troubleshoot Outlook synchronization?"
              required
            />
            <button className="primary">Search</button>
          </div>
        </form>

        {error && <p className="error">{error}</p>}

        {answer && (
          <div className="answer">
            <b>{answer.found ? "Answer from approved knowledge" : "No approved answer found"}</b>
            <p>{answer.answer}</p>
            {answer.sources?.length > 0 && (
              <p className="sources">
                <b>Sources: </b>
                {answer.sources.map((source) => `${source.id} · ${source.title}`).join(", ")}
              </p>
            )}
            <p className="sources"><b>Retrieval confidence: </b>{Math.round((answer.retrieval_score || 0) * 100)}%</p>
          </div>
        )}
      </div>

      <div className="article-toolbar">
        <h2 className="article-heading">Support articles ({visibleArticles.length})</h2>
        <label>Category
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            {categories.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
      </div>
      <div className="article-grid">
        {visibleArticles.map((article) => (
          <article className="card article-card" key={article.id}>
            <span className="badge">{article.category}</span>
            <h3>{article.title}</h3>
            <p>{article.content}</p>
            <small>{article.id}</small>
          </article>
        ))}
      </div>
    </section>
  );
}

function SelfServiceView({ onAnalysis }) {
  const [description, setDescription] = useState("");
  const [result, setResult] = useState(null);
  const [workflow, setWorkflow] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [createTicket, setCreateTicket] = useState(true);
  const [conversation, setConversation] = useState([]);

  const examples = [
    "My VPN is not connecting. Authentication keeps failing.",
    "My password has expired.",
    "I need Visual Studio Code installed on my laptop.",
    "How do I troubleshoot Outlook synchronization?",
  ];

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    setWorkflow(null);
    try {
      const analyzed = await api("/tickets/intake", {
        method: "POST",
        body: JSON.stringify({ description, create_ticket: createTicket }),
      });
      setResult(analyzed);
      onAnalysis(analyzed);
      setConversation((turns) => [...turns, {
        question: description,
        answer: analyzed.suggested_resolution || "This request needs review by the IT support team.",
        intent: analyzed.intent,
      }]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function runPasswordHelp() {
    setBusy(true);
    setError("");
    try {
      setWorkflow(await api("/automation/password-reset", {
        method: "POST",
        body: JSON.stringify({ description: result?.original_description || description, incident_number: result?.servicenow?.number }),
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function runVpnCheck() {
    setBusy(true);
    setError("");
    try {
      setWorkflow(await api("/automation/vpn-check", {
        method: "POST",
        body: JSON.stringify({ description: result?.original_description || description, incident_number: result?.servicenow?.number }),
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function startProvisioning() {
    const number = result?.servicenow?.number;
    if (!number) return;
    setBusy(true);
    setError("");
    try {
      setWorkflow(await api(
        `/provisioning/requests/${encodeURIComponent(number)}/provision`,
        { method: "POST" },
      ));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function validateProvisioning() {
    const number = workflow?.request_id;
    if (!number) return;
    setBusy(true);
    setError("");
    try {
      setWorkflow(await api(
        `/provisioning/requests/${encodeURIComponent(number)}/validate`,
        { method: "POST" },
      ));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="hero">
        <p className="eyebrow">IT SUPPORT, MADE SIMPLE</p>
        <h1>How can we help today?</h1>
        <p>Describe your issue or ask a question to find the right support path.</p>
      </section>

      <section className="grid">
        <div className="card form-card">
          <h2>Tell us what you need</h2>
          <p className="muted">Include what happened and any error message you saw.</p>
          <form onSubmit={submit}>
            <label htmlFor="description">Your request</label>
            <textarea
              id="description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="For example: My VPN is not connecting..."
              minLength={4}
              maxLength={2000}
              required
            />
            <label className="ticket-choice">
              <input type="checkbox" checked={createTicket} onChange={(event) => setCreateTicket(event.target.checked)} />
              Create a support ticket and ServiceNow reference
            </label>
            <div className="form-bottom">
              <small>Your request will be saved for support follow-up.</small>
              <button className="primary" disabled={busy}>
                {busy ? "Working..." : "Get help →"}
              </button>
            </div>
          </form>
          <div className="examples">
            <small>TRY AN EXAMPLE</small>
            {examples.map((item) => (
              <button key={item} type="button" onClick={() => setDescription(item)}>
                {item}
              </button>
            ))}
          </div>
        </div>

        <aside className="card guide">
          <div className="icon">✦</div>
          <h3>What happens next?</h3>
          <p className="muted">Your request is matched with the right support workflow.</p>
          <p>01 &nbsp; We understand your request</p>
          <p>02 &nbsp; We find approved guidance</p>
          <p>03 &nbsp; You get an answer or ticket reference</p>
        </aside>
      </section>

      {error && <div className="card error">{error}</div>}

      {conversation.length > 0 && (
        <section className="card conversation" aria-label="Support conversation">
          <h2>Support conversation</h2>
          {conversation.map((turn, index) => (
            <div className="conversation-turn" key={`${index}-${turn.question}`}>
              <p className="user-message"><b>You</b>{turn.question}</p>
              <p className="assistant-message"><b>Helpdesk AI · {turn.intent}</b>{turn.answer}</p>
            </div>
          ))}
        </section>
      )}

      {result && (
        <section className="card result">
          <div className="result-title">
            <div><p className="eyebrow">REQUEST ANALYSIS</p><h2>{result.short_description}</h2></div>
            <span className="badge">{result.intent}</span>
          </div>
          <div className="details">
            <div><small>Category</small><b>{result.category || "—"}</b></div>
            <div><small>Priority</small><b>{result.priority || "—"}</b></div>
            <div><small>Assignment group</small><b>{result.assignment_group || "—"}</b></div>
            <div><small>Confidence</small><b>{result.confidence ?? "—"}</b></div>
          </div>
          <div className="details extra-details">
            <div><small>Subcategory</small><b>{result.subcategory || "—"}</b></div>
            <div><small>Impact / urgency</small><b>{[result.impact, result.urgency].filter(Boolean).join(" / ") || "—"}</b></div>
            <div><small>Ticket outcome</small><b>{result.ticket_created ? "Created" : "Not created"}</b></div>
            <div><small>Confidence threshold</small><b>35%</b></div>
          </div>
          <p className={result.ticket_created ? "created-state" : "not-created-state"}>
            {result.ticket_created
              ? `Ticket created · ${result.ticket_id} · ${result.servicenow?.number} (${result.record_status})`
              : "No ticket or ServiceNow record created. This request was saved as a chat analysis only."}
          </p>
          {result.suggested_resolution && (
            <div className="answer"><b>Suggested next step</b><p>{result.suggested_resolution}</p></div>
          )}
          {result.knowledge_sources?.length > 0 && (
            <p className="sources"><b>Sources: </b>
              {result.knowledge_sources.map((source) => `${source.id} · ${source.title}`).join(", ")}
            </p>
          )}
          {result.servicenow && (
            <p className="reference">
              Mock ServiceNow {result.servicenow.type}: <b>{result.servicenow.number}</b>
            </p>
          )}
          {result.needs_human_review && <p className="review">Low confidence or unsupported guidance. Routed for human review{result.servicenow?.number ? ` under ${result.servicenow.number}` : "; create a ticket to escalate"}.</p>}
          {result.intent === "Incident" && result.subcategory === "VPN" && (
            <button className="secondary" onClick={runVpnCheck} disabled={busy || !result.ticket_created}>Run mock VPN diagnostics</button>
          )}
          {result.intent === "Automatable Issue" && (
            <button className="secondary" onClick={runPasswordHelp} disabled={busy || !result.ticket_created}>
              Run password self-help
            </button>
          )}
          {(result.intent === "Incident" && result.subcategory === "VPN" || result.intent === "Automatable Issue") && !result.ticket_created && (
            <p className="muted">Create a ticket before running the workflow so its ServiceNow incident can be updated.</p>
          )}
          {result.servicenow?.type === "Service Request" && result.software_catalog_supported && !workflow && (
            <button className="secondary" onClick={startProvisioning} disabled={busy}>
              Start mock provisioning
            </button>
          )}
          {result.servicenow?.type === "Service Request" && !result.software_catalog_supported && (
            <p className="review">The ServiceNow request was created for catalogue review. Mock provisioning is unavailable for unlisted items.</p>
          )}
        </section>
      )}

      {workflow && (
        <section className="card result">
          <p className="eyebrow">WORKFLOW RESULT</p>
          <h2>{workflow.software || workflow.result}</h2>
          <p>{workflow.message}</p>
          {workflow.servicenow_incident && <p>Incident: <b>{workflow.servicenow_incident}</b></p>}
          {workflow.servicenow_incident && <p>ServiceNow incident status: <b>{workflow.incident_status}</b></p>}
          {workflow.request_id && <p>Request: <b>{workflow.request_id}</b></p>}
          <p>Status: <span className="badge">{workflow.status || workflow.incident_status}</span></p>
          {workflow.validation && <p>Validation: <b>{workflow.validation}</b></p>}
          {workflow.knowledge_source && <p className="sources">Knowledge source: <b>{workflow.knowledge_source.id} · {workflow.knowledge_source.title}</b></p>}
          {workflow.steps?.length > 0 && <ol className="workflow-steps">{workflow.steps.map((step) => <li key={step.step}><b>{step.step}:</b> {step.result}</li>)}</ol>}
          {workflow.status === "Provisioning" && (
            <button className="secondary" onClick={validateProvisioning} disabled={busy}>
              Validate mock provisioning
            </button>
          )}
        </section>
      )}
    </>
  );
}

function AnalysisView({ analysis }) {
  if (!analysis) return <div className="card">Submit a request in Employee Self-Service to view its AI analysis.</div>;
  return (
    <section>
      <div className="hero"><p className="eyebrow">ROUTING AND SAFETY</p><h1>AI Analysis</h1><p>Classification, confidence, grounding, ticket decision, and ITSM record.</p></div>
      <article className="card result">
        <div className="result-title"><div><p className="eyebrow">{analysis.intent}</p><h2>{analysis.short_description}</h2></div><span className="badge">{analysis.ticket_created ? "Ticket created" : "Analysis only"}</span></div>
        <p><b>Employee request:</b> {analysis.original_description}</p>
        {analysis.intent === "Service Request" && <p><b>Requested item:</b> {analysis.software} · {analysis.software_catalog_supported ? "Approved catalogue item" : "Needs catalogue review"}</p>}
        <div className="details analysis-details">
          <div><small>Category / subcategory</small><b>{[analysis.category, analysis.subcategory].filter(Boolean).join(" / ") || "—"}</b></div>
          <div><small>Priority</small><b>{analysis.priority || "—"}</b></div>
          <div><small>Impact / urgency</small><b>{[analysis.impact, analysis.urgency].filter(Boolean).join(" / ") || "—"}</b></div>
          <div><small>Assignment group</small><b>{analysis.assignment_group || "—"}</b></div>
          <div><small>Confidence</small><b>{Math.round((analysis.confidence || 0) * 100)}%</b></div>
          <div><small>Human review</small><b>{analysis.needs_human_review ? "Required" : "Not required"}</b></div>
        </div>
        <p><b>Ticket decision:</b> {analysis.ticket_created ? `Created ${analysis.ticket_id}` : "Not created by user choice"}</p>
        {analysis.servicenow && <p className="reference"><b>Mock ServiceNow:</b> {analysis.servicenow.type} {analysis.servicenow.number} · {analysis.record_status}</p>}
        {analysis.suggested_resolution && <div className="answer"><b>Suggested resolution</b><p>{analysis.suggested_resolution}</p></div>}
        {analysis.knowledge_sources?.length > 0 && <p className="sources"><b>Knowledge sources:</b> {analysis.knowledge_sources.map((source) => `${source.id} · ${source.title}`).join(", ")}</p>}
        {analysis.needs_human_review && <p className="review">Escalation is needed because approved guidance was unavailable or confidence was low.</p>}
      </article>
      {analysis.servicenow?.type === "Incident" && <IncidentControl number={analysis.servicenow.number} />}
    </section>
  );
}

function IncidentControl({ number }) {
  const [incident, setIncident] = useState(null);
  const [status, setStatus] = useState("In Progress");
  const [workNotes, setWorkNotes] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function loadIncident() {
    setBusy(true);
    setMessage("");
    try {
      const data = await api(`/mock-servicenow/incidents/${encodeURIComponent(number)}`);
      setIncident(data);
      setStatus(data.status || "New");
      setWorkNotes(data.work_notes || "");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function updateIncident(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const data = await api(`/mock-servicenow/incidents/${encodeURIComponent(number)}`, {
        method: "PATCH",
        body: JSON.stringify({ status, work_notes: workNotes }),
      });
      setIncident(data);
      setMessage("Mock ServiceNow incident updated.");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card incident-control">
      <div className="result-title"><div><p className="eyebrow">MOCK SERVICENOW</p><h2>Incident {number}</h2></div><button className="secondary" onClick={loadIncident} disabled={busy}>Load incident</button></div>
      {incident && <>
        <div className="details"><div><small>Category</small><b>{incident.category} / {incident.subcategory}</b></div><div><small>Priority</small><b>{incident.priority}</b></div><div><small>Assignment</small><b>{incident.assignment_group}</b></div><div><small>Current status</small><b>{incident.status}</b></div></div>
        <p><b>Description:</b> {incident.description}</p>
        <form onSubmit={updateIncident} className="incident-update-form">
          <label>Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option>New</option><option>In Progress</option><option>Resolved</option><option>Closed</option></select></label>
          <label>Work notes<textarea value={workNotes} onChange={(event) => setWorkNotes(event.target.value)} maxLength={2000} /></label>
          <button className="primary" disabled={busy}>{busy ? "Saving..." : "Update ServiceNow incident"}</button>
        </form>
      </>}
      {message && <p className={message.includes("updated") ? "created-state" : "error"}>{message}</p>}
    </section>
  );
}

export default function App() {
  const [page, setPage] = useState("self-service");
  const [analysis, setAnalysis] = useState(null);

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="logo">H</div>
        <h2>Helpdesk<span>AI</span></h2>
        <p className="nav-label">WORKSPACE</p>
        <button className={`nav ${page === "self-service" ? "active" : ""}`} onClick={() => setPage("self-service")}>
          ▣ &nbsp; Employee self-service
        </button>
        <button className={`nav ${page === "dashboard" ? "active" : ""}`} onClick={() => setPage("dashboard")}>
          ▤ &nbsp; ITSM Dashboard
        </button>
        <button className={`nav ${page === "knowledge" ? "active" : ""}`} onClick={() => setPage("knowledge")}>
          ◫ &nbsp; Knowledge Base
        </button>
        <button className={`nav ${page === "analysis" ? "active" : ""}`} onClick={() => setPage("analysis")}>
          ✦ &nbsp; AI Analysis
        </button>
        <div className="support"><i /> Support services online</div>
      </aside>

      <main className="main">
        <header>
          <span>AI ITSM Helpdesk / {page}</span>
          <b>Employee</b>
        </header>
        {page === "self-service" && <SelfServiceView onAnalysis={setAnalysis} />}
        {page === "dashboard" && <DashboardView />}
        {page === "knowledge" && <KnowledgeView />}
        {page === "analysis" && <AnalysisView analysis={analysis} />}
        <footer>AI ITSM Helpdesk · Prototype support portal</footer>
      </main>
    </div>
  );
}
