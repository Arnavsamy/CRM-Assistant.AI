"use client";

import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3, Building2, CalendarDays, CheckCircle2, ChevronRight, ExternalLink,
  LayoutDashboard, Loader2, Mail, Menu, MessageSquare, Plus, RefreshCw,
  Search, Send, Settings, Sparkles, Pencil, Users, X, Bot, ClipboardCheck, Calculator, AlertTriangle, FileText,
  PanelLeftClose, PanelLeftOpen, Trash2,
} from "lucide-react";
import { api } from "@/lib/api";

type View = "overview" | "chat" | "discovery" | "accounts" | "leads" | "drafts" | "analytics" | "agents" | "agents-call" | "agents-commercial" | "settings";
type Workspace = { id: string; company_name: string; company_description: string; product_name: string; product_description: string; email: string };
type Account = { id: string; search_id?: string; name: string; domain?: string; industry?: string; description?: string; website?: string; match_score?: number; confidence?: number; status?: string; verified?: boolean; why_recommended?: string; pain_points?: string[] };
type Lead = { id: string; company_id: string; status: string; contact_email?: string | null; company?: Account };
type Draft = { id: string; lead_id: string; subject: string; body: string; status?: string; company?: Account };
type Message = { role: "user" | "assistant"; content: string };
type Conversation = { id: string; title: string; messages: Message[]; updatedAt: string; workspace: Workspace; searchId?: string };
type Task = { id: string; workspace_id: string; lead_id?: string | null; title: string; description?: string; status: string; priority: string; due_at?: string | null; source?: string; created_at?: string; completed_at?: string | null };
type LeadIntelligence = { lead_id: string; current_stage: string; analysis: { actual_stage: string; stage_confidence: number; competitor_signals: { name: string; evidence: string; confidence: number }[]; buyer_intent: string; blockers: string[]; next_action: { title: string; description: string; priority: string } }; task?: Task };
type TimelineEvent = { id: string; event_type: string; content: string; source?: string; metadata?: Record<string, any>; occurred_at?: string; created_at?: string };
type Timeline = { lead_id: string; events: TimelineEvent[]; stage_history: { id: string; old_stage?: string | null; new_stage: string; reason?: string; confidence?: number | null; created_at: string }[] };
type MeetingPayload = { title?: string; description: string; start_at: string; end_at: string; attendees: string[] };
type MeetingEvent = { event_id: string; title: string; description: string; start_at: string; end_at: string; attendees: string[]; html_link?: string; meet_link?: string; cancelled?: boolean };
type DebriefAnalysis = { summary: string; proposed_stage: string; stage_confidence: number; stakeholders: { name: string; role: string; evidence: string }[]; objections: string[]; contradictions: { previous: string; new: string; evidence: string }[]; next_action: { title: string; description: string; priority: string } };
type CommercialInput = { monthly_price: number; monthly_delivery_cost: number; contract_months: number; discount_percent: number; acquisition_cost: number };
type CommercialAnalysis = { lead_id: string; company_name: string; commercial_fit: string; recommendation: string; assumptions: CommercialInput; monthly_revenue: number; monthly_gross_profit: number; gross_margin_percent: number; contract_value: number; estimated_contract_profit: number; break_even_months: number; estimated_budget_low: number; estimated_budget_high: number; budget_confidence: number; budget_basis: string };

const navItems: { id: View; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "chat", label: "Chief of Staff", icon: MessageSquare },
  { id: "discovery", label: "Discovery", icon: Search },
  { id: "accounts", label: "Accounts", icon: Building2 },
  { id: "leads", label: "Leads", icon: Users },
  { id: "drafts", label: "Email drafts", icon: Mail },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "agents", label: "Agents", icon: Bot },
  { id: "agents-call", label: "Call Analysis", icon: ClipboardCheck },
  { id: "agents-commercial", label: "Commercial Fit", icon: Calculator },
  { id: "settings", label: "Settings", icon: Settings },
];

const emptyWorkspace = { company_name: "", company_description: "", product_name: "", product_description: "", email: "" };
const draftCacheKey = (email: string) => `outreach_email_drafts:${email.toLowerCase()}`;
const discardedDraftsKey = (email: string) => `outreach_discarded_drafts:${email.toLowerCase()}`;
const conversationsKey = (email: string) => `outreach_conversations:${email.toLowerCase()}`;
const workspacesKey = "outreach_workspaces";
const newConversation = (workspace: Workspace): Conversation => ({ id: crypto.randomUUID(), title: "New conversation", messages: [], updatedAt: new Date().toISOString(), workspace });

function scoreColor(score = 0) { return score >= 75 ? "score-high" : score >= 50 ? "score-medium" : "score-low"; }
function StatusPill({ children }: { children: ReactNode }) { return <span className="status-pill">{children}</span>; }
function PencilMark() { return <Pencil size={19} strokeWidth={1.7} aria-hidden="true" />; }

function AccountCard({ account, onEmail }: { account: Account; onEmail?: () => void }) {
  const score = account.match_score ?? 0;
  return <article className="account-card"><div className="account-card-top"><div className="company-mark">{account.name?.slice(0, 1).toUpperCase()}</div><div className="min-w-0 flex-1"><h3 className="truncate font-semibold text-[var(--ink)]">{account.name}</h3><p className="truncate text-xs text-[var(--muted)]">{account.domain || "Domain unavailable"}</p></div><span className={`score-badge ${scoreColor(score)}`}>{score}%</span></div><div className="mt-4 flex flex-wrap gap-2"><StatusPill>{account.industry || "Unknown industry"}</StatusPill><StatusPill>{account.verified ? "Verified" : "Needs verification"}</StatusPill></div><p className="mt-4 line-clamp-3 text-sm leading-6 text-[var(--muted)]">{account.description || account.why_recommended || "No description available yet."}</p><div className="mt-5 flex items-center justify-between border-t border-[var(--line)] pt-4"><span className="text-xs text-[var(--muted)]">{account.status || "New"}</span><div className="flex gap-2">{account.website && <a className="icon-link" href={account.website} target="_blank" rel="noreferrer" aria-label="Open website"><ExternalLink size={15} /></a>}{onEmail && <button className="text-button" onClick={onEmail}>Draft email <ChevronRight size={14} /></button>}</div></div></article>;
}

function LocalAuthGate() {
  const [authenticated, setAuthenticated] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const saved = window.localStorage.getItem("outreach-local-auth");
    if (saved === "admin") {
      setAuthenticated(true);
    }
    const style = document.createElement("style");
    style.dataset.localAuth = "true";
    style.textContent = `
      .local-auth-page{min-height:100vh;display:grid;place-items:center;padding:32px;background:#1f1f1f}
      .local-auth-card{width:min(1120px,100%);min-height:680px;display:grid;grid-template-columns:1fr 1fr;background:#fff;border-radius:28px;overflow:hidden;box-shadow:0 24px 80px rgba(0,0,0,.25)}
      .local-auth-visual{padding:56px;display:flex;flex-direction:column;justify-content:flex-end;color:#fff;background:linear-gradient(145deg,#873f39,#bd8c86)}
      .local-auth-mark{width:64px;height:64px;display:grid;place-items:center;border-radius:18px;background:#f1dfdc;color:#873f39;font:36px Georgia;margin-bottom:auto}
      .local-auth-eyebrow{letter-spacing:.16em;font-size:12px;font-weight:700}.local-auth-visual h1{max-width:430px;font:48px/1.05 Georgia;margin:0 0 18px}.local-auth-visual p{max-width:420px;color:#f9e9e6;line-height:1.6}
      .local-auth-form-wrap{padding:64px 72px;display:flex;flex-direction:column;justify-content:center}.local-auth-brand{font-weight:700;color:#8b6429;margin-bottom:42px}.local-auth-brand span{font-size:22px}.local-auth-form-wrap h2{font:38px Georgia;margin:0 0 8px}.local-auth-subtitle{color:#777;margin:0 0 30px}.local-auth-form{display:grid;gap:18px}.local-auth-form label{display:grid;gap:8px;color:#555;font-size:14px}.local-auth-form input{height:52px;border:1px solid #dedbd6;border-radius:14px;padding:0 16px;font-size:15px;outline:none}.local-auth-form input:focus{border-color:#a45a51;box-shadow:0 0 0 3px #f2dfdc}.local-auth-primary{height:52px;border:0;border-radius:14px;background:#9c433b;color:#fff;font-weight:700;font-size:15px;cursor:pointer}.local-auth-provider{height:50px;border:0;border-radius:14px;background:#f1f1f3;font-weight:600;cursor:pointer}.local-auth-divider{display:flex;align-items:center;gap:12px;color:#999;font-size:13px}.local-auth-divider:before,.local-auth-divider:after{content:"";height:1px;background:#e5e2de;flex:1}.local-auth-link{border:0;background:none;color:#8c443d;font-weight:600;cursor:pointer;padding:4px}.local-auth-error{color:#a62f29;font-size:13px;line-height:1.4}.local-auth-note{text-align:center;color:#aaa;font-size:12px;margin-top:26px}.local-logout-button{position:fixed;right:24px;top:20px;z-index:50;border:1px solid #e2d8d4;background:#fff;border-radius:10px;padding:9px 14px;cursor:pointer}@media(max-width:800px){.local-auth-card{grid-template-columns:1fr}.local-auth-visual{min-height:260px;padding:32px}.local-auth-visual h1{font-size:36px}.local-auth-form-wrap{padding:40px 28px}}
    `;
    document.head.appendChild(style);
    return () => style.remove();
  }, []);

  if (authenticated) {
    return (
      <>
        <button
          type="button"
          className="local-logout-button"
          onClick={() => {
            window.localStorage.removeItem("outreach-local-auth");
            setAuthenticated(false);
          }}
        >
          Log out
        </button>
        <DashboardHomePage />
      </>
    );
  }

  const signIn = (event: React.FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !password.trim()) {
      setError("Enter your email and password to continue.");
      return;
    }
    setError("Email login is ready for connection to your auth provider. Use Admin Access for this local demo.");
  };

  const adminSignIn = (event: React.FormEvent) => {
    event.preventDefault();
    if (adminName === "admin123" && adminPassword === "admin123") {
      window.localStorage.setItem("outreach-local-auth", "admin");
      setAuthenticated(true);
      setError("");
    } else {
      setError("Incorrect admin name or password.");
    }
  };

  return (
    <main className="local-auth-page">
      <section className="local-auth-card" aria-label="Outreach login">
        <div className="local-auth-visual">
          <div className="local-auth-mark">O</div>
          <p className="local-auth-eyebrow">OUTREACH</p>
          <h1>Turn every conversation into your next opportunity.</h1>
          <p>Discover accounts, understand buying intent, and move outreach forward from one calm workspace.</p>
        </div>
        <div className="local-auth-form-wrap">
          <div className="local-auth-brand"><span>◈</span> Outreach</div>
          <h2>{showAdmin ? "Admin access" : "Log in to your account"}</h2>
          <p className="local-auth-subtitle">{showAdmin ? "Use your local administrator credentials." : "Welcome back! Enter your details to continue."}</p>
          {!showAdmin ? (
            <form onSubmit={signIn} className="local-auth-form">
              <label>Email<input type="email" placeholder="Enter your email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
              <label>Password<input type="password" placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
              <button className="local-auth-primary" type="submit">Login</button>
              <div className="local-auth-divider"><span>or continue with</span></div>
              <button type="button" className="local-auth-provider" onClick={() => setError("Google login will be connected after deployment.")}>Continue with Google</button>
              <button type="button" className="local-auth-link" onClick={() => { setShowAdmin(true); setError(""); }}>Admin access</button>
            </form>
          ) : (
            <form onSubmit={adminSignIn} className="local-auth-form">
              <label>Admin name<input autoFocus value={adminName} onChange={(e) => setAdminName(e.target.value)} placeholder="Enter admin name" /></label>
              <label>Password<input type="password" value={adminPassword} onChange={(e) => setAdminPassword(e.target.value)} placeholder="Enter admin password" /></label>
              <button className="local-auth-primary" type="submit">Enter dashboard</button>
              <button type="button" className="local-auth-link" onClick={() => { setShowAdmin(false); setError(""); }}>Back to email login</button>
            </form>
          )}
          {error && <p className="local-auth-error" role="alert">{error}</p>}
          <p className="local-auth-note">Local demo access only</p>
        </div>
      </section>
    </main>
  );
}

export default function HomePage() {
  return <LocalAuthGate />;
}

function DashboardHomePage() {
  const [view, setView] = useState<View>("overview");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [workspaceForm, setWorkspaceForm] = useState(emptyWorkspace);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [intelligence, setIntelligence] = useState<Record<string, LeadIntelligence>>({});
  const [timelines, setTimelines] = useState<Record<string, Timeline>>({});
  const [analyzingLead, setAnalyzingLead] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [workspaceHistory, setWorkspaceHistory] = useState<Workspace[]>([]);
  const [activeConversationId, setActiveConversationId] = useState("");
  const [analytics, setAnalytics] = useState<Record<string, any>>({});
  const [debriefResult, setDebriefResult] = useState<{ leadId: string; notes: string; analysis: DebriefAnalysis } | null>(null);
  const [commercialResult, setCommercialResult] = useState<CommercialAnalysis | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [searchId, setSearchId] = useState("");
  const [job, setJob] = useState<Record<string, any> | null>(null);
  const [connected, setConnected] = useState(false);
  const [calendarConnected, setCalendarConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [workspaceMenuOpen, setWorkspaceMenuOpen] = useState(false);
  const [agentTab, setAgentTab] = useState<"debrief" | "commercial">("debrief");
  const workspaceLoadToken = useRef(0);
  useEffect(() => {
    document.body.dataset.agentTab = agentTab;
    document.body.dataset.agentOpen = view === "agents" || view === "agents-call" || view === "agents-commercial" ? "true" : "false";
    const syncAgentNav = () => {
      document.querySelectorAll<HTMLElement>(".nav-list .nav-item, .nav-list button").forEach((item) => {
        const label = item.textContent?.replace(/\s+/g, " ").trim() || "";
        if (label.includes("Call Analysis") || label.includes("Commercial Fit")) {
          item.style.setProperty("display", document.body.dataset.agentOpen === "true" ? "flex" : "none", "important");
        }
        if (label.includes("Settings")) item.style.setProperty("display", "flex", "important");
      });
    };
    requestAnimationFrame(syncAgentNav);
  }, [agentTab, view]);
  useEffect(() => {
    const existing = document.getElementById("analytics-visuals");
    existing?.remove();
    if (view !== "analytics") return;
    const host = document.createElement("section");
    host.id = "analytics-visuals";
    host.className = "analytics-visuals analytics-drawer";
    const style = document.createElement("style");
    style.textContent = `
      .analytics-visuals{display:grid;grid-template-columns:1.35fr 1fr;gap:16px;margin:22px 0 28px;padding:0 2px}
      .analytics-open-button{display:inline-flex;align-items:center;border:1px solid #e0d6d1;background:#fff;border-radius:8px;padding:7px 11px;color:#873f39;font-size:12px;font-weight:700;cursor:pointer;margin:0}.analytics-open-button:hover{background:#f7eeeb}
      .analytics-drawer{display:none;position:fixed;z-index:40;right:0;top:0;width:min(720px,92vw);height:100vh;overflow-y:auto;margin:0;padding:38px 28px 32px;background:#fbf9f7;box-shadow:-18px 0 50px rgba(52,35,27,.18);grid-template-columns:1fr}.analytics-drawer.is-open{display:grid}.analytics-drawer-close{position:absolute;left:24px;right:auto;top:20px;border:1px solid #e0d6d1;background:#fff;border-radius:9px;width:34px;height:34px;font-size:22px;line-height:1;color:#6d5c55;cursor:pointer}.analytics-drawer-title{margin:8px 0 8px;padding-left:48px}.analytics-drawer-title h2{font:30px Georgia;margin:4px 0 0;color:#29221f}
      .analytics-chart-card{background:#fff;border:1px solid #e7e1dc;border-radius:18px;padding:24px;box-shadow:0 10px 30px rgba(72,45,32,.05)}
      .analytics-chart-heading{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}.analytics-chart-kicker{font-size:11px;letter-spacing:.14em;font-weight:700;color:#9a4038}.analytics-chart-card h3{font:25px Georgia;margin:7px 0 0;color:#27211e}.analytics-chart-total{font-size:13px;color:#786d67}
      .analytics-chart-card svg{width:100%;height:auto;display:block}.chart-grid{stroke:#eee7e1;stroke-width:1}.chart-line{fill:none;stroke:#9a4038;stroke-width:4;stroke-linecap:round}.chart-area{fill:#f2dfdc;opacity:.55}.chart-labels{fill:#988c85;font:12px sans-serif}
      .analytics-bars{display:grid;gap:15px;padding-top:10px}.analytics-bars>div{display:grid;grid-template-columns:120px 1fr 24px;gap:10px;align-items:center;font-size:13px;color:#716761}.analytics-bars i,.analytics-funnel i{height:10px;border-radius:999px;background:linear-gradient(90deg,#9a4038 var(--value),#f0e9e4 var(--value));display:block}.analytics-bars b,.analytics-funnel b{font-size:13px;color:#29221f;text-align:right}
      .analytics-funnel-card{grid-column:1 / -1}.analytics-funnel{display:grid;gap:13px;padding-top:10px}.analytics-funnel>div{display:grid;grid-template-columns:120px 1fr 28px;gap:12px;align-items:center;font-size:13px;color:#716761}.analytics-funnel i{height:12px}.analytics-funnel>div:nth-child(2) i{opacity:.88}.analytics-funnel>div:nth-child(3) i{opacity:.74}.analytics-funnel>div:nth-child(4) i{opacity:.62}.analytics-funnel>div:nth-child(5) i{opacity:.5}
      @media(max-width:900px){.analytics-visuals{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
    host.innerHTML = `<button type="button" class="analytics-drawer-close" aria-label="Close analytics">×</button>
      <div class="analytics-drawer-title"><span class="analytics-chart-kicker">WORKSPACE INSIGHTS</span><h2>Analytics details</h2></div>
      <article class="analytics-chart-card"><div class="analytics-chart-heading"><div><span class="analytics-chart-kicker">ACTIVITY</span><h3>Workspace activity</h3></div><span class="analytics-chart-total">Last 7 days</span></div><svg viewBox="0 0 520 180" role="img" aria-label="Workspace activity trend"><path class="chart-grid" d="M20 145H500M20 100H500M20 55H500"/><path class="chart-line" d="M20 132 C75 120 78 116 125 122 S175 92 220 105 S270 75 320 88 S370 50 420 68 S470 42 500 48"/><path class="chart-area" d="M20 132 C75 120 78 116 125 122 S175 92 220 105 S270 75 320 88 S370 50 420 68 S470 42 500 48 L500 150 L20 150Z"/><g class="chart-labels"><text x="20" y="172">Mon</text><text x="175" y="172">Wed</text><text x="330" y="172">Fri</text><text x="475" y="172">Sun</text></g></svg></article>
      <article class="analytics-chart-card"><div class="analytics-chart-heading"><div><span class="analytics-chart-kicker">PIPELINE</span><h3>Lead stages</h3></div><span class="analytics-chart-total">15 leads</span></div><div class="analytics-bars"><div><span>New</span><i style="--value:100%"></i><b>15</b></div><div><span>Qualified</span><i style="--value:60%"></i><b>9</b></div><div><span>Meeting</span><i style="--value:27%"></i><b>4</b></div><div><span>Deals completed</span><i style="--value:13%"></i><b>2</b></div></div></article>
      <article class="analytics-chart-card analytics-funnel-card"><div class="analytics-chart-heading"><div><span class="analytics-chart-kicker">OUTREACH</span><h3>Conversion funnel</h3></div><span class="analytics-chart-total">Current cycle</span></div><div class="analytics-funnel"><div><span>Discovered</span><i style="--value:100%"></i><b>119</b></div><div><span>Qualified</span><i style="--value:35%"></i><b>42</b></div><div><span>Replied</span><i style="--value:15%"></i><b>18</b></div><div><span>Meetings</span><i style="--value:7%"></i><b>8</b></div><div><span>Deals completed</span><i style="--value:3%"></i><b>3</b></div></div></article>`;
    const target = document.querySelector("main") || document.body;
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "analytics-open-button";
    openButton.textContent = "View analytics";
    openButton.addEventListener("click", () => host.classList.add("is-open"));
    host.querySelector(".analytics-drawer-close")?.addEventListener("click", () => host.classList.remove("is-open"));
    const performanceLabel = Array.from(target.querySelectorAll<HTMLElement>("*"))
      .find((node) => node.textContent?.trim() === "WORKSPACE PERFORMANCE");
    if (performanceLabel?.parentElement) {
      performanceLabel.parentElement.style.display = "flex";
      performanceLabel.parentElement.style.alignItems = "center";
      performanceLabel.parentElement.style.justifyContent = "space-between";
      performanceLabel.parentElement.appendChild(openButton);
    } else {
      target.prepend(openButton);
    }
    target.appendChild(host);
    return () => { openButton.remove(); host.remove(); style.remove(); };
  }, [view]);
  useEffect(() => {
    const style = document.createElement("style");
    style.dataset.agentTabs = "minimal";
    style.textContent = `
      body[data-agent-tab="commercial"] .agents-shell > :first-child { display: none; }
      body[data-agent-tab="debrief"] .agents-shell > :last-child { display: none; }
      .nav-list .nav-item:nth-child(9), .nav-list .nav-item:nth-child(10) { display: none !important; }
      body[data-agent-open="true"] .nav-list .nav-item:nth-child(9),
      body[data-agent-open="true"] .nav-list .nav-item:nth-child(10) { display: flex !important; }
      body[data-agent-tab="debrief"] .nav-list .nav-item:nth-child(9),
      body[data-agent-tab="commercial"] .nav-list .nav-item:nth-child(10) {
        background: transparent !important; color: inherit !important; font-weight: inherit !important;
      }
      body[data-agent-tab="debrief"] .nav-list .nav-item:nth-child(9)::before,
      body[data-agent-tab="commercial"] .nav-list .nav-item:nth-child(10)::before { color: var(--red-dark); }
    `;
    document.head.appendChild(style);
    return () => style.remove();
  }, []);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!workspace?.email) return;
    if (drafts.length > 0) window.localStorage.setItem(draftCacheKey(workspace.email), JSON.stringify(drafts));
  }, [drafts, workspace?.email]);

  const loadData = async (currentWorkspace: Workspace, currentSearchId = searchId) => {
    const loadToken = ++workspaceLoadToken.current;
    try {
      const [accountData, analyticsData, draftData] = await Promise.all([
        api<{ accounts: Account[] }>(`/api/workspaces/${currentWorkspace.id}/accounts`),
        api<Record<string, any>>(`/api/analytics?email=${encodeURIComponent(currentWorkspace.email)}`),
        api<{ drafts: Draft[] }>(`/api/email-drafts?email=${encodeURIComponent(currentWorkspace.email)}`),
      ]);
      if (loadToken !== workspaceLoadToken.current) return;
      const cachedDrafts = (() => { try { return JSON.parse(window.localStorage.getItem(draftCacheKey(currentWorkspace.email)) || "[]") as Draft[]; } catch { return []; } })();
      const discarded = (() => { try { return new Set(JSON.parse(window.localStorage.getItem(discardedDraftsKey(currentWorkspace.email)) || "[]") as string[]); } catch { return new Set<string>(); } })();
      const remoteDrafts = draftData.drafts || [];
      const mergedDrafts = [...remoteDrafts, ...cachedDrafts.filter((draft) => !remoteDrafts.some((item) => item.id === draft.id || item.lead_id === draft.lead_id))].filter((draft) => !discarded.has(draft.id) && !discarded.has(draft.lead_id));
      setAccounts(accountData.accounts || []); setLeads([]); setSearchId(""); setJob(null); setIntelligence({}); setTimelines({}); setAnalytics(analyticsData || {}); setDrafts(mergedDrafts);
      try { const taskData = await api<{ tasks: Task[] }>(`/api/workspaces/${currentWorkspace.id}/tasks/today`); if (loadToken === workspaceLoadToken.current) setTasks(taskData.tasks || []); } catch { if (loadToken === workspaceLoadToken.current) setTasks([]); }
      try { const google = await api<{ connected: boolean }>(`/api/integrations/google/status?workspace_id=${encodeURIComponent(currentWorkspace.id)}`); if (loadToken === workspaceLoadToken.current) setCalendarConnected(Boolean(google.connected)); } catch { if (loadToken === workspaceLoadToken.current) setCalendarConnected(false); }
      const accountSearchId = accountData.accounts?.find((account) => account.search_id)?.search_id;
      const candidateSearchIds = Array.from(new Set([currentSearchId, accountSearchId].filter(Boolean) as string[]));
      let loadedLeads: Lead[] = [];
      let loadedSearchId = "";
      for (const candidate of candidateSearchIds) {
        const leadData = await api<{ leads: Lead[] }>(`/api/searches/${candidate}/leads`);
        if (loadToken !== workspaceLoadToken.current) return;
        if (leadData.leads?.length) { loadedLeads = leadData.leads; loadedSearchId = candidate; break; }
      }
      if (loadedSearchId) { setSearchId(loadedSearchId); window.localStorage.setItem("outreach_search_id", loadedSearchId); setLeads(loadedLeads); setAccounts(loadedLeads.map((lead) => lead.company).filter(Boolean) as Account[]); }
    } catch { /* The empty state remains usable while the backend is unavailable. */ }
  };

  useEffect(() => {
    const saved = window.localStorage.getItem("outreach_workspace"); const savedSearch = window.localStorage.getItem("outreach_search_id");
    let savedWorkspaces: Workspace[] = [];
    try { savedWorkspaces = JSON.parse(window.localStorage.getItem(workspacesKey) || "[]") as Workspace[]; } catch { savedWorkspaces = []; }
    if (!Array.isArray(savedWorkspaces)) savedWorkspaces = [];
    // Migrate workspace metadata from the per-workspace conversation caches
    // written by older versions that did not keep a workspace registry.
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (!key?.startsWith("outreach_conversations:")) continue;
      try {
        const cached = JSON.parse(window.localStorage.getItem(key) || "[]") as Conversation[];
        for (const conversation of Array.isArray(cached) ? cached : []) {
          const cachedWorkspace = conversation?.workspace;
          if (cachedWorkspace?.id && cachedWorkspace.email && !savedWorkspaces.some((item) => item.id === cachedWorkspace.id)) savedWorkspaces.push(cachedWorkspace);
        }
      } catch { /* Ignore malformed legacy cache entries. */ }
    }
    window.localStorage.setItem(workspacesKey, JSON.stringify(savedWorkspaces));
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as Workspace;
        if (parsed && parsed.id && parsed.email) {
          savedWorkspaces = [parsed, ...savedWorkspaces.filter((item) => item.id !== parsed.id)];
          setWorkspaceHistory(savedWorkspaces);
          window.localStorage.setItem(workspacesKey, JSON.stringify(savedWorkspaces));
          setWorkspace(parsed); setWorkspaceForm(parsed); void loadData(parsed, savedSearch || undefined);
        } else {
          window.localStorage.removeItem("outreach_workspace");
        }
      } catch {
        window.localStorage.removeItem("outreach_workspace");
        window.localStorage.removeItem("outreach_search_id");
      }
    }
    if (!saved) setWorkspaceHistory(savedWorkspaces);
    if (savedSearch) setSearchId(savedSearch);
    const checkHealth = () => api<{ status: string }>("/health").then(() => setConnected(true)).catch(() => setConnected(false));
    void checkHealth();
    const healthTimer = window.setInterval(checkHealth, 5000);
    return () => window.clearInterval(healthTimer);
  }, []);
  // Render's free service can sleep. Once it wakes up, retry the initial
  // workspace load so the page does not stay stuck in its empty state.
  useEffect(() => {
    if (!connected || !workspace) return;
    void loadData(workspace, searchId || undefined);
  }, [connected, workspace?.id]);
  useEffect(() => {
    if (!workspace?.email) return;
    let saved: Conversation[] = [];
    try { saved = JSON.parse(window.localStorage.getItem(conversationsKey(workspace.email)) || "[]") as Conversation[]; } catch { saved = []; }
    const fallbackSearchId = window.localStorage.getItem("outreach_search_id") || undefined;
    const valid = Array.isArray(saved)
      ? saved
        .filter((item) => item && item.id && Array.isArray(item.messages) && (!item.workspace?.id || item.workspace.id === workspace.id))
        .map((item) => ({ ...item, workspace: item.workspace || workspace, searchId: item.searchId || fallbackSearchId }))
      : [];
    if (valid.length) {
      setConversations(valid);
      setActiveConversationId(valid[0].id);
      setMessages(valid[0].messages);
      return;
    }
    void api<{ messages: Message[] }>(`/api/workspaces/${workspace.id}/messages`).then((result) => {
      const previous = result.messages || [];
      const migrated = previous.length ? [{ ...newConversation(workspace), title: "Previous conversation", messages: previous }] : [newConversation(workspace)];
      setConversations(migrated);
      setActiveConversationId(migrated[0].id);
      setMessages(migrated[0].messages);
    }).catch(() => {
      const fresh = newConversation(workspace);
      setConversations([fresh]);
      setActiveConversationId(fresh.id);
      setMessages([]);
    });
  }, [workspace?.id]);
  useEffect(() => {
    if (!workspace?.email || !conversations.length) return;
    window.localStorage.setItem(conversationsKey(workspace.email), JSON.stringify(conversations));
  }, [conversations, workspace?.email]);
  useEffect(() => { if (view === "agents-call" || view === "agents-commercial") { const tab = view === "agents-commercial" ? "commercial" : "debrief"; setAgentTab(tab); document.body.dataset.agentTab = tab; window.dispatchEvent(new Event("agent-tab-change")); setView("agents"); } }, [view]);
  useEffect(() => { if (!workspace) return; const interval = window.setInterval(() => void loadData(workspace), 15000); return () => window.clearInterval(interval); }, [workspace, searchId]);
  useEffect(() => {
    if (job && (job.status === "queued" || job.status === "running") && accounts.length > 0) {
      setJob((current) => current ? { ...current, status: "completed", companies_found: current.companies_found || accounts.length } : current);
    }
  }, [accounts.length, job?.status]);

  const createWorkspace = async (event: FormEvent) => { event.preventDefault(); setBusy(true); setError(""); try { const result = await api<{ workspace: Workspace }>("/api/workspaces", { method: "POST", body: workspaceForm }); const fresh = newConversation(result.workspace); const nextHistory = [result.workspace, ...workspaceHistory.filter((item) => item.id !== result.workspace.id)]; setWorkspaceHistory(nextHistory); window.localStorage.setItem(workspacesKey, JSON.stringify(nextHistory)); setWorkspace(result.workspace); setWorkspaceForm(result.workspace); setConversations([fresh]); setActiveConversationId(fresh.id); setMessages([]); setChatInput(""); window.localStorage.setItem("outreach_workspace", JSON.stringify(result.workspace)); window.localStorage.removeItem("outreach_search_id"); setView("chat"); } catch (err) { setError(err instanceof Error ? err.message : "Could not create workspace."); } finally { setBusy(false); } };

  const updateConversationMessages = (next: Message[]) => { setMessages(next); setConversations((current) => current.map((conversation) => conversation.id === activeConversationId ? { ...conversation, messages: next, title: conversation.title === "New conversation" && next.find((message) => message.role === "user") ? next.find((message) => message.role === "user")!.content.slice(0, 42) + (next.find((message) => message.role === "user")!.content.length > 42 ? "…" : "") : conversation.title, updatedAt: new Date().toISOString() } : conversation)); };
  const selectConversation = (id: string) => { const selected = conversations.find((conversation) => conversation.id === id); if (!selected) return; setActiveConversationId(id); setMessages(selected.messages); setChatInput(""); if (selected.workspace?.id && selected.workspace.id !== workspace?.id) { setWorkspace(selected.workspace); setWorkspaceForm(selected.workspace); window.localStorage.setItem("outreach_workspace", JSON.stringify(selected.workspace)); if (selected.searchId) window.localStorage.setItem("outreach_search_id", selected.searchId); else window.localStorage.removeItem("outreach_search_id"); void loadData(selected.workspace, selected.searchId || ""); } setView("chat"); };
  const deleteConversation = (id: string) => { const remaining = conversations.filter((conversation) => conversation.id !== id); const next = remaining.length ? remaining : (workspace ? [newConversation(workspace)] : []); setConversations(next); if (id === activeConversationId && next.length) { setActiveConversationId(next[0].id); setMessages(next[0].messages); setChatInput(""); } if (workspace?.email) window.localStorage.setItem(conversationsKey(workspace.email), JSON.stringify(next)); };
  const switchWorkspace = (id: string) => { const selected = workspaceHistory.find((item) => item.id === id); if (!selected || selected.id === workspace?.id) { setWorkspaceMenuOpen(false); return; } setWorkspace(selected); setWorkspaceForm(selected); window.localStorage.setItem("outreach_workspace", JSON.stringify(selected)); setWorkspaceMenuOpen(false); setView("overview"); void loadData(selected); };
  const startNewConversation = () => { setError(""); setWorkspace(null); setWorkspaceForm(emptyWorkspace); setMessages([]); setChatInput(""); setAccounts([]); setLeads([]); setDrafts([]); setTasks([]); setSearchId(""); setJob(null); setAnalytics({}); window.localStorage.removeItem("outreach_workspace"); window.localStorage.removeItem("outreach_search_id"); setView("overview"); setMobileNav(false); };
  const sendChat = async (event: FormEvent) => { event.preventDefault(); if (!workspace || !chatInput.trim()) return; const text = chatInput.trim(); setChatInput(""); const withUser = [...messages, { role: "user" as const, content: text }]; updateConversationMessages(withUser); setBusy(true); try { const result = await api<{ answer: string }>(`/api/workspaces/${workspace.id}/chat`, { method: "POST", body: { message: text } }); updateConversationMessages([...withUser, { role: "assistant", content: result.answer }]); } catch { updateConversationMessages([...withUser, { role: "assistant", content: "I could not reach the workspace service. Please check that FastAPI is running." }]); } finally { setBusy(false); } };

  const startDiscovery = async () => { if (!workspace) return; setBusy(true); setError(""); setView("discovery"); try { const result = await api<{ job: Record<string, any> }>(`/api/workspaces/${workspace.id}/jobs/discovery`, { method: "POST" }); setJob(result.job); const jobId = result.job.id as string; let current = result.job; for (let attempt = 0; attempt < 60; attempt += 1) { await new Promise((resolve) => window.setTimeout(resolve, 3000)); current = await api<Record<string, any>>(`/api/jobs/${jobId}`); setJob(current); if (current.status === "completed" || current.status === "failed") break; } if (current.status !== "completed" && current.status !== "failed") { throw new Error("Discovery timed out. Please try again; the free backend may still be waking up."); } if (current.status === "failed") { throw new Error(String(current.error || "Discovery failed.")); } if (current.status === "completed" && current.search_id) { const completedSearchId = current.search_id as string; setSearchId(completedSearchId); window.localStorage.setItem("outreach_search_id", completedSearchId); setConversations((currentConversations) => currentConversations.map((conversation) => conversation.id === activeConversationId ? { ...conversation, searchId: completedSearchId, updatedAt: new Date().toISOString() } : conversation)); await loadData(workspace, completedSearchId); } } catch (err) { setError(err instanceof Error ? err.message : "Discovery failed."); } finally { setBusy(false); } };

  const updateLead = async (leadId: string, status: string): Promise<boolean> => { setLeads((current) => current.map((lead) => lead.id === leadId ? { ...lead, status } : lead)); try { await api(`/api/leads/${leadId}/status`, { method: "PATCH", body: { status } }); if (status === "Contacted") { setDrafts((current) => current.filter((draft) => draft.lead_id !== leadId)); if (workspace?.email) { const key = discardedDraftsKey(workspace.email); const discarded = (() => { try { return new Set(JSON.parse(window.localStorage.getItem(key) || "[]") as string[]); } catch { return new Set<string>(); } })(); discarded.add(leadId); window.localStorage.setItem(key, JSON.stringify(Array.from(discarded))); } } return true; } catch { setError("Could not update lead status. Check that the backend is running and the lead still exists."); return false; } };
  const analyzeLead = async (leadId: string) => { if (!workspace) return; setAnalyzingLead(leadId); setError(""); try { const [result, timeline] = await Promise.all([api<{ status: string; result: LeadIntelligence }>(`/api/workspaces/${workspace.id}/leads/${leadId}/intelligence`, { method: "POST" }), api<Timeline>(`/api/leads/${leadId}/timeline`)]); setIntelligence((current) => ({ ...current, [leadId]: result.result })); setTimelines((current) => ({ ...current, [leadId]: timeline })); if (result.result.task) setTasks((current) => [result.result.task as Task, ...current.filter((task) => task.id !== result.result.task?.id)]); } catch (err) { setError(err instanceof Error ? err.message : "Lead analysis failed."); } finally { setAnalyzingLead(null); } };
  const loadTimeline = async (leadId: string): Promise<Timeline | undefined> => { try { const timeline = await api<Timeline>(`/api/leads/${leadId}/timeline`); setTimelines((current) => ({ ...current, [leadId]: timeline })); return timeline; } catch { setError("Could not load lead timeline."); return undefined; } };
  const completeTask = async (taskId: string) => { try { const result = await api<{ status: string; task: Task }>(`/api/tasks/${taskId}/complete`, { method: "PATCH" }); setTasks((current) => current.map((task) => task.id === taskId ? result.task : task).filter((task) => task.status !== "completed")); } catch { setError("Could not complete the task."); } };
  const createDraft = async (leadId: string) => { setBusy(true); setError(""); try { const result = await api<{ draft: Draft }>(`/api/leads/${leadId}/email`, { method: "POST" }); const discarded = (() => { try { return new Set(JSON.parse(window.localStorage.getItem(discardedDraftsKey(workspace?.email || "")) || "[]") as string[]); } catch { return new Set<string>(); } })(); discarded.delete(leadId); window.localStorage.setItem(discardedDraftsKey(workspace?.email || ""), JSON.stringify(Array.from(discarded))); setDrafts((current) => [...current.filter((draft) => draft.lead_id !== leadId), result.draft]); const statusUpdated = await updateLead(leadId, "Draft Ready"); if (!statusUpdated) setError("Draft generated successfully, but the lead status could not be updated."); setView("drafts"); } catch (err) { setError(err instanceof Error ? err.message : "Could not generate the email draft."); } finally { setBusy(false); } };
  const discardDraft = (draft: Draft) => { if (workspace?.email) { const key = discardedDraftsKey(workspace.email); const discarded = (() => { try { return new Set(JSON.parse(window.localStorage.getItem(key) || "[]") as string[]); } catch { return new Set<string>(); } })(); discarded.add(draft.id); discarded.add(draft.lead_id); window.localStorage.setItem(key, JSON.stringify(Array.from(discarded))); } setDrafts((current) => current.filter((item) => item.id !== draft.id && item.lead_id !== draft.lead_id)); };
  const connectCalendar = async () => { if (!workspace) return; setError(""); try { const result = await api<{ authorization_url: string }>(`/api/integrations/google/connect?workspace_id=${encodeURIComponent(workspace.id)}`); window.location.assign(result.authorization_url); } catch (err) { setError(err instanceof Error ? err.message : "Could not start Google Calendar connection."); } };
  const scheduleMeeting = async (leadId: string, payload: MeetingPayload) => { if (!workspace) throw new Error("Workspace is not loaded."); const result = await api<{ status: string; event_id: string; html_link?: string; meet_link?: string }>(`/api/workspaces/${workspace.id}/leads/${leadId}/calendar`, { method: "POST", body: payload }); setCalendarConnected(true); return result; };
  const rescheduleMeeting = async (leadId: string, eventId: string, payload: MeetingPayload) => { if (!workspace) throw new Error("Workspace is not loaded."); return api<{ status: string; event_id: string; html_link?: string; meet_link?: string }>(`/api/workspaces/${workspace.id}/leads/${leadId}/calendar/${eventId}`, { method: "PATCH", body: payload }); };
  const cancelMeeting = async (leadId: string, eventId: string) => { if (!workspace) throw new Error("Workspace is not loaded."); return api<{ status: string; event_id: string }>(`/api/workspaces/${workspace.id}/leads/${leadId}/calendar/${eventId}`, { method: "DELETE" }); };
  const analyzeDebrief = async (leadId: string, notes: string) => { if (!workspace) throw new Error("Workspace is not loaded."); setBusy(true); setError(""); try { const result = await api<{ status: string; analysis: DebriefAnalysis }>(`/api/workspaces/${workspace.id}/leads/${leadId}/debrief`, { method: "POST", body: { notes } }); setDebriefResult({ leadId, notes, analysis: result.analysis }); } catch (err) { setError(err instanceof Error ? err.message : "Could not analyze the call notes."); } finally { setBusy(false); } };
  const applyDebrief = async () => { if (!workspace || !debriefResult) return; setBusy(true); setError(""); try { await api(`/api/workspaces/${workspace.id}/leads/${debriefResult.leadId}/debrief`, { method: "POST", body: { notes: debriefResult.notes, analysis: debriefResult.analysis } }); await loadData(workspace); setDebriefResult(null); } catch (err) { setError(err instanceof Error ? err.message : "Could not apply the debrief."); } finally { setBusy(false); } };
  const analyzeCommercial = async (leadId: string, input: CommercialInput) => { if (!workspace) return; setBusy(true); setError(""); try { const result = await api<{ status: string; analysis: CommercialAnalysis }>(`/api/workspaces/${workspace.id}/leads/${leadId}/commercial-fit`, { method: "POST", body: input }); setCommercialResult(result.analysis); } catch (err) { setError(err instanceof Error ? err.message : "Could not calculate commercial fit."); } finally { setBusy(false); } };

  const title = navItems.find((item) => item.id === view)?.label || "Overview";
  const qualified = useMemo(() => accounts.filter((account) => (account.match_score || 0) >= 50), [accounts]);
  const workspaceOptions = useMemo(() => workspaceHistory, [workspaceHistory]);
  const content = !workspace && view === "overview" ? <Onboarding form={workspaceForm} setForm={setWorkspaceForm} onSubmit={createWorkspace} busy={busy} error={error} /> : <>{view === "overview" && workspace && <Overview workspace={workspace} accounts={accounts} qualified={qualified} analytics={analytics} tasks={tasks} onCompleteTask={completeTask} onChat={() => setView("chat")} onDiscovery={startDiscovery} onAccounts={() => setView("accounts")} />}{view === "chat" && workspace && <ChatView workspace={workspace} messages={messages} conversations={conversations} activeConversationId={activeConversationId} onSelectConversation={selectConversation} onDeleteConversation={deleteConversation} onNewConversation={startNewConversation} input={chatInput} setInput={setChatInput} onSubmit={sendChat} onDiscovery={startDiscovery} busy={busy} />}{view === "discovery" && <DiscoveryView job={job} accounts={accounts} onStart={startDiscovery} busy={busy} />}{view === "accounts" && <AccountsView accounts={accounts} onEmail={(account) => { const lead = leads.find((item) => item.company_id === account.id); if (lead) void createDraft(lead.id); }} />}{view === "leads" && <LeadsView leads={leads} onStatus={updateLead} onDraft={createDraft} onAnalyze={analyzeLead} onTimeline={loadTimeline} onSchedule={scheduleMeeting} onReschedule={rescheduleMeeting} onCancelMeeting={cancelMeeting} calendarConnected={calendarConnected} intelligence={intelligence} timelines={timelines} analyzingLead={analyzingLead} />}{view === "drafts" && <DraftsView drafts={drafts} onApprove={(leadId) => void updateLead(leadId, "Contacted")} onRegenerate={createDraft} onDiscard={discardDraft} />}{view === "analytics" && <AnalyticsView analytics={analytics} accounts={accounts} leads={leads} drafts={drafts} />}{view === "agents" && <div className="agents-shell"><AgentsView leads={leads} busy={busy} result={debriefResult} onAnalyze={analyzeDebrief} onApply={applyDebrief} onClear={() => setDebriefResult(null)} /><CommercialFitPanel leads={leads} busy={busy} result={commercialResult} onAnalyze={analyzeCommercial} onClear={() => setCommercialResult(null)} /></div>}{view === "settings" && workspace && <SettingsView connected={connected} calendarConnected={calendarConnected} workspace={workspace} onConnectCalendar={connectCalendar} onRefresh={() => void loadData(workspace)} />}</>;

  return <div className="app-shell"><aside className={`sidebar ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${mobileNav ? "sidebar-open" : ""}`}><div><div className="brand"><div className="brand-mark">O</div><div><strong>Outreach</strong><span>Revenue engine</span></div><button className="sidebar-toggle" aria-label={sidebarCollapsed ? "Open sidebar" : "Close sidebar"} onClick={() => setSidebarCollapsed((value) => !value)}>{sidebarCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}</button><button className="mobile-close" onClick={() => setMobileNav(false)}><X size={18} /></button></div>{workspace && <div className="workspace-switcher"><button type="button" className="workspace-switcher-trigger" onClick={() => setWorkspaceMenuOpen((open) => !open)}><div className="workspace-avatar">{workspace.company_name.slice(0, 1).toUpperCase()}</div><div className="min-w-0"><b className="truncate">{workspace.company_name}</b><span>{workspace.product_name || "Current workspace"}</span></div><ChevronRight size={15} /></button>{workspaceMenuOpen && <div className="workspace-menu">{workspaceOptions.map((item) => <button type="button" key={item.id} className={item.id === workspace.id ? "selected" : ""} onClick={() => switchWorkspace(item.id)}>{item.company_name}</button>)}</div>}</div>}<nav className="nav-list">{navItems.map(({ id, label, icon: Icon }) => <button key={id} className={`nav-item ${view === id ? "active" : ""}`} onClick={() => { setView(id); setMobileNav(false); }}><Icon size={17} /><span>{label}</span>{id === "drafts" && drafts.length > 0 && <em>{drafts.length}</em>}</button>)}</nav></div><div className="sidebar-bottom"><div className={`connection ${connected ? "online" : ""}`}><span className="connection-dot" /><div><b>{connected ? "System operational" : "Backend offline"}</b><small>{connected ? "FastAPI · PostgreSQL" : "Start FastAPI to sync"}</small></div></div><button className="new-chat-button" onClick={startNewConversation}><Plus size={16} /> New conversation</button></div></aside><main className="main-shell"><header className="topbar"><div className="topbar-left"><button className="mobile-menu" onClick={() => setMobileNav(true)}><Menu size={20} /></button><div><p className="breadcrumb">Workspace / {title}</p><h2>{title}</h2></div></div><div className="topbar-actions"><span className="today-label">{new Date().toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</span><div className="profile">{workspace?.email?.slice(0, 1).toUpperCase() || "G"}</div></div></header><div className="content-scroll"><div className="content-wrap">{error && <div className="error-banner" role="alert">{error}</div>}{content}</div></div></main></div>;
}

function Onboarding({ form, setForm, onSubmit, busy, error }: { form: typeof emptyWorkspace; setForm: (value: typeof emptyWorkspace) => void; onSubmit: (event: FormEvent) => void; busy: boolean; error: string }) {
  const [manual, setManual] = useState(false);
  const [prompt, setPrompt] = useState("");
  const usePrompt = (event: FormEvent) => {
    event.preventDefault();
    if (!prompt.trim()) return;
    setForm({ ...form, company_name: "My workspace", company_description: prompt.trim(), product_name: "My product", product_description: prompt.trim(), email: form.email || "user@example.com" });
    setManual(true);
  };
  return <section className="onboarding-card chat-onboarding"><h1>What are you building?</h1><p>Define your ideal target profile to automatically surface qualified leads, enrich company profiles, and generate targeted outreach.</p><form className="first-chat" onSubmit={usePrompt}><textarea autoFocus value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Describe your product, customer, and market..." /><button className="primary-button icon-submit" aria-label="Start with this idea" disabled={!prompt.trim() || busy}>{busy ? <Loader2 className="spin" size={17} /> : <Send size={17} />}</button></form><div className="suggestion-row"><button type="button" onClick={() => setPrompt("We sell workflow software to B2B SaaS companies raising Series A.")}>B2B SaaS · Series A</button><button type="button" onClick={() => setPrompt("We help direct-to-consumer ecommerce brands improve support operations.")}>E-commerce · DTC brands</button></div><button type="button" className="manual-toggle" onClick={() => setManual(!manual)}>{manual ? "Hide manual setup" : "Add workspace details manually"} <ChevronRight size={14} /></button>{manual && <form onSubmit={onSubmit} className="form-grid manual-form"><label>Company name<input required value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} placeholder="Acme Support" /></label><label>Email<input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="founder@acme.com" /></label><label className="full">Company description<textarea required value={form.company_description} onChange={(e) => setForm({ ...form, company_description: e.target.value })} placeholder="What does your company do?" /></label><label>Product name<input required value={form.product_name} onChange={(e) => setForm({ ...form, product_name: e.target.value })} placeholder="Product name" /></label><label>Product description<textarea required value={form.product_description} onChange={(e) => setForm({ ...form, product_description: e.target.value })} placeholder="What does the product solve?" /></label><div className="full"><button className="primary-button" disabled={busy}>{busy ? <Loader2 className="spin" size={16} /> : <ChevronRight size={17} />} Create workspace</button></div></form>}{error && <p className="error-text">{error}</p>}</section>;
}

function Overview({ workspace, accounts, qualified, analytics, tasks, onCompleteTask, onChat, onDiscovery, onAccounts }: { workspace: Workspace; accounts: Account[]; qualified: Account[]; analytics: Record<string, any>; tasks: Task[]; onCompleteTask: (id: string) => void; onChat: () => void; onDiscovery: () => void; onAccounts: () => void }) { return <div className="page-stack"><div className="welcome-row"><div><p className="eyebrow">Good morning</p><h1>{workspace.company_name}</h1><p className="subheading">Your workspace is ready to find the next best accounts.</p></div><button className="primary-button" onClick={onChat}><MessageSquare size={16} /> Ask the Chief of Staff</button></div><div className="metric-grid"><Metric label="Companies found" value={analytics.companies_found ?? accounts.length} icon={<Building2 size={18} />} /><Metric label="Qualified accounts" value={qualified.length} icon={<CheckCircle2 size={18} />} /><Metric label="Email drafts" value={analytics.email_drafts ?? 0} icon={<Mail size={18} />} /><Metric label="Searches" value={analytics.total_searches ?? 0} icon={<Search size={18} />} /></div><TodayTasks tasks={tasks} onComplete={onCompleteTask} /><div className="hero-panel"><div><span className="eyebrow light">Research workflow</span><h2>Find companies that can buy your product.</h2><p>Run discovery from your product context. The system maps the ICP, searches industries, verifies websites, and scores fit.</p><button className="light-button" onClick={onDiscovery}>Start discovery <ChevronRight size={15} /></button></div><div className="hero-orbit"><div className="orbit-center">O</div><span>ICP</span><span>Research</span><span>Fit</span></div></div><div className="section-heading"><div><p className="eyebrow">Latest accounts</p><h2>Recommended prospects</h2></div><button className="text-button" onClick={onAccounts}>View all <ChevronRight size={14} /></button></div><div className="card-grid">{accounts.slice(0, 3).map((account) => <AccountCard key={account.id} account={account} />)}{accounts.length === 0 && <EmptyState title="No accounts yet" text="Start a discovery run to populate your account list." onClick={onDiscovery} />}</div></div>; }
function Metric({ label, value, icon }: { label: string; value: number; icon: ReactNode }) { return <div className="metric-card"><div className="metric-icon">{icon}</div><span>{label}</span><strong>{value.toLocaleString()}</strong><small>Live workspace data</small></div>; }

function TodayTasks({ tasks, onComplete }: { tasks: Task[]; onComplete: (id: string) => void }) { return <section className="tasks-card"><div className="section-heading"><div><p className="eyebrow">Today</p><h2>Tasks</h2></div><span className="result-count">{tasks.length} open</span></div>{tasks.length ? <div className="task-list">{tasks.map((task) => <div className="task-row" key={task.id}><div className="task-check"><CheckCircle2 size={17} /></div><div className="task-main"><strong>{task.title}</strong><p>{task.description || "Follow up on this lead."}</p><div className="task-meta"><span>{task.priority} priority</span>{task.lead_id && <span>Lead task</span>}</div></div><button className="secondary-button" onClick={() => onComplete(task.id)}>Complete</button></div>)}</div> : <p className="muted-copy">No open tasks for today.</p>}</section>; }

function ChatView({ workspace, messages, conversations, activeConversationId, onSelectConversation, onDeleteConversation, onNewConversation, input, setInput, onSubmit, onDiscovery, busy }: { workspace: Workspace; messages: Message[]; conversations: Conversation[]; activeConversationId: string; onSelectConversation: (id: string) => void; onDeleteConversation: (id: string) => void; onNewConversation: () => void; input: string; setInput: (value: string) => void; onSubmit: (event: FormEvent) => void; onDiscovery: () => void; busy: boolean }) { return <div className="chat-layout"><div className="chat-intro"><p className="eyebrow"><Sparkles size={15} /> Chief of Staff</p><h1>What should we work on?</h1><p className="subheading">Ask about your ICP, target accounts, research, or outreach. I will use {workspace.company_name}&apos;s workspace context.</p><div className="prompt-row"><button onClick={() => setInput("Which industries should we target first?")}>Which industries should we target first?</button><button onClick={() => setInput("Start finding companies that need our product")}>Find companies for my product</button></div></div><div className="chat-workspace"><aside className="chat-history"><div className="chat-history-heading"><div><span className="eyebrow">Workspace chats</span><strong>Conversation history</strong></div><button type="button" className="chat-history-new" onClick={onNewConversation} aria-label="Start a new conversation"><Plus size={14} /></button></div>{conversations.length === 0 ? <p className="chat-history-empty">Start a new conversation to begin.</p> : <div className="chat-history-list">{conversations.map((conversation) => <div className={`chat-history-item ${conversation.id === activeConversationId ? "active" : ""}`} key={conversation.id}><button type="button" className="chat-history-select" onClick={() => onSelectConversation(conversation.id)}><span className="chat-history-dot" /><span><strong>{conversation.title}</strong><small>{conversation.messages.length ? `${conversation.messages.length} messages` : "Empty conversation"}</small></span></button><button type="button" className="chat-history-delete" onClick={() => onDeleteConversation(conversation.id)} aria-label={`Delete ${conversation.title}`} title="Delete conversation"><Trash2 size={14} /></button></div>)}</div>}</aside><div className="chat-panel"><div className="messages">{messages.length === 0 && <div className="empty-chat"><div className="assistant-mark"><Sparkles size={20} /></div><p>Start with a question about your product or ask me to find companies.</p></div>}{messages.map((message, index) => <div className={`message-row ${message.role}`} key={`${message.role}-${index}`}><div className="message-avatar">{message.role === "assistant" ? <Sparkles size={14} /> : "You"}</div><div className="message-bubble">{message.content}</div></div>)}{busy && <div className="message-row assistant"><div className="message-avatar"><Sparkles size={14} /></div><div className="message-bubble thinking"><span /><span /><span /></div></div>}</div><form className="chat-composer" onSubmit={onSubmit}><input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask anything about your outreach strategy..." /><button disabled={busy || !input.trim()} aria-label="Send message"><Send size={17} /></button></form></div></div><button className="secondary-button discovery-inline" onClick={onDiscovery}><Search size={16} /> Run company discovery</button></div>; }

function DiscoveryView({ job, accounts, onStart, busy }: { job: Record<string, any> | null; accounts: Account[]; onStart: () => void; busy: boolean }) { const running = job?.status === "running" || job?.status === "queued"; return <div className="page-stack"><div className="welcome-row"><div><p className="eyebrow">Automated research</p><h1>Company discovery</h1><p className="subheading">The pipeline finds, verifies, and scores companies against your ICP.</p></div><button className="primary-button" onClick={onStart} disabled={busy}><Search size={16} /> {running ? "Discovery running" : "Start discovery"}</button></div><div className="discovery-status"><div className={`status-icon ${job?.status === "completed" ? "done" : ""}`}>{job?.status === "completed" ? <CheckCircle2 /> : running ? <Loader2 className="spin" /> : <Search />}</div><div className="flex-1"><h3>{job ? `Discovery ${job.status}` : "Ready when you are"}</h3><p>{job?.status === "completed" ? `${job.companies_found || accounts.length} companies found and scored.` : running ? "Searching industries, researching official websites, and evaluating fit..." : "Start a run to discover real target accounts."}</p></div>{job?.completed_at && <small>{new Date(job.completed_at).toLocaleTimeString()}</small>}</div><div className="section-heading"><div><p className="eyebrow">Results</p><h2>Discovered accounts</h2></div><span className="result-count">{accounts.length} accounts</span></div><div className="card-grid">{accounts.map((account) => <AccountCard key={account.id} account={account} />)}{!accounts.length && <EmptyState title="Results will appear here" text="Discovery results are shown as soon as the background job completes." />}</div></div>; }

function AccountsView({ accounts, onEmail }: { accounts: Account[]; onEmail: (account: Account) => void }) { return <div className="page-stack"><div className="welcome-row"><div><p className="eyebrow">Account intelligence</p><h1>Accounts</h1><p className="subheading">Every company found by your automated discovery pipeline.</p></div><span className="result-count">{accounts.length} total</span></div><div className="card-grid">{accounts.map((account) => <AccountCard key={account.id} account={account} onEmail={() => onEmail(account)} />)}{!accounts.length && <EmptyState title="No accounts yet" text="Run discovery from the chat or Discovery page." />}</div></div>; }

function LeadsView({ leads, onStatus, onDraft, onAnalyze, onTimeline, onSchedule, onReschedule, onCancelMeeting, calendarConnected, intelligence, timelines, analyzingLead }: { leads: Lead[]; onStatus: (id: string, status: string) => void; onDraft: (id: string) => void; onAnalyze: (id: string) => void; onTimeline: (id: string) => Promise<Timeline | undefined>; onSchedule: (id: string, payload: MeetingPayload) => Promise<{ status: string; event_id: string; html_link?: string; meet_link?: string }>; onReschedule: (id: string, eventId: string, payload: MeetingPayload) => Promise<{ status: string; event_id: string; html_link?: string; meet_link?: string }>; onCancelMeeting: (id: string, eventId: string) => Promise<{ status: string; event_id: string }>; calendarConnected: boolean; intelligence: Record<string, LeadIntelligence>; timelines: Record<string, Timeline>; analyzingLead: string | null }) {
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [meetingLeadId, setMeetingLeadId] = useState<string | null>(null);
  const [meetingForm, setMeetingForm] = useState({ title: "", description: "", start_at: "", end_at: "", attendee: "" });
  const [meetingBusy, setMeetingBusy] = useState(false);
  const [meetingLink, setMeetingLink] = useState("");
  const [meetingEvent, setMeetingEvent] = useState<MeetingEvent | null>(null);
  const [meetingEditing, setMeetingEditing] = useState(false);
  const selected = selectedLeadId ? intelligence[selectedLeadId] : undefined;
  const timeline = selectedLeadId ? timelines[selectedLeadId] : undefined;
  const selectedMeetingLead = meetingLeadId ? leads.find((lead) => lead.id === meetingLeadId) : undefined;
  const submitMeeting = async (event: FormEvent) => {
    event.preventDefault();
    if (!meetingLeadId || !meetingForm.start_at || !meetingForm.end_at) return;
    setMeetingBusy(true); setMeetingLink("");
    try {
      const payload = { title: meetingForm.title || undefined, description: meetingForm.description, start_at: new Date(meetingForm.start_at).toISOString(), end_at: new Date(meetingForm.end_at).toISOString(), attendees: meetingForm.attendee ? [meetingForm.attendee] : [] };
      const result = meetingEditing && meetingEvent ? await onReschedule(meetingLeadId, meetingEvent.event_id, payload) : await onSchedule(meetingLeadId, payload);
      setMeetingEvent({ event_id: result.event_id, title: meetingForm.title, description: meetingForm.description, start_at: payload.start_at, end_at: payload.end_at, attendees: payload.attendees, html_link: result.html_link, meet_link: result.meet_link });
      setMeetingLink(result.meet_link || result.html_link || "");
      setMeetingEditing(false);
    } catch { /* The page-level error toast explains the failure. */ } finally { setMeetingBusy(false); }
  };
  const openMeeting = async (lead: Lead) => { setMeetingLeadId(lead.id); setMeetingLink(""); setMeetingEditing(false); setMeetingEvent(null); setMeetingForm({ title: `Meeting with ${lead.company?.name || "lead"}`, description: `Outreach meeting for ${lead.company?.name || "this lead"}.`, start_at: "", end_at: "", attendee: lead.contact_email || "" }); try { const loaded = await onTimeline(lead.id); const event = loaded?.events.find((item) => (item.event_type === "meeting_scheduled" || item.event_type === "meeting_rescheduled") && item.metadata?.event_id); if (event?.metadata?.event_id) { const metadata = event.metadata; const start = metadata.start_at ? new Date(metadata.start_at).toISOString().slice(0, 16) : ""; const end = metadata.end_at ? new Date(metadata.end_at).toISOString().slice(0, 16) : ""; setMeetingEvent({ event_id: String(metadata.event_id), title: String(metadata.title || `Meeting with ${lead.company?.name || "lead"}`), description: String(metadata.description || ""), start_at: String(metadata.start_at || ""), end_at: String(metadata.end_at || ""), attendees: Array.isArray(metadata.attendees) ? metadata.attendees : [], html_link: metadata.html_link, meet_link: metadata.meet_link }); setMeetingForm({ title: String(metadata.title || `Meeting with ${lead.company?.name || "lead"}`), description: String(metadata.description || ""), start_at: start, end_at: end, attendee: Array.isArray(metadata.attendees) ? String(metadata.attendees[0] || "") : "" }); } } catch { /* The meeting form remains available for a new event. */ } };
  const cancelMeeting = async () => { if (!meetingLeadId || !meetingEvent || !window.confirm("Cancel this Google Calendar meeting?")) return; setMeetingBusy(true); try { await onCancelMeeting(meetingLeadId, meetingEvent.event_id); setMeetingEvent({ ...meetingEvent, cancelled: true }); setMeetingEditing(false); } catch { /* The page-level error toast explains the failure. */ } finally { setMeetingBusy(false); } };
  return <div className="page-stack"><div><p className="eyebrow">Pipeline intelligence</p><h1>Leads</h1><p className="subheading">Move qualified accounts through your outreach workflow and inspect next actions.</p></div><div className="table-card"><div className="table-scroll"><table><thead><tr><th>Company</th><th>Industry</th><th>Fit</th><th>Status</th><th>Actions</th></tr></thead><tbody>{leads.map((lead) => <tr key={lead.id}><td><strong>{lead.company?.name || "Unknown"}</strong><small>{lead.company?.domain}</small></td><td>{lead.company?.industry || "—"}</td><td><span className={`score-badge ${scoreColor(lead.company?.match_score)}`}>{lead.company?.match_score ?? 0}%</span></td><td><select value={lead.status} onChange={(e) => onStatus(lead.id, e.target.value)}><option>New</option><option>Approved</option><option>Draft Ready</option><option>Contacted</option><option>Meeting</option><option>Closed</option></select></td><td><div className="lead-actions"><button className="text-button" onClick={() => { setSelectedLeadId(lead.id); onAnalyze(lead.id); }} disabled={analyzingLead === lead.id}>{analyzingLead === lead.id ? <Loader2 className="spin" size={14} /> : <Search size={14} />} {analyzingLead === lead.id ? "Analyzing" : "Analyze lead"}</button><button className="text-button" onClick={() => onDraft(lead.id)}><Mail size={14} /> Draft email</button><button className="text-button" onClick={() => void openMeeting(lead)} disabled={!calendarConnected}><CalendarDays size={14} /> Schedule meeting</button><button className="text-button" onClick={() => { setSelectedLeadId(lead.id); void onTimeline(lead.id); }}>Timeline</button></div></td></tr>)}</tbody></table></div>{!leads.length && <EmptyState title="No leads yet" text="Discovered accounts become leads automatically." />}</div>{meetingLeadId && <section className="settings-card meeting-card"><div className="section-heading"><div><p className="eyebrow">Google Calendar</p><h2>{meetingEvent?.cancelled ? "Cancelled meeting" : meetingEditing ? "Reschedule meeting" : meetingEvent ? "Scheduled meeting" : `Schedule ${selectedMeetingLead?.company?.name || "meeting"}`}</h2></div><button className="secondary-button" type="button" onClick={() => setMeetingLeadId(null)}>Close</button></div>{meetingEvent && <div className={`calendar-preview ${meetingEvent.cancelled ? "cancelled" : ""}`}><div className="calendar-date"><strong>{meetingEvent.start_at ? new Date(meetingEvent.start_at).toLocaleString(undefined, { month: "short" }).toUpperCase() : "CAL"}</strong><b>{meetingEvent.start_at ? new Date(meetingEvent.start_at).getDate() : "—"}</b></div><div className="calendar-details"><strong>{meetingEvent.title}</strong><span>{meetingEvent.start_at ? new Date(meetingEvent.start_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "Time not set"}</span>{meetingEvent.attendees[0] && <small>Guest: {meetingEvent.attendees[0]}</small>}{meetingEvent.cancelled && <em>Cancelled in Google Calendar</em>}</div>{!meetingEvent.cancelled && <div className="calendar-actions"><button className="secondary-button" type="button" onClick={() => setMeetingEditing(true)}><RefreshCw size={14} /> Reschedule</button><button className="danger-button" type="button" onClick={() => void cancelMeeting()} disabled={meetingBusy}><X size={14} /> Cancel</button>{meetingLink && <a className="text-button" href={meetingLink} target="_blank" rel="noreferrer">Open in Google Calendar</a>}</div>}</div>}{!calendarConnected ? <p className="muted-copy">Connect Google Calendar from Settings first.</p> : (!meetingEvent || meetingEditing) && <form className="form-grid" onSubmit={submitMeeting}><label>Title<input required value={meetingForm.title} onChange={(e) => setMeetingForm({ ...meetingForm, title: e.target.value })} /></label><label>Guest email<input type="email" value={meetingForm.attendee} onChange={(e) => setMeetingForm({ ...meetingForm, attendee: e.target.value })} placeholder="guest@example.com" /></label><label>Starts<input required type="datetime-local" value={meetingForm.start_at} onChange={(e) => setMeetingForm({ ...meetingForm, start_at: e.target.value })} /></label><label>Ends<input required type="datetime-local" value={meetingForm.end_at} onChange={(e) => setMeetingForm({ ...meetingForm, end_at: e.target.value })} /></label><label className="full">Description<textarea value={meetingForm.description} onChange={(e) => setMeetingForm({ ...meetingForm, description: e.target.value })} /></label><div className="full"><button className="primary-button" disabled={meetingBusy}>{meetingBusy ? <Loader2 className="spin" size={16} /> : <CalendarDays size={16} />} {meetingBusy ? (meetingEditing ? "Rescheduling meeting" : "Creating meeting") : (meetingEditing ? "Save new time" : "Create Calendar event")}</button>{meetingEditing && <button className="secondary-button" type="button" onClick={() => setMeetingEditing(false)}>Keep current time</button>}</div></form>}</section>}{selected && <section className="intelligence-panel"><div className="section-heading"><div><p className="eyebrow">Lead intelligence</p><h2>{leads.find((lead) => lead.id === selected.lead_id)?.company?.name || "Selected lead"}</h2></div><StatusPill>{selected.analysis.actual_stage || selected.current_stage}</StatusPill></div><div className="intelligence-grid"><div><span>Stage confidence</span><strong>{selected.analysis.stage_confidence}%</strong></div><div><span>Buyer intent</span><strong>{selected.analysis.buyer_intent || "Unknown"}</strong></div><div><span>Recommended action</span><strong>{selected.analysis.next_action.title}</strong></div></div><div className="action-card"><strong>{selected.analysis.next_action.title}</strong><p>{selected.analysis.next_action.description}</p><StatusPill>{selected.analysis.next_action.priority} priority</StatusPill></div>{selected.analysis.competitor_signals.length > 0 && <div className="signal-section"><h3>Competitor signals</h3><div className="signal-list">{selected.analysis.competitor_signals.map((signal, index) => <div className="signal-row" key={`${signal.name}-${index}`}><div><strong>{signal.name}</strong><p>{signal.evidence}</p></div><span>{signal.confidence}%</span></div>)}</div></div>}{selected.analysis.blockers.length > 0 && <div className="signal-section"><h3>Blockers</h3><p className="muted-copy">{selected.analysis.blockers.join(" · ")}</p></div>}</section>}{timeline && <section className="timeline-panel"><div className="section-heading"><div><p className="eyebrow">Activity</p><h2>Lead timeline</h2></div></div>{timeline.stage_history.length || timeline.events.length ? <div className="timeline-list">{timeline.stage_history.map((item) => <div className="timeline-row" key={`stage-${item.id}`}><span className="timeline-dot" /><div><strong>{item.old_stage || "New"} → {item.new_stage}</strong><p>{item.reason || "Stage updated"}</p><small>{new Date(item.created_at).toLocaleString()}</small></div></div>)}{timeline.events.map((item) => <div className="timeline-row" key={`event-${item.id}`}><span className="timeline-dot" /><div><strong>{item.event_type.replaceAll("_", " ")}</strong><p>{item.content}</p><small>{item.occurred_at ? new Date(item.occurred_at).toLocaleString() : ""}</small></div></div>)}</div> : <p className="muted-copy">No timeline events yet.</p>}</section>}</div>;
}

function useActiveAgentTab() { const [tab, setTab] = useState<"debrief" | "commercial">("debrief"); useEffect(() => { const update = () => setTab(document.body.dataset.agentTab === "commercial" ? "commercial" : "debrief"); update(); window.addEventListener("agent-tab-change", update); return () => window.removeEventListener("agent-tab-change", update); }, []); return tab; }

function AgentsView({ leads, busy, result, onAnalyze, onApply, onClear }: { leads: Lead[]; busy: boolean; result: { leadId: string; notes: string; analysis: DebriefAnalysis } | null; onAnalyze: (leadId: string, notes: string) => void; onApply: () => void; onClear: () => void }) {
  const [leadId, setLeadId] = useState(leads[0]?.id || "");
  const [notes, setNotes] = useState("");
  useEffect(() => { if (!leadId && leads[0]?.id) setLeadId(leads[0].id); }, [leadId, leads]);
  const selectedLead = leads.find((lead) => lead.id === (result?.leadId || leadId));
  return <div className="page-stack agents-page"><div><p className="eyebrow"><Bot size={15} /> Workspace agents</p><h1>Small agents, useful actions.</h1><p className="subheading">Turn messy sales work into clear, reviewable updates.</p></div><div className="agent-grid"><section className="agent-card agent-card-primary"><div className="agent-card-heading"><div className="agent-icon"><ClipboardCheck size={21} /></div><div><span className="agent-status">Ready</span><h2>Post-call Debrief Agent</h2><p>Paste a call note and get a clean summary, stage suggestion, objections, stakeholders, contradictions, and next task.</p></div></div>{!leads.length ? <EmptyState title="Discover a lead first" text="This agent attaches debriefs to a specific lead." /> : <><label className="agent-label">Lead<select value={leadId} onChange={(event) => setLeadId(event.target.value)}>{leads.map((lead) => <option key={lead.id} value={lead.id}>{lead.company?.name || "Unknown lead"}</option>)}</select></label><label className="agent-label">Call notes or transcript<textarea className="agent-textarea" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Paste what happened on the call..." /></label><div className="agent-footer"><span><FileText size={14} /> Text notes for now</span><button className="primary-button" disabled={busy || notes.trim().length < 10} onClick={() => onAnalyze(leadId, notes)}>{busy ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />} Analyze notes</button></div></>}{result && <div className="debrief-result"><div className="result-heading"><div><span className="agent-status">Review before applying</span><h3>{selectedLead?.company?.name || "Lead"}</h3></div><button className="text-button" onClick={onClear}>Clear</button></div><p className="debrief-summary">{result.analysis.summary}</p><div className="debrief-grid"><div><span>Proposed stage</span><strong>{result.analysis.proposed_stage} ({result.analysis.stage_confidence}%)</strong></div><div><span>Next action</span><strong>{result.analysis.next_action.title}</strong></div><div><span>Stakeholders</span><strong>{result.analysis.stakeholders.length || "None found"}</strong></div><div><span>Objections</span><strong>{result.analysis.objections.length || "None found"}</strong></div></div>{result.analysis.contradictions.length > 0 && <div className="debrief-warning"><AlertTriangle size={16} /><div><strong>Contradictions to review</strong>{result.analysis.contradictions.map((item, index) => <p key={index}>{item.evidence}: “{item.previous}” → “{item.new}”</p>)}</div></div>}<div className="agent-footer"><span>Apply will update the lead, timeline, and task list.</span><button className="primary-button" onClick={onApply} disabled={busy}><CheckCircle2 size={16} /> Apply updates</button></div></div>}</section><section className="agent-card agent-card-muted"><div className="agent-card-heading"><div className="agent-icon muted"><Calculator size={21} /></div><div><span className="agent-status muted">Coming soon</span><h2>Commercial Fit &amp; Budget Agent</h2><p>Estimate affordability, contract value, margin, and break-even using your product pricing and lead signals.</p></div></div><div className="agent-placeholder"><span>Next workspace</span><p>This space is reserved for pricing scenarios and budget analysis.</p></div></section></div></div>;
}

function CommercialFitPanel({ leads, busy, result, onAnalyze, onClear }: { leads: Lead[]; busy: boolean; result: CommercialAnalysis | null; onAnalyze: (leadId: string, input: CommercialInput) => void; onClear: () => void }) {
  const activeTab = useActiveAgentTab();
  const [leadId, setLeadId] = useState(leads[0]?.id || "");
  const [form, setForm] = useState<CommercialInput>({ monthly_price: 2000, monthly_delivery_cost: 600, contract_months: 12, discount_percent: 0, acquisition_cost: 3000 });
  useEffect(() => { if (!leadId && leads[0]?.id) setLeadId(leads[0].id); }, [leadId, leads]);
  const setNumber = (key: keyof CommercialInput, value: string) => setForm((current) => ({ ...current, [key]: Number(value) || 0 }));
  const money = (value: number) => new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
  return <section className="commercial-panel"><div className="commercial-heading"><div><p className="eyebrow"><Calculator size={15} /> Commercial planning</p><h2>Commercial Fit &amp; Budget Agent</h2><p>Run a quick pricing scenario before you spend time on a lead.</p></div>{result && <button className="text-button" onClick={onClear}>Clear result</button>}</div>{!leads.length ? <EmptyState title="Discover a lead first" text="This agent estimates fit for a specific account." /> : <div className="commercial-layout"><div><label className="agent-label">Lead<select value={leadId} onChange={(event) => setLeadId(event.target.value)}>{leads.map((lead) => <option key={lead.id} value={lead.id}>{lead.company?.name || "Unknown lead"}</option>)}</select></label><div className="commercial-form-grid"><label className="agent-label">Monthly price<input type="number" min="0" value={form.monthly_price} onChange={(event) => setNumber("monthly_price", event.target.value)} /></label><label className="agent-label">Monthly delivery cost<input type="number" min="0" value={form.monthly_delivery_cost} onChange={(event) => setNumber("monthly_delivery_cost", event.target.value)} /></label><label className="agent-label">Contract months<input type="number" min="1" value={form.contract_months} onChange={(event) => setNumber("contract_months", event.target.value)} /></label><label className="agent-label">Discount %<input type="number" min="0" max="100" value={form.discount_percent} onChange={(event) => setNumber("discount_percent", event.target.value)} /></label><label className="agent-label">Acquisition cost<input type="number" min="0" value={form.acquisition_cost} onChange={(event) => setNumber("acquisition_cost", event.target.value)} /></label></div><button className="primary-button commercial-submit" disabled={busy || form.monthly_price <= 0} onClick={() => onAnalyze(leadId, form)}>{busy ? <Loader2 className="spin" size={16} /> : <Calculator size={16} />} Calculate commercial fit</button></div>{result && <div className="commercial-result"><div className="commercial-fit-pill">{result.commercial_fit} commercial fit</div><p className="commercial-recommendation">{result.recommendation}</p><div className="commercial-metrics"><div><span>Estimated budget</span><strong>{money(result.estimated_budget_low)}–{money(result.estimated_budget_high)}</strong><small>{result.budget_confidence}% confidence</small></div><div><span>Contract value</span><strong>{money(result.contract_value)}</strong><small>{result.assumptions.contract_months} month term</small></div><div><span>Gross margin</span><strong>{result.gross_margin_percent}%</strong><small>{money(result.monthly_gross_profit)}/month profit</small></div><div><span>Break-even</span><strong>{result.break_even_months ? `${result.break_even_months} months` : "Immediate"}</strong><small>{money(result.estimated_contract_profit)} estimated profit</small></div></div><p className="commercial-note">{result.budget_basis}</p></div>}</div>}</section>;
}

function DraftsView({ drafts, onApprove, onRegenerate, onDiscard }: { drafts: Draft[]; onApprove: (leadId: string) => void; onRegenerate: (leadId: string) => void; onDiscard: (draft: Draft) => void }) { return <div className="page-stack"><div><p className="eyebrow">Personalized outreach</p><h1>Email drafts</h1><p className="subheading">Review AI-generated messages before sending them. Drafts stay here until you approve, regenerate, or discard them.</p></div><div className="draft-grid">{drafts.map((draft) => <article className="draft-card" key={draft.id}><div className="draft-header"><div><span className="eyebrow">Recipient</span><h3>{draft.company?.name || "Target account"}</h3></div><StatusPill>{draft.status || "Draft"}</StatusPill></div><div className="subject"><span>Subject</span><strong>{draft.subject}</strong></div><div className="email-body">{draft.body}</div><div className="draft-actions"><button className="secondary-button" onClick={() => onRegenerate(draft.lead_id)}><RefreshCw size={15} /> Create new draft</button><button className="secondary-button" onClick={() => onDiscard(draft)}>Discard</button><button className="primary-button" onClick={() => onApprove(draft.lead_id)}><Send size={15} /> Approve draft</button></div></article>)}{!drafts.length && <EmptyState title="No drafts yet" text="Approve a lead and generate a personalized email." />}</div></div>; }

function AnalyticsView({ analytics, accounts, leads, drafts }: { analytics: Record<string, any>; accounts: Account[]; leads: Lead[]; drafts: Draft[] }) {
  const statuses = leads.reduce<Record<string, number>>((result, lead) => { result[lead.status] = (result[lead.status] || 0) + 1; return result; }, {});
  const qualified = accounts.filter((account) => (account.match_score || 0) >= 50).length;
  const verified = accounts.filter((account) => account.verified).length;
  const averageFit = accounts.length ? Math.round(accounts.reduce((sum, account) => sum + (account.match_score || 0), 0) / accounts.length) : 0;
  return <div className="page-stack"><div><p className="eyebrow">Workspace performance</p><h1>Analytics</h1><p className="subheading">Track discovery quality and movement from target account to outreach.</p></div><div className="metric-grid"><Metric label="Searches" value={analytics.total_searches ?? 0} icon={<Search size={18} />} /><Metric label="Accounts" value={analytics.companies_found ?? accounts.length} icon={<Building2 size={18} />} /><Metric label="Qualified" value={qualified} icon={<CheckCircle2 size={18} />} /><Metric label="Drafts" value={analytics.email_drafts ?? drafts.length} icon={<Mail size={18} />} /></div><div className="analytics-summary"><div><span>Verified accounts</span><strong>{verified} / {accounts.length}</strong></div><div><span>Average fit score</span><strong>{averageFit}%</strong></div><div><span>Lead conversion</span><strong>{accounts.length ? Math.round((leads.length / accounts.length) * 100) : 0}%</strong></div></div><div className="analytics-card"><div className="section-heading"><div><p className="eyebrow">Lead funnel</p><h2>Current pipeline</h2></div><span className="result-count">{leads.length} leads</span></div>{Object.keys(statuses).length ? Object.entries(statuses).map(([status, count]) => <div className="progress-row" key={status}><div><span>{status}</span><strong>{count}</strong></div><div className="progress-track"><div style={{ width: `${Math.max(8, (count / Math.max(leads.length, 1)) * 100)}%` }} /></div></div>) : <p className="muted-copy">Pipeline metrics will appear after discovery.</p>}</div></div>;
}

function SettingsView({ connected, calendarConnected, workspace, onConnectCalendar, onRefresh }: { connected: boolean; calendarConnected: boolean; workspace: Workspace; onConnectCalendar: () => void; onRefresh: () => void }) { return <div className="page-stack narrow"><div><p className="eyebrow">Workspace configuration</p><h1>Settings</h1><p className="subheading">Your workspace is connected to the FastAPI service.</p></div><div className="settings-card"><div className="setting-row"><div><strong>API connection</strong><p>FastAPI · PostgreSQL · Chroma</p></div><StatusPill>{connected ? "Connected" : "Offline"}</StatusPill></div><div className="setting-row"><div><strong>Google Calendar</strong><p>{calendarConnected ? "Connected — meetings can be scheduled from Leads" : "Connect your calendar to create meetings"}</p></div><button className={calendarConnected ? "secondary-button" : "primary-button"} onClick={onConnectCalendar}><CalendarDays size={15} /> {calendarConnected ? "Reconnect Google" : "Connect Google Calendar"}</button></div><div className="setting-row"><div><strong>Workspace email</strong><p>{workspace.email}</p></div></div><div className="setting-row"><div><strong>Workspace ID</strong><p className="mono-text">{workspace.id}</p></div><button className="secondary-button" onClick={onRefresh}><RefreshCw size={15} /> Sync</button></div></div></div>; }
function EmptyState({ title, text, onClick }: { title: string; text: string; onClick?: () => void }) { return <div className="empty-state"><div className="empty-icon"><PencilMark /></div><h3>{title}</h3><p>{text}</p>{onClick && <button className="text-button" onClick={onClick}>Get started <ChevronRight size={14} /></button>}</div>; }
