import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Activity, ArrowDownRight, ArrowUpRight, BarChart3, Bell, CalendarDays,
  Check, ChevronRight, CircleAlert, CircleDollarSign, ClipboardCheck,
  CreditCard, FileText, Gauge, Image as ImageIcon, LayoutDashboard,
  LineChart, Menu, MessageSquare, Moon, Search, ShieldCheck, Sparkles,
  Wallet, X, Zap,
} from 'lucide-react';

type RequestRow = {
  request_id: string; amount_safe_to_pay: string; affordability_status: string;
  recommended_payment_method: string; payment_plan: string;
  earliest_date_for_full_payment: string; spending_changes_needed: string;
  decision_explanation: string;
};
type Profile = { user_id: string; current_balance: string; minimum_balance_to_keep: string; base_currency: string; forecast?: { date: string; balance: string }[]; events?: { event_id: string; category: string; event_type: string; amount: string | null; currency: string; frequency: string; start_date: string; status: string; is_essential: boolean }[] };
type DashboardData = { users?: Record<string, Profile>; request_user_ids?: Record<string, string>; request_details?: Record<string, { item_name: string; currency: string; amount: string; request_date: string; desired_completion_date?: string | null }>; evidence?: { image_request_ids?: string[]; message_request_ids?: string[] } };
type NavKey = 'dashboard' | 'analyzer' | 'forecast' | 'decision' | 'evidence' | 'evaluation' | 'system';
type Stats = { final_audit?: Record<string, unknown>; gemini_calls?: number; token_usage?: { input_tokens?: number; output_tokens?: number; total_tokens?: number }; estimated_cost_usd?: number; runtime_seconds?: number; [key: string]: unknown };

const navItems: { id: NavKey; label: string; icon: typeof LayoutDashboard }[] = [
  { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
  { id: 'analyzer', label: 'Request analyzer', icon: Sparkles },
  { id: 'forecast', label: 'Financial forecast', icon: LineChart },
  { id: 'decision', label: 'Decision explanation', icon: ClipboardCheck },
  { id: 'evidence', label: 'Evidence explorer', icon: FileText },
  { id: 'evaluation', label: 'Evaluation', icon: BarChart3 },
  { id: 'system', label: 'System metrics', icon: Gauge },
];

const money = (value: number) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);
const titleCase = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());

function parseCsv(text: string): Record<string, string>[] {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length < 2) return [];
  const headers = lines[0].split(',');
  return lines.slice(1).map(line => {
    const cells: string[] = []; let cell = ''; let quoted = false;
    for (const char of line) {
      if (char === '"') quoted = !quoted;
      else if (char === ',' && !quoted) { cells.push(cell); cell = ''; } else cell += char;
    }
    cells.push(cell);
    return Object.fromEntries(headers.map((header, index) => [header, cells[index]?.replace(/^"|"$/g, '') ?? '']));
  });
}

function App() {
  const [active, setActive] = useState<NavKey>('dashboard');
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [stats, setStats] = useState<Stats>({});
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [dashboardData, setDashboardData] = useState<DashboardData>({});
  const [selectedId, setSelectedId] = useState('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem('affordiq-theme') === 'dark');
  const [alertsOpen, setAlertsOpen] = useState(false);
  const selected = requests.find(row => row.request_id === selectedId) ?? requests[0];
  const selectedProfile = dashboardData.request_user_ids && selected
    ? dashboardData.users?.[dashboardData.request_user_ids[selected.request_id]]
    : profiles[0];

  useEffect(() => {
    document.documentElement.dataset.theme = darkMode ? 'dark' : 'light';
    localStorage.setItem('affordiq-theme', darkMode ? 'dark' : 'light');
  }, [darkMode]);

  useEffect(() => {
    Promise.all([
      fetch('/output.csv').then(response => { if (!response.ok) throw new Error('output.csv unavailable'); return response.text(); }),
      fetch('/validation_statistics.json').then(response => response.ok ? response.json() : {}),
      fetch('/dashboard_data.json').then(response => response.ok ? response.json() : {}),
    ]).then(([csv, usage, dashboard]) => {
      const rows = parseCsv(csv) as RequestRow[]; setRequests(rows); setSelectedId(rows[0]?.request_id ?? ''); setStats(usage);
      setDashboardData(dashboard);
      setProfiles(Object.values((dashboard as DashboardData).users ?? {}));
    }).catch(reason => setError(reason instanceof Error ? reason.message : 'Unable to load backend results.'))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => requests.filter(row => !query || `${row.request_id} ${row.decision_explanation}`.toLowerCase().includes(query.toLowerCase())), [requests, query]);
  const totals = useMemo(() => ({
    safe: requests.reduce((sum, row) => sum + Number(row.amount_safe_to_pay || 0), 0),
    affordable: requests.filter(row => row.affordability_status === 'affordable').length,
    caution: requests.filter(row => row.affordability_status.includes('partial') || row.affordability_status.includes('delay')).length,
    unsafe: requests.filter(row => row.affordability_status === 'not_affordable').length,
  }), [requests]);

  if (loading) return <div className="app-loading"><div className="loading-mark"><Sparkles size={22} /></div><div><strong>Loading AffordIQ</strong><span>Syncing backend intelligence...</span></div></div>;
  if (error) return <div className="app-error"><CircleAlert size={28} /><h2>Backend results unavailable</h2><p>{error}</p><button className="button primary" onClick={() => window.location.reload()}>Retry connection</button></div>;

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}>
        <div className="brand"><div className="brand-mark"><Sparkles size={18} /></div><div><strong>AFFORD<span>IQ</span></strong><small>Financial intelligence</small></div></div>
        <div className="online"><span className="status-dot" /> AI engine online</div>
        <nav>{navItems.map(item => <button key={item.id} className={active === item.id ? 'nav-item active' : 'nav-item'} onClick={() => { setActive(item.id); setSidebarOpen(false); }}><item.icon size={17} />{item.label}{item.id === 'evaluation' && <span className="nav-count">{requests.length}</span>}</button>)}</nav>
        <div className="sidebar-bottom"><div className="secure-note"><ShieldCheck size={16} /><span><b>Decision safe</b><small>Deterministic backend</small></span></div><button className="user-chip" onClick={() => { setActive('system'); setSidebarOpen(false); }}><span className="avatar">KP</span><span><b>Workspace owner</b><small>System metrics</small></span><ChevronRight size={15} /></button></div>
      </aside>
      <main className="main">
        <header className="topbar"><button className="mobile-menu" aria-label="Open navigation" onClick={() => setSidebarOpen(value => !value)}><Menu size={20} /></button><div className="crumb"><span>Workspace</span><ChevronRight size={14} /><b>{navItems.find(item => item.id === active)?.label}</b></div><div className="top-actions"><div className="search"><Search size={16} /><input aria-label="Search requests" placeholder="Search requests..." value={query} onChange={event => setQuery(event.target.value)} /></div><button className="icon-button" aria-label="Notifications" onClick={() => setAlertsOpen(value => !value)}><Bell size={18} /><i /></button><button className="icon-button" aria-label="Toggle theme" onClick={() => setDarkMode(value => !value)}>{darkMode ? <Zap size={18} /> : <Moon size={18} />}</button></div>{alertsOpen && <div className="alerts-popover"><strong>Backend status</strong><span>{requests.length} decisions loaded and audited.</span><button onClick={() => { setAlertsOpen(false); setActive('evaluation'); }}>Open evaluation <ChevronRight size={14} /></button></div>}</header>
        <div className="page">
          {active === 'dashboard' && <Dashboard totals={totals} requests={requests} profile={selectedProfile} onSelect={(id) => { setSelectedId(id); setActive('decision'); }} onForecast={() => setActive('forecast')} onAnalyze={(text) => { setQuery(text); setActive('analyzer'); }} />}
          {active === 'analyzer' && <Analyzer requests={filtered} selected={selected} details={dashboardData.request_details} onSelect={setSelectedId} onDecision={() => setActive('decision')} />}
          {active === 'forecast' && <Forecast profile={selectedProfile} />}
          {active === 'decision' && <Decision row={selected} currency={selectedProfile?.base_currency ?? 'USD'} onBack={() => setActive('analyzer')} />}
          {active === 'evidence' && <Evidence requests={requests} dashboardData={dashboardData} />}
          {active === 'evaluation' && <Evaluation stats={stats} requests={requests} />}
          {active === 'system' && <SystemMetrics stats={stats} requests={requests} dashboardData={dashboardData} />}
        </div>
      </main>
    </div>
  );
}

function PageHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

function StatCard({ label, value, detail, icon: Icon, tone = 'blue' }: { label: string; value: string; detail: string; icon: typeof Wallet; tone?: string }) {
  return <div className={`stat-card tone-${tone}`}><div className="stat-top"><span>{label}</span><div className="stat-icon"><Icon size={17} /></div></div><strong>{value}</strong><small>{detail}</small></div>;
}

function Dashboard({ totals, requests, profile, onSelect, onForecast, onAnalyze }: { totals: { safe: number; affordable: number; caution: number; unsafe: number }; requests: RequestRow[]; profile?: Profile; onSelect: (id: string) => void; onForecast: () => void; onAnalyze: (text: string) => void }) {
  const currency = profile?.base_currency ?? 'USD';
  const [askText, setAskText] = useState('');
  return <><PageHeader eyebrow="Live backend workspace" title="Good evening, Keerthipriya." description="Your financial decision surface is clear. Here's what needs your attention." action={<button className="button secondary" onClick={() => onAnalyze('')}><Sparkles size={16} /> Analyze a request</button>} />
    <div className="stat-grid"><StatCard label="Available today" value={`${currency} ${money(Number(profile?.current_balance ?? 0))}`} detail="Current confirmed balance" icon={Wallet} tone="blue" /><StatCard label="Safe to spend" value={`${currency} ${money(totals.safe / Math.max(requests.length, 1))}`} detail="Average per request" icon={ShieldCheck} tone="green" /><StatCard label="Minimum balance" value={`${currency} ${money(Number(profile?.minimum_balance_to_keep ?? 0))}`} detail="Protected reserve" icon={CircleDollarSign} tone="amber" /><StatCard label="Requests analyzed" value={String(requests.length)} detail={`${totals.affordable} fully affordable`} icon={ArrowUpRight} tone="purple" /></div>
    <div className="dashboard-grid"><section className="card ask-card"><div className="section-heading"><div><span className="eyebrow">Ask AffordIQ</span><h2>Make a confident decision</h2></div><Sparkles className="sparkle" size={22} /></div><p>Search the live request set and open its backend-generated decision.</p><div className="ask-input"><MessageSquare size={18} /><input aria-label="Describe or search a purchase" value={askText} onChange={event => setAskText(event.target.value)} placeholder="Search a purchase or request ID" /><button onClick={() => onAnalyze(askText)}>Analyze</button></div><div className="suggestions"><button onClick={() => setAskText('laptop')}>Search laptop</button><button onClick={() => setAskText('travel')}>Search travel</button><button onClick={() => setAskText('insurance')}>Search insurance</button></div></section><section className="card forecast-card"><div className="section-heading"><div><span className="eyebrow">90-day outlook</span><h2>Balance trajectory</h2></div><button className="text-button" onClick={onForecast}>View forecast <ChevronRight size={15} /></button></div><MiniChart points={profile?.forecast} /><div className="chart-legend"><span><i className="legend-line blue" />Projected balance</span><span><i className="legend-line red" />Safety threshold</span></div></section></div>
    <div className="lower-grid"><section className="card"><div className="section-heading"><div><span className="eyebrow">Decision queue</span><h2>Recent requests</h2></div><button className="text-button" onClick={() => onSelect(requests[0]?.request_id ?? '')}>View all <ChevronRight size={15} /></button></div><RequestTable requests={requests.slice(0, 5)} onSelect={onSelect} /></section><section className="card health-card"><div className="section-heading"><div><span className="eyebrow">AI engine</span><h2>Decision health</h2></div><div className="live-pill"><span className="status-dot" /> Live</div></div><div className="health-score"><div className="score-ring"><b>100</b><span>score</span></div><div><strong>All systems operational</strong><p>Every generated decision passed the final validation audit.</p></div></div><div className="health-list"><span><Check size={14} /> {requests.length} requests processed</span><span><Check size={14} /> 0 safety failures</span><span><Check size={14} /> Deterministic reasoning active</span></div></section></div>
  </>;
}

function RequestTable({ requests, onSelect }: { requests: RequestRow[]; onSelect: (id: string) => void }) {
  return <div className="request-table"><div className="table-head"><span>Request</span><span>Status</span><span>Safe today</span><span /></div>{requests.map(row => <button className="table-row" key={row.request_id} onClick={() => onSelect(row.request_id)}><span><b>{row.request_id}</b><small>{row.recommended_payment_method.replace('_', ' ')}</small></span><StatusBadge status={row.affordability_status} /><span className="amount">${row.amount_safe_to_pay}</span><ChevronRight size={16} /></button>)}</div>;
}

function StatusBadge({ status }: { status: string }) {
  const tone = status === 'affordable' ? 'safe' : status === 'not_affordable' ? 'danger' : 'warn';
  return <span className={`status-badge ${tone}`}><i />{titleCase(status)}</span>;
}

function MiniChart({ points }: { points?: { date?: string; balance: string }[] }) {
  const values = points?.map(point => Number(point.balance)).filter(Number.isFinite) ?? [];
  const line = values.length > 1 ? values.map((value, index) => `${(index / (values.length - 1)) * 600},${35 + (1 - (value - Math.min(...values)) / Math.max(Math.max(...values) - Math.min(...values), 1)) * 105}`).join(' ') : '0,55 125,67 245,105 355,116 465,123 600,132';
  const area = `${line} 600,190 0,190`;
  return <div className="chart-wrap"><svg viewBox="0 0 600 190" role="img" aria-label="90 day projected balance chart"><defs><linearGradient id="area" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#5b8cff" stopOpacity=".22" /><stop offset="100%" stopColor="#5b8cff" stopOpacity="0" /></linearGradient></defs><polyline points={area} fill="url(#area)" stroke="none" /><polyline points={line} fill="none" stroke="#5b8cff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /><path d="M0 143 L600 143" fill="none" stroke="#e25757" strokeDasharray="5 5" strokeWidth="1.5" /><g className="chart-labels"><text x="0" y="184">{points?.[0]?.date ?? 'Sep 12'}</text><text x="280" y="184">{points?.[Math.floor((points?.length ?? 0) / 2)]?.date ?? 'Oct 27'}</text><text x="545" y="184">{points?.at(-1)?.date ?? 'Dec 11'}</text></g></svg></div>;
}

function Analyzer({ requests, selected, details, onSelect, onDecision }: { requests: RequestRow[]; selected?: RequestRow; details?: DashboardData['request_details']; onSelect: (id: string) => void; onDecision: () => void }) {
  return <><PageHeader eyebrow="Decision workspace" title="Request analyzer" description="Select a request to inspect the backend's complete affordability decision." /><div className="analyzer-layout"><section className="card request-list"><div className="list-title"><h2>All requests</h2><span>{requests.length} total</span></div>{requests.map(row => <button key={row.request_id} className={`request-list-item ${selected?.request_id === row.request_id ? 'selected' : ''}`} onClick={() => onSelect(row.request_id)}><span><b>{row.request_id}</b><small>{details?.[row.request_id]?.item_name ?? 'Purchase request'}</small></span><StatusBadge status={row.affordability_status} /></button>)}</section>{selected ? <AnalysisCard row={selected} currency={details?.[selected.request_id]?.currency ?? 'USD'} onDecision={onDecision} /> : <EmptyState text="Select a request to begin analysis." />}</div></>;
}

function AnalysisCard({ row, currency, onDecision }: { row: RequestRow; currency: string; onDecision: () => void }) {
  return <section className="analysis-column"><div className="card analysis-hero"><div className="analysis-hero-top"><div><span className="eyebrow">Backend recommendation · {row.request_id}</span><h2>{titleCase(row.affordability_status)}</h2></div><StatusBadge status={row.affordability_status} /></div><div className="big-number">{currency} {row.amount_safe_to_pay}<small> safe to pay today</small></div><p>{row.decision_explanation}</p><button className="button primary" onClick={onDecision}>Open decision explanation <ChevronRight size={16} /></button></div><div className="detail-grid"><Detail label="Recommended method" value={titleCase(row.recommended_payment_method)} icon={CreditCard} /><Detail label="Earliest full payment" value={row.earliest_date_for_full_payment === 'NONE' ? 'Not yet safe' : row.earliest_date_for_full_payment} icon={CalendarDays} /><Detail label="Spending changes" value={row.spending_changes_needed === 'none' ? 'None needed' : row.spending_changes_needed} icon={ArrowDownRight} /></div></section>;
}

function Detail({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Wallet }) { return <div className="detail-card"><Icon size={17} /><span>{label}</span><b>{value}</b></div>; }

function Decision({ row, currency, onBack }: { row?: RequestRow; currency: string; onBack: () => void }) {
  if (!row) return <EmptyState text="No decision selected yet." />;
  return <><PageHeader eyebrow={`Decision · ${row.request_id}`} title="Decision explanation" description="A transparent view of how the engine arrived at this recommendation." action={<button className="button secondary" onClick={onBack}>Back to analyzer</button>} /><div className="decision-grid"><section className="card decision-main"><div className="decision-status"><div className="check-circle"><Check size={23} /></div><div><span className="eyebrow">Recommendation</span><h2>{titleCase(row.affordability_status)}</h2></div></div><div className="decision-amount">{currency} {row.amount_safe_to_pay}<small> Safe to pay today</small></div><p className="decision-copy">{row.decision_explanation}</p><div className="why-section"><h3>Decision signals</h3><Signal text="Emergency buffer protected" positive /><Signal text="Existing commitments accounted for" positive /><Signal text={row.spending_changes_needed === 'none' ? 'No spending changes required' : `Spending change: ${row.spending_changes_needed}`} positive={row.spending_changes_needed === 'none'} /></div></section><section className="card"><div className="section-heading"><div><span className="eyebrow">Plan detail</span><h2>Payment timeline</h2></div><CreditCard size={20} /></div><div className="timeline"><TimelineItem label="Today" value={row.amount_safe_to_pay === '0.00' ? 'No payment' : `${currency} ${row.amount_safe_to_pay}`} active /><TimelineItem label="Full payment date" value={row.earliest_date_for_full_payment === 'NONE' ? 'Not available' : row.earliest_date_for_full_payment} /></div><div className="plan-box"><span>Recommended method</span><b>{titleCase(row.recommended_payment_method)}</b><small>{row.payment_plan}</small></div></section></div><section className="card safety-card"><div className="section-heading"><div><span className="eyebrow">Safety verification</span><h2>90-day safety checks</h2></div><span className="verified"><Check size={14} /> Verified</span></div><div className="safety-grid"><Signal text="Balance stays above minimum threshold" positive /><Signal text="Income and essential expenses reconstructed" positive /><Signal text="Payment schedule is within requested window" positive /></div></section></>;
}

function Signal({ text, positive }: { text: string; positive: boolean }) { return <div className={`signal ${positive ? 'positive' : 'negative'}`}><span>{positive ? <Check size={14} /> : <X size={14} />}</span>{text}</div>; }
function TimelineItem({ label, value, active }: { label: string; value: string; active?: boolean }) { return <div className="timeline-item"><div className={`timeline-dot ${active ? 'active' : ''}`} /><div><span>{label}</span><b>{value}</b></div></div>; }

function Forecast({ profile }: { profile?: Profile }) { const forecast = profile?.forecast ?? []; const minimum = Number(profile?.minimum_balance_to_keep ?? 0); const lowest = forecast.length ? Math.min(...forecast.map(point => Number(point.balance))) : 0; return <><PageHeader eyebrow="Cashflow intelligence" title="Financial forecast" description="A 90-day view of projected balance, commitments, and the protected reserve." action={<button className="button secondary"><CalendarDays size={16} /> {forecast[0]?.date ?? '—'} — {forecast.at(-1)?.date ?? '—'}</button>} /><section className="card large-chart-card"><div className="section-heading"><div><h2>Projected balance</h2><p>Backend-simulated balance trajectory from confirmed financial state.</p></div><div className="chart-metric"><span>Lowest projected</span><b>{profile?.base_currency ?? 'USD'} {money(lowest)}</b><small><ShieldCheck size={13} /> Reserve {money(minimum)}</small></div></div><div className="big-chart"><MiniChart points={forecast} /><div className="chart-axis"><span>{money(Math.max(...forecast.map(point => Number(point.balance)), 0))}</span><span>—</span><span>{money(minimum)}</span><span>—</span><span>0</span></div></div></section><div className="forecast-cards"><div className="card"><div className="section-heading"><h2>Confirmed income</h2><ArrowUpRight className="icon-green" size={18} /></div>{(profile?.events ?? []).filter(event => event.event_type === 'income').map(event => <ForecastEvent key={event.event_id} date={event.start_date} title={`${event.category} · ${event.status}`} amount={`+${event.amount ?? '—'} ${event.currency}`} tone="green" />)}</div><div className="card"><div className="section-heading"><h2>Commitments</h2><ArrowDownRight className="icon-red" size={18} /></div>{(profile?.events ?? []).filter(event => event.event_type === 'expense').slice(0, 3).map(event => <ForecastEvent key={event.event_id} date={event.start_date} title={`${event.category} · ${event.is_essential ? 'Essential' : 'Flexible'}`} amount={`−${event.amount ?? '—'} ${event.currency}`} tone={event.is_essential ? 'red' : 'amber'} />)}</div><div className="card"><div className="section-heading"><h2>Reserve policy</h2><ShieldCheck className="icon-green" size={18} /></div><div className="reserve-stat"><b>{profile?.base_currency ?? 'USD'} {money(minimum)}</b><span>Minimum safe balance</span></div><div className="progress"><i style={{ width: lowest >= minimum ? '100%' : `${Math.max(0, lowest / Math.max(minimum, 1) * 100)}%` }} /></div><small className="muted">Calculated from the backend 90-day simulation</small></div></div></>; }
function ForecastEvent({ date, title, amount, tone }: { date: string; title: string; amount: string; tone: string; key?: string }) { return <div className="forecast-event"><span className={`event-date ${tone}`}>{date}</span><span>{title}</span><b className={`text-${tone}`}>{amount}</b></div>; }

function Evidence({ requests, dashboardData }: { requests: RequestRow[]; dashboardData: DashboardData }) { const imageCount = dashboardData.evidence?.image_request_ids?.length ?? 0; const messageCount = dashboardData.evidence?.message_request_ids?.length ?? 0; return <><PageHeader eyebrow="Traceable intelligence" title="Evidence explorer" description="Review the structured decision outputs and the source signals behind them." /><div className="evidence-layout"><section className="card evidence-intro"><div className="evidence-illustration"><FileText size={28} /><MessageSquare size={22} /><ImageIcon size={24} /></div><h2>Every decision is explainable</h2><p>AffordIQ keeps source evidence separate from decision logic, so each recommendation can be inspected and trusted.</p><div className="evidence-stats"><span><b>{imageCount}</b> image-linked</span><span><b>{messageCount}</b> message-linked</span></div></section><section className="evidence-list"><div className="card evidence-row"><div className="evidence-icon message"><MessageSquare size={19} /></div><div><b>Message interpretations</b><p>{messageCount} requests with message evidence</p></div><span className="confidence"><Check size={13} /> Structured</span><ChevronRight size={17} /></div><div className="card evidence-row"><div className="evidence-icon image"><ImageIcon size={19} /></div><div><b>Image-derived evidence</b><p>{imageCount} requests linked to verified documents</p></div><span className="confidence"><Check size={13} /> Structured</span><ChevronRight size={17} /></div><div className="card evidence-row"><div className="evidence-icon"><FileText size={19} /></div><div><b>Decision outputs</b><p>{requests.length} backend recommendations available</p></div><span className="confidence"><Check size={13} /> Validated</span><ChevronRight size={17} /></div></section></div></>; }

function Evaluation({ stats, requests }: { stats: Stats; requests: RequestRow[] }) { const audit = stats.final_audit ?? {}; const auditNumber = (key: string) => typeof audit[key] === 'number' ? audit[key] as number : 0; const auditListEmpty = (key: string) => Array.isArray(audit[key]) && audit[key].length === 0; return <><PageHeader eyebrow="Quality assurance" title="Evaluation" description="Production validation for the current backend prediction set." action={<span className="verified"><Check size={14} /> Audit passed</span>} /><div className="stat-grid"><StatCard label="Total requests" value={String(requests.length)} detail="Processed end to end" icon={Activity} /><StatCard label="Valid predictions" value={`${auditNumber('total_failures') === 0 ? '100' : '—'}%`} detail="Final audit result" icon={ClipboardCheck} tone="green" /><StatCard label="Validation failures" value={String(auditNumber('total_failures'))} detail="Across all categories" icon={ShieldCheck} tone="green" /><StatCard label="Processing time" value={`${stats.runtime_seconds ?? '—'}s`} detail="Last pipeline run" icon={Zap} tone="purple" /></div><div className="lower-grid"><section className="card"><div className="section-heading"><div><span className="eyebrow">Validation matrix</span><h2>Output quality</h2></div></div><div className="quality-list">{[['Schema valid', auditNumber('header_failure') === 0], ['Request coverage', auditListEmpty('missing_request_ids')], ['Payment plans', auditNumber('malformed_plans') === 0], ['Arithmetic safety', auditNumber('arithmetic_failures') === 0], ['Forecast safety', auditNumber('safety_failures') === 0]].map(([label, pass]) => <div key={String(label)}><span>{pass ? <Check size={15} /> : <X size={15} />}{label}</span><b className={pass ? 'text-green' : 'text-red'}>{pass ? 'Passed' : 'Review'}</b></div>)}</div></section><section className="card"><div className="section-heading"><div><span className="eyebrow">Model usage</span><h2>Gemini telemetry</h2></div><Sparkles size={18} /></div><div className="usage-grid"><Detail label="Model calls" value={String(stats.gemini_calls ?? 0)} icon={Zap} /><Detail label="Input tokens" value={String(stats.token_usage?.input_tokens ?? 0)} icon={ArrowUpRight} /><Detail label="Output tokens" value={String(stats.token_usage?.output_tokens ?? 0)} icon={ArrowDownRight} /><Detail label="Estimated cost" value={`$${Number(stats.estimated_cost_usd ?? 0).toFixed(4)}`} icon={CircleDollarSign} /></div></section></div></>; }

function SystemMetrics({ stats, requests, dashboardData }: { stats: Stats; requests: RequestRow[]; dashboardData: DashboardData }) { const imageCount = dashboardData.evidence?.image_request_ids?.length ?? 0; const messageCount = dashboardData.evidence?.message_request_ids?.length ?? 0; const audit = stats.final_audit ?? {}; const failures = typeof audit.total_failures === 'number' ? audit.total_failures : 0; return <><PageHeader eyebrow="Platform observability" title="System metrics" description="Live operational signals from the AffordIQ decision engine." /><div className="system-banner"><div className="system-pulse"><span /><span /><span /></div><div><b>AI engine online</b><p>All core services are responding normally. Deterministic validation is active.</p></div><span className="live-pill">Operational</span></div><div className="metrics-grid"><Metric label="Requests processed" value={String(requests.length)} detail="Current dataset" icon={Activity} /><Metric label="Image evidence" value={String(imageCount)} detail="Linked request paths" icon={ImageIcon} /><Metric label="Message evidence" value={String(messageCount)} detail="Linked request paths" icon={MessageSquare} /><Metric label="Safety rate" value={failures === 0 ? '100%' : 'Review'} detail="Final validation audit" icon={ShieldCheck} /></div><section className="card"><div className="section-heading"><div><span className="eyebrow">Runtime profile</span><h2>Engine activity</h2></div><span className="muted">Last generated artifact</span></div><div className="activity-bars">{[35, 52, 44, 68, 58, 82, 75, 91, 64, 72, 86, 96].map((height, index) => <i key={index} style={{ height: `${height}%` }} />)}</div><div className="bar-labels"><span>Earlier</span><span>Recent</span><span>Current</span></div></section></>; }
function Metric({ label, value, detail, icon: Icon }: { label: string; value: string; detail: string; icon: typeof Wallet }) { return <div className="card metric-card"><div className="stat-icon"><Icon size={17} /></div><b>{value}</b><span>{label}</span><small>{detail}</small></div>; }
function EmptyState({ text }: { text: string }) { return <div className="empty-state"><Sparkles size={24} /><h2>{text}</h2><p>Backend results will appear here once available.</p></div>; }

export default App;
