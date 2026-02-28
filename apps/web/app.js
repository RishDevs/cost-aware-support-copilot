/* ============================================================
   SupportCopilot — Frontend Application (app.js)
   Connects UI to FastAPI backend with full state management.
   Demo mode when API is unavailable.
   ============================================================ */

const API_BASE = (window.NEXT_PUBLIC_API_URL || 'http://localhost:8000') + '/api/v1';
const DEMO_MODE = false; // Set true to use simulated responses

// ── State ──────────────────────────────────────────────────────────────────

const state = {
    conversationId: null,
    history: [],
    debugData: null,
    isTyping: false,
    currentView: 'chat',
    apiOnline: false,
    totalCost: 0,
    totalMessages: 0,
    tierCounts: { cheap: 0, balanced: 0, premium: 0 },
};

// ── DOM References ─────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);

// ── API Client ─────────────────────────────────────────────────────────────

async function apiCall(endpoint, method = 'GET', body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(`${API_BASE}${endpoint}`, opts);
    if (!resp.ok) throw new Error(`API ${resp.status}: ${resp.statusText}`);
    return resp.json();
}

// ── Navigation ─────────────────────────────────────────────────────────────

function switchView(view) {
    state.currentView = view;
    $$('.view').forEach(v => v.classList.remove('active'));
    $$('.nav-item').forEach(n => n.classList.remove('active'));
    $(`view${capitalize(view)}`).classList.add('active');
    $(`nav${capitalize(view)}`).classList.add('active');

    if (view === 'analytics') loadAnalytics();
    if (view === 'knowledge') loadDocuments();
    if (view === 'evaluation') loadEvalQueries();
}

$$('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
});

// ── Health Check & Budget ──────────────────────────────────────────────────

async function checkHealth() {
    try {
        await apiCall('/health');
        state.apiOnline = true;
        $('apiStatus').querySelector('.status-dot').className = 'status-dot online';
        $('apiStatus').querySelector('span').textContent = 'API connected';
    } catch {
        state.apiOnline = false;
        $('apiStatus').querySelector('.status-dot').className = 'status-dot offline';
        $('apiStatus').querySelector('span').textContent = DEMO_MODE ? 'Demo Mode' : 'API offline';
    }
}

async function loadBudget() {
    try {
        const data = state.apiOnline ? await apiCall('/analytics/budget') : getDemoBudget();
        const pct = data.usage_pct;
        $('budgetValue').textContent = `$${data.spend_usd.toFixed(2)} / $${data.budget_usd}`;
        $('budgetFill').style.width = `${Math.min(pct, 100)}%`;
        $('budgetFill').className = 'budget-fill' + (data.emergency_mode ? ' emergency' : data.alert ? ' alert' : '');
        $('budgetMeta').textContent = data.emergency_mode ? '⚠️ Emergency cheap mode' : data.alert ? '⚠️ Budget alert' : `${pct.toFixed(1)}% used`;
        $('kpiSpend').textContent = `$${data.spend_usd.toFixed(2)}`;
    } catch { }
}

function getDemoBudget() {
    const spend = state.totalCost;
    return { spend_usd: spend, budget_usd: 50, usage_pct: spend / 50 * 100, alert: spend > 40, emergency_mode: spend > 47.5 };
}

// ── Chat ───────────────────────────────────────────────────────────────────

const chatInput = $('chatInput');
const sendBtn = $('sendBtn');
const messages = $('messages');

chatInput.addEventListener('input', () => {
    const len = chatInput.value.length;
    $('charCount').textContent = `${len} / 4096`;
    sendBtn.disabled = len === 0;

    // Auto-resize
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + 'px';
});

chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!sendBtn.disabled) sendMessage();
    }
});

sendBtn.addEventListener('click', sendMessage);

// Scenario chips
$$('.scenario-chip').forEach(chip => {
    chip.addEventListener('click', () => {
        chatInput.value = chip.dataset.query;
        chatInput.dispatchEvent(new Event('input'));
        sendMessage();
    });
});

// Clear chat
$('clearChat').addEventListener('click', () => {
    state.conversationId = null;
    state.history = [];
    messages.innerHTML = '';
    messages.appendChild(buildWelcome());
    updateInspector(null);
});

// Debug panel toggle
$('debugMode').addEventListener('change', e => {
    const panel = $('inspectorPanel');
    panel.style.display = e.target.checked ? 'flex' : 'none';
});

// SLA mode indicator
$('slaMode').addEventListener('change', e => {
    const sla = e.target.checked ? 'quality' : 'balanced';
    const dot = $('modelIndicator').querySelector('.tier-dot');
    dot.className = `tier-dot ${e.target.checked ? 'tier-premium' : 'tier-balanced'}`;
    $('modelIndicator').lastChild.textContent = ` SLA: ${capitalize(sla)}`;
});

async function sendMessage() {
    const query = chatInput.value.trim();
    if (!query || state.isTyping) return;

    // Clear input
    chatInput.value = '';
    chatInput.style.height = 'auto';
    sendBtn.disabled = true;
    $('charCount').textContent = '0 / 4096';

    // Hide welcome state
    const welcome = $('welcomeState');
    if (welcome) welcome.remove();
    if ($('scenarioBar')) $('scenarioBar').style.display = 'none';

    // Add user message
    appendMessage('user', query);

    // Add thinking state
    const thinkingEl = addThinking();
    state.isTyping = true;

    try {
        const sla = $('slaMode').checked ? 'quality' : 'balanced';
        const debug = $('debugMode').checked;

        let response;
        if (state.apiOnline && !DEMO_MODE) {
            response = await apiCall('/chat', 'POST', {
                message: query,
                conversation_id: state.conversationId,
                history: state.history.map(m => ({ role: m.role, content: m.content })),
                sla_mode: sla,
                debug: debug,
            });
        } else {
            response = await simulateResponse(query, sla, debug);
        }

        state.conversationId = response.conversation_id;
        state.history.push({ role: 'user', content: query });
        state.history.push({ role: 'assistant', content: response.answer });
        state.totalCost += response.token_usage.estimated_cost_usd || 0;
        state.totalMessages++;
        state.tierCounts[response.model_tier] = (state.tierCounts[response.model_tier] || 0) + 1;

        thinkingEl.remove();
        appendAssistantMessage(response);
        updateInspector(response);
        loadBudget();

    } catch (err) {
        thinkingEl.remove();
        appendMessage('user', ''); // empty placeholder fix
        appendErrorMessage(err.message);
    } finally {
        state.isTyping = false;
    }
}

function appendMessage(role, content) {
    const tpl = $(`${role === 'user' ? 'user' : 'assistant'}MsgTpl`).content.cloneNode(true);
    tpl.querySelector('.msg-content').textContent = content;
    messages.appendChild(tpl);
    scrollMessages();
}

function appendAssistantMessage(resp) {
    const tpl = $('assistantMsgTpl').content.cloneNode(true);
    const el = tpl.querySelector('.assistant-message');

    // Meta badges
    const badge = el.querySelector('.model-badge');
    badge.textContent = TIER_LABELS[resp.model_tier] || resp.model_tier;
    badge.dataset.tier = resp.model_tier;

    const confBadge = el.querySelector('.confidence-badge');
    confBadge.textContent = `${capitalize(resp.confidence_band)} confidence (${(resp.confidence * 100).toFixed(0)}%)`;
    confBadge.dataset.band = resp.confidence_band;

    el.querySelector('.latency-val').textContent = resp.latency_ms.toFixed(0);
    el.querySelector('.cost-val').textContent = resp.token_usage.estimated_cost_usd.toFixed(6);

    if (resp.cache_hit) el.querySelector('.cache-badge').style.display = '';

    // Answer
    el.querySelector('.msg-content').innerHTML = formatMarkdown(resp.answer);

    // Citations
    if (resp.citations && resp.citations.length > 0) {
        const citBlock = el.querySelector('.citations-block');
        citBlock.style.display = '';
        const list = citBlock.querySelector('.citations-list');
        resp.citations.slice(0, 3).forEach((c, i) => {
            const item = document.createElement('div');
            item.className = 'citation-item';
            item.innerHTML = `
        <div class="citation-header">
          <span class="citation-source">[${i + 1}] ${escapeHtml(c.document_title)}${c.section_title ? ' — ' + escapeHtml(c.section_title) : ''}</span>
          <span class="citation-score">${(c.relevance_score * 100).toFixed(0)}%</span>
        </div>
        <div class="citation-snippet">${escapeHtml(c.snippet)}</div>
      `;
            list.appendChild(item);
        });
    }

    // Escalation
    if (resp.needs_human) {
        const block = el.querySelector('.escalation-block');
        block.style.display = '';
        if (resp.escalation_reason) {
            block.querySelector('.escalation-banner').innerHTML += ` — ${escapeHtml(resp.escalation_reason)}`;
        }
    }

    // Follow-up question
    if (resp.follow_up_question) {
        const block = el.querySelector('.follow-up-block');
        block.style.display = '';
        block.querySelector('.follow-up-text').textContent = resp.follow_up_question;
    }

    // Feedback buttons
    el.querySelectorAll('.feedback-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            el.querySelectorAll('.feedback-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });

    messages.appendChild(tpl);
    scrollMessages();
}

function appendErrorMessage(msg) {
    const div = document.createElement('div');
    div.className = 'message assistant-message';
    div.innerHTML = `
    <div class="msg-avatar msg-avatar-ai">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2L2 7l10 5 10-5-10-5z"/>
      </svg>
    </div>
    <div class="msg-body">
      <div class="msg-content" style="border-color: rgba(239,68,68,0.3); background: rgba(239,68,68,0.05);">
        <span style="color: #fca5a5;">⚠️ Unable to connect to the API.</span> ${escapeHtml(msg)}<br/><br/>
        <small style="color: var(--text-muted);">Make sure the FastAPI backend is running on port 8000, or enable Demo Mode by setting <code>DEMO_MODE = true</code> in app.js.</small>
      </div>
    </div>
  `;
    messages.appendChild(div);
    scrollMessages();
}

function addThinking() {
    const tpl = $('thinkingTpl').content.cloneNode(true);
    const el = tpl.querySelector('.thinking-message');
    messages.appendChild(tpl);
    scrollMessages();

    // Animate steps
    const steps = ['step-classify', 'step-route', 'step-retrieve', 'step-generate'];
    let i = 0;
    const interval = setInterval(() => {
        if (i > 0) el.querySelector(`#${steps[i - 1]}`).className = 'thinking-step done';
        if (i < steps.length) {
            el.querySelector(`#${steps[i]}`).className = 'thinking-step active';
            i++;
        } else {
            clearInterval(interval);
        }
    }, 600);

    el._interval = interval;
    return el;
}

function scrollMessages() {
    messages.scrollTop = messages.scrollHeight;
}

function buildWelcome() {
    const d = document.createElement('div');
    d.id = 'welcomeState';
    d.className = 'welcome-state';
    d.innerHTML = `
    <div class="welcome-icon">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
      </svg>
    </div>
    <h2>How can I help you today?</h2>
    <p>Ask about returns, refunds, shipping, or your order status.</p>
  `;
    return d;
}

// ── Debug Inspector ────────────────────────────────────────────────────────

function updateInspector(resp) {
    state.debugData = resp;
    renderInspector();
}

$('inspectorTab').addEventListener('change', renderInspector);

function renderInspector() {
    const content = $('inspectorContent');
    if (!state.debugData) {
        content.innerHTML = `
      <div class="inspector-empty">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <p>Send a message to inspect routing decisions, retrieved context, and cost breakdown.</p>
      </div>`;
        return;
    }

    const r = state.debugData;
    const tab = $('inspectorTab').value;

    if (tab === 'routing') {
        const dbg = r.debug;
        const route = dbg?.router_decision || {};
        content.innerHTML = `
      <div class="inspector-section">
        <div class="inspector-section-title">Classification</div>
        ${inspRow('Intent', dbg?.classification?.intent || '—')}
        ${inspRow('Risk Level', dbg?.classification?.risk_level || '—')}
        ${inspRow('Complexity', dbg?.classification?.complexity_score?.toFixed(2) || '—')}
        ${inspRow('Sentiment', dbg?.classification?.sentiment || '—')}
        ${inspRow('Multi-Intent', dbg?.classification?.is_multi_intent ? 'Yes' : 'No')}
      </div>
      <div class="inspector-section">
        <div class="inspector-section-title">Router Decision</div>
        ${inspRow('Model Tier', route.model_tier || r.model_tier, tierClass(r.model_tier))}
        ${inspRow('Model', route.model_name || r.model_used)}
        ${inspRow('Top-K', route.top_k || '—')}
        ${inspRow('Reranker', route.use_reranker ? 'Yes' : 'No')}
        ${inspRow('Max Tokens', route.max_output_tokens || '—')}
        ${inspRow('Tools Allowed', route.allow_tools ? 'Yes' : 'No')}
        ${inspRow('Reason', route.decision_reason || '—')}
        ${inspRow('Budget Usage', route.budget_usage_pct != null ? (route.budget_usage_pct * 100).toFixed(1) + '%' : '—')}
      </div>
      <div class="inspector-section">
        <div class="inspector-section-title">Confidence</div>
        ${inspRow('Score', (r.confidence * 100).toFixed(0) + '%')}
        ${inspRow('Band', r.confidence_band)}
        ${inspRow('Escalate', r.needs_human ? 'Yes' : 'No')}
        ${inspRow('Retrieval Conf.', dbg?.retrieval_confidence?.toFixed(3) || '—')}
      </div>`;

    } else if (tab === 'retrieval') {
        const chunks = r.debug?.retrieved_chunks || [];
        content.innerHTML = `<div class="inspector-section">
      <div class="inspector-section-title">Retrieved Chunks (${chunks.length})</div>
      ${chunks.map((c, i) => `
        <div style="margin-bottom: 10px;">
          <div class="inspector-row">
            <span class="inspector-key">#${i + 1} ${escapeHtml(c.doc)}</span>
            <span class="inspector-val">${(c.score * 100).toFixed(0)}%</span>
          </div>
          ${c.section ? `<div style="font-size:0.72rem; color: var(--text-muted); padding: 2px 0;">§ ${escapeHtml(c.section)}</div>` : ''}
          <div style="font-size: 0.72rem; color: var(--text-muted); padding: 4px 0; font-style: italic;">"${escapeHtml((c.snippet_preview || '').substring(0, 100))}..."</div>
        </div>
      `).join('') || '<div style="color: var(--text-muted); font-size: 0.8rem;">No chunks retrieved.</div>'}
    </div>`;

    } else if (tab === 'cost') {
        const t = r.token_usage;
        content.innerHTML = `
      <div class="inspector-section">
        <div class="inspector-section-title">Token Usage</div>
        ${inspRow('Input Tokens', t.input_tokens?.toLocaleString())}
        ${inspRow('Output Tokens', t.output_tokens?.toLocaleString())}
        ${inspRow('Embed Tokens', t.embedding_tokens?.toLocaleString())}
        ${inspRow('Total Tokens', t.total_tokens?.toLocaleString())}
      </div>
      <div class="inspector-section">
        <div class="inspector-section-title">Cost</div>
        ${inspRow('This Request', '$' + (t.estimated_cost_usd || 0).toFixed(6))}
        ${inspRow('Session Total', '$' + state.totalCost.toFixed(6))}
        ${inspRow('Cache Hit', r.cache_hit ? `Yes (${r.cache_type})` : 'No')}
        ${inspRow('Latency', r.latency_ms.toFixed(0) + 'ms')}
      </div>`;

    } else {
        content.innerHTML = `<div class="inspector-json">${JSON.stringify(r, null, 2)}</div>`;
    }
}

function inspRow(key, val, extra = '') {
    return `<div class="inspector-row">
    <span class="inspector-key">${escapeHtml(String(key))}</span>
    <span class="inspector-val ${extra}">${escapeHtml(String(val))}</span>
  </div>`;
}

function tierClass(tier) {
    return tier === 'cheap' ? 'badge-a' : tier === 'balanced' ? 'badge-b' : tier === 'premium' ? 'badge-c' : '';
}

// ── Analytics ──────────────────────────────────────────────────────────────

async function loadAnalytics() {
    await loadBudget();
    try {
        const cost = state.apiOnline ? await apiCall('/analytics/cost-breakdown') : getDemoCostBreakdown();
        renderCostTable(cost.breakdown || []);
        renderTierChart(cost.breakdown || []);
    } catch { }

    try {
        const lat = state.apiOnline ? await apiCall('/analytics/latency') : getDemoLatency();
        renderLatency(lat.latency || []);
    } catch { }

    // Local session stats
    $('kpiCacheHit').textContent = '—';
    $('kpiEscalation').textContent = '—';
    $('kpiLatency').textContent = '—';
}

function renderCostTable(rows) {
    const tbody = $('costTableBody');
    if (!rows.length) return;
    tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${escapeHtml(r.model_name)}</td>
      <td><span class="model-badge" data-tier="${r.model_tier}">${TIER_LABELS[r.model_tier]}</span></td>
      <td>${r.call_count?.toLocaleString()}</td>
      <td>${r.total_input_tokens?.toLocaleString()}</td>
      <td>${r.total_output_tokens?.toLocaleString()}</td>
      <td>$${parseFloat(r.total_cost_usd).toFixed(4)}</td>
      <td>${parseFloat(r.avg_latency_ms).toFixed(0)}ms</td>
    </tr>
  `).join('');
}

function renderTierChart(rows) {
    const total = rows.reduce((s, r) => s + (r.call_count || 0), 0);
    if (!total) return;
    const tiers = { cheap: 0, balanced: 0, premium: 0 };
    rows.forEach(r => { tiers[r.model_tier] = (tiers[r.model_tier] || 0) + r.call_count; });
    ['a', 'b', 'c'].forEach((l, i) => {
        const tier = ['cheap', 'balanced', 'premium'][i];
        const pct = total ? tiers[tier] / total * 100 : 0;
        $(`tierBar${l.toUpperCase()}`).style.width = `${pct}%`;
        $(`tierPct${l.toUpperCase()}`).textContent = `${pct.toFixed(0)}%`;
    });
}

function renderLatency(rows) {
    const grid = $('latencyGrid');
    if (!rows.length) return;
    grid.innerHTML = rows.map(r => `
    <div class="latency-card">
      <div class="latency-tier">${TIER_LABELS[r.model_tier] || r.model_tier}</div>
      <div class="latency-stat"><span class="latency-stat-label">P50</span><span class="latency-stat-val">${parseFloat(r.p50_ms).toFixed(0)}ms</span></div>
      <div class="latency-stat"><span class="latency-stat-label">P95</span><span class="latency-stat-val">${parseFloat(r.p95_ms).toFixed(0)}ms</span></div>
      <div class="latency-stat"><span class="latency-stat-label">Avg</span><span class="latency-stat-val">${parseFloat(r.avg_ms).toFixed(0)}ms</span></div>
      <div class="latency-stat"><span class="latency-stat-label">Count</span><span class="latency-stat-val">${r.count}</span></div>
    </div>
  `).join('');
}

// ── Evaluation ─────────────────────────────────────────────────────────────

const EVAL_DATA = [
    { id: 'eval_001', query: 'What is the return window for electronics?', intent: 'returns', difficulty: 'easy', requires_escalation: false },
    { id: 'eval_002', query: 'I was charged twice on the same order. What should I do?', intent: 'payment', difficulty: 'medium', requires_escalation: false },
    { id: 'eval_003', query: 'My package says delivered but I never received it.', intent: 'shipping', difficulty: 'medium', requires_escalation: false },
    { id: 'eval_004', query: 'Can I return a used laptop after 35 days?', intent: 'returns', difficulty: 'hard', requires_escalation: false },
    { id: 'eval_005', query: 'How long does it take to get my refund after I return something?', intent: 'refunds', difficulty: 'easy', requires_escalation: false },
    { id: 'eval_006', query: 'Can I return shoes I only wore once?', intent: 'returns', difficulty: 'medium', requires_escalation: false },
    { id: 'eval_007', query: 'What is the holiday return policy?', intent: 'returns', difficulty: 'easy', requires_escalation: false },
    { id: 'eval_008', query: 'I ordered the wrong size shirt. Can I exchange it?', intent: 'returns', difficulty: 'easy', requires_escalation: false },
    { id: 'eval_009', query: 'Can you make an exception and let me return this item after 90 days?', intent: 'returns', difficulty: 'hard', requires_escalation: true },
    { id: 'eval_010', query: 'Is overnight shipping available? How much does it cost?', intent: 'shipping', difficulty: 'easy', requires_escalation: false },
    { id: 'eval_011', query: 'My order is taking too long to arrive.', intent: 'shipping', difficulty: 'medium', requires_escalation: false },
    { id: 'eval_012', query: 'Will I pay customs fees on my international order?', intent: 'shipping', difficulty: 'medium', requires_escalation: false },
    { id: 'eval_013', query: 'I bought some digital software. Can I get a refund?', intent: 'refunds', difficulty: 'medium', requires_escalation: false },
    { id: 'eval_014', query: 'My refund was supposed to come to my Visa card but it\'s been 3 weeks.', intent: 'refunds', difficulty: 'hard', requires_escalation: true },
    { id: 'eval_015', query: 'If I return part of a bundle, do I get a full refund?', intent: 'refunds', difficulty: 'hard', requires_escalation: false },
];

function loadEvalQueries() {
    const container = $('evalQueries');
    container.innerHTML = EVAL_DATA.map(q => `
    <div class="eval-query-item">
      <span class="eval-query-badge badge-${q.intent}">${q.intent}</span>
      <span class="eval-query-text">${escapeHtml(q.query)}</span>
      <div class="eval-query-meta">
        <span class="eval-difficulty-tag">${q.difficulty}</span>
        ${q.requires_escalation ? '<span class="eval-escalation-tag">escalate</span>' : ''}
      </div>
    </div>
  `).join('');
}

$('runEvalBtn').addEventListener('click', async () => {
    $('runEvalBtn').textContent = '⏳ Running...';
    $('runEvalBtn').disabled = true;
    try {
        if (state.apiOnline) {
            const result = await apiCall('/eval/run?run_name=manual_run', 'POST');
            $('evalGroundedness').textContent = result.groundedness_score ? (result.groundedness_score * 100).toFixed(0) + '%' : '—';
        } else {
            // Simulate
            await sleep(2000);
            $('evalGroundedness').textContent = '87%';
            $('evalRetrieval').textContent = '94%';
            $('evalCost').textContent = '$0.0004';
            $('evalLatency').textContent = '820ms';
        }
    } catch (e) {
        console.error(e);
    } finally {
        $('runEvalBtn').textContent = '▶ Run Evaluation';
        $('runEvalBtn').disabled = false;
    }
});

// ── Knowledge Base ─────────────────────────────────────────────────────────

async function loadDocuments() {
    try {
        const data = state.apiOnline ? await apiCall('/documents') : { documents: getDemoDocs() };
        const tbody = $('docsTableBody');
        if (!data.documents.length) return;
        tbody.innerHTML = data.documents.map(d => `
      <tr>
        <td>${escapeHtml(d.title)}</td>
        <td>${escapeHtml(d.policy_type || '—')}</td>
        <td>${escapeHtml(d.region || 'global')}</td>
        <td>${escapeHtml(d.version || '1.0')}</td>
        <td>${d.created_at ? new Date(d.created_at).toLocaleDateString() : '—'}</td>
      </tr>
    `).join('');
    } catch { }
}

// ── Demo Simulation (when API is offline) ─────────────────────────────────

const DEMO_RESPONSES = {
    'return': {
        answer: `Based on our **Returns Policy**, here's what you need to know:

Most items purchased from ShopEase can be returned within **30 days** of the delivery date, provided items are in their original, unused condition with original packaging.

**Category-specific windows:**
- Electronics: 30 days (unopened or defective only)
- Apparel & Shoes: 60 days (unworn, with tags)
- Furniture: 14 days (unassembled only)

**How to start a return:**
1. Log in to your ShopEase account
2. Go to Orders > Return an Item
3. Print the prepaid label and drop off within 7 days

[Source 1: Returns Policy — Standard Return Window]`,
        model_tier: 'cheap', confidence: 0.87, confidence_band: 'high', needs_human: false,
        citations: [{ chunk_id: '1', document_title: 'Returns Policy', section_title: 'Standard Return Window', snippet: 'Most items purchased from ShopEase can be returned within 30 days of the delivery date.', relevance_score: 0.94 }],
    },
    'refund': {
        answer: `I understand you have a question about a refund. Based on our **Refund Policy**:

Refunds are issued to the **original payment method** whenever possible.

**Timelines by payment method:**
- Credit/Debit Card: 5–10 business days
- PayPal: 3–5 business days
- Bank Transfer: 7–14 business days

**After returning an item:** Our team inspects it within 1–3 business days, then issues the refund. **Total time: 7–14 business days** from when we receive the return.

If you were charged twice, please check your bank — pending charges sometimes drop off within 3–5 days. If both charges cleared, contact billing@shopease.com with your order number.

[Source 1: Refund Policy — Refund Timeline]`,
        model_tier: 'premium', confidence: 0.82, confidence_band: 'high', needs_human: false,
        citations: [{ chunk_id: '2', document_title: 'Refund Policy', section_title: 'Refund Timeline After Return', snippet: 'Refunds are issued within 5-10 business days after inspection.', relevance_score: 0.91 }],
    },
    'ship': {
        answer: `Regarding your shipping question — here's what our **Shipping Policy** covers:

**Available shipping methods:**
| Method | Delivery | Cost |
|--------|---------|------|
| Standard | 5–7 business days | Free over $35 |
| Expedited | 2–3 business days | $12.99 |
| Overnight | Next business day | $24.99 |

**If your package shows "delivered" but you didn't receive it:**
1. Wait 3 business days (carriers sometimes mark early)
2. Check with neighbors or building reception
3. Contact the carrier with your tracking number
4. File a claim with ShopEase within 30 days

We'll investigate and offer a full refund or replacement if confirmed lost.

[Source 1: Shipping Policy — Lost or Missing Shipments]`,
        model_tier: 'balanced', confidence: 0.79, confidence_band: 'high', needs_human: false,
        citations: [{ chunk_id: '3', document_title: 'Shipping Policy', section_title: 'Delivered But Not Received', snippet: 'If the carrier marks a package as delivered but you have not received it...', relevance_score: 0.88 }],
    },
    'default': {
        answer: `Thank you for reaching out to ShopEase support! I'd be happy to help with your question.

Based on the information available in our knowledge base, I can assist with questions about:
- **Returns**: Our standard 30-day return policy (60 days for apparel)
- **Refunds**: Processing times and methods
- **Shipping**: Delivery options and missing packages
- **Order status**: Tracking and delivery information

Could you share more specific details about your situation so I can provide the most accurate answer?`,
        model_tier: 'balanced', confidence: 0.45, confidence_band: 'medium', needs_human: false,
        follow_up_question: 'Could you provide more details about your specific situation?',
        citations: [],
    },
};

async function simulateResponse(query, sla, debug) {
    await sleep(1800 + Math.random() * 1200);

    const q = query.toLowerCase();
    let template;
    if (q.includes('return') || q.includes('exchange')) template = DEMO_RESPONSES.return;
    else if (q.includes('refund') || q.includes('charge') || q.includes('payment')) template = DEMO_RESPONSES.refund;
    else if (q.includes('ship') || q.includes('deliver') || q.includes('package') || q.includes('tracking')) template = DEMO_RESPONSES.ship;
    else template = DEMO_RESPONSES.default;

    const convId = state.conversationId || 'demo-' + Date.now();
    const cost = template.model_tier === 'cheap' ? 0.00018 : template.model_tier === 'balanced' ? 0.00045 : 0.0012;

    return {
        request_id: 'req-' + Date.now(),
        conversation_id: convId,
        answer: template.answer,
        citations: template.citations || [],
        confidence: template.confidence,
        confidence_band: template.confidence_band,
        needs_human: template.needs_human || false,
        escalation_reason: template.escalation_reason || null,
        follow_up_question: template.follow_up_question || null,
        model_used: { cheap: 'gpt-3.5-turbo', balanced: 'gpt-4o-mini', premium: 'gpt-4o' }[template.model_tier],
        model_tier: template.model_tier,
        latency_ms: 800 + Math.random() * 1200,
        token_usage: { input_tokens: 320, output_tokens: 180, embedding_tokens: 8, total_tokens: 508, estimated_cost_usd: cost },
        cache_hit: false,
        tool_calls: [],
        debug: debug ? {
            classification: { intent: q.includes('return') ? 'returns' : q.includes('refund') ? 'refunds' : 'shipping', risk_level: template.model_tier === 'premium' ? 'high' : 'medium', complexity_score: 0.35, sentiment: 'neutral', is_multi_intent: false },
            router_decision: { model_tier: template.model_tier, model_name: { cheap: 'gpt-3.5-turbo', balanced: 'gpt-4o-mini', premium: 'gpt-4o' }[template.model_tier], top_k: { cheap: 3, balanced: 6, premium: 8 }[template.model_tier], use_reranker: template.model_tier !== 'cheap', max_output_tokens: { cheap: 200, balanced: 400, premium: 700 }[template.model_tier], allow_tools: false, decision_reason: 'demo_simulation', budget_usage_pct: state.totalCost / 50 },
            retrieval_confidence: template.confidence,
            retrieved_chunks: template.citations.map(c => ({ doc: c.document_title, section: c.section_title, score: c.relevance_score, snippet_preview: c.snippet })),
        } : null,
    };
}

// ── Demo Fallback Data ─────────────────────────────────────────────────────

function getDemoCostBreakdown() {
    return {
        breakdown: [
            { model_tier: 'cheap', model_name: 'gpt-3.5-turbo', call_count: 42, total_input_tokens: 13440, total_output_tokens: 8400, total_cost_usd: 0.019, avg_latency_ms: 680 },
            { model_tier: 'balanced', model_name: 'gpt-4o-mini', call_count: 31, total_input_tokens: 9920, total_output_tokens: 12400, total_cost_usd: 0.0089, avg_latency_ms: 1120 },
            { model_tier: 'premium', model_name: 'gpt-4o', call_count: 12, total_input_tokens: 3840, total_output_tokens: 8400, total_cost_usd: 0.1449, avg_latency_ms: 2340 },
        ]
    };
}

function getDemoLatency() {
    return {
        latency: [
            { model_tier: 'cheap', p50_ms: 650, p95_ms: 1120, avg_ms: 680, count: 42 },
            { model_tier: 'balanced', p50_ms: 1050, p95_ms: 1980, avg_ms: 1120, count: 31 },
            { model_tier: 'premium', p50_ms: 2180, p95_ms: 3840, avg_ms: 2340, count: 12 },
        ]
    };
}

function getDemoDocs() {
    return [
        { title: 'Returns Policy', policy_type: 'returns', region: 'global', version: '1.0', created_at: new Date().toISOString() },
        { title: 'Refund Policy', policy_type: 'refunds', region: 'global', version: '1.0', created_at: new Date().toISOString() },
        { title: 'Shipping Policy', policy_type: 'shipping', region: 'global', version: '1.0', created_at: new Date().toISOString() },
    ];
}

// ── Utilities ──────────────────────────────────────────────────────────────

const TIER_LABELS = { cheap: 'Tier A · Cheap', balanced: 'Tier B · Balanced', premium: 'Tier C · Premium' };

function capitalize(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }

function escapeHtml(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatMarkdown(text) {
    if (!text) return '';
    return text
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code style="background:var(--bg-card);padding:1px 5px;border-radius:3px;font-family:monospace;font-size:0.85em;">$1</code>')
        .replace(/\n- (.+)/g, '\n• $1')
        .replace(/\n\n/g, '<br/><br/>')
        .replace(/\n/g, '<br/>');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── Init ───────────────────────────────────────────────────────────────────

async function init() {
    await checkHealth();
    await loadBudget();
    loadEvalQueries();

    // Auto-load demo data for analytics
    if (!state.apiOnline || DEMO_MODE) {
        renderCostTable(getDemoCostBreakdown().breakdown);
        renderTierChart(getDemoCostBreakdown().breakdown);
        renderLatency(getDemoLatency().latency);
        loadDocuments();
    }

    // Refresh budget every 30s
    setInterval(loadBudget, 30000);
}

init();
