const state = { snapshot: null, charts: { pages: null, severity: null, radar: null }, seenEventIds: new Set() };
const $ = (id) => document.getElementById(id);
function esc(str) {
  return String(str ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function formatLocalTime(iso) {
  if (!iso) return "--";
  try { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
  catch { return iso; }
}
function appendLogLine(ev) {
  const key = ev.ts + ev.message;
  if (state.seenEventIds.has(key)) return;
  state.seenEventIds.add(key);
  const log = $("terminal-log");
  if (!log) return;
  const row = document.createElement("div");
  row.className = `log-line log-${ev.level || "info"}`;
  row.innerHTML = `<span class="log-ts">${esc(formatLocalTime(ev.ts))}</span><span class="log-stage">${esc(ev.stage || "bot")}</span><span class="log-msg">${esc(ev.message || "")}</span>`;
  log.appendChild(row);
  while (log.children.length > 80) log.removeChild(log.firstChild);
  log.scrollTop = log.scrollHeight;
}
function animateNumber(el, target, decimals = 0) {
  if (!el) return;
  const start = parseFloat(el.dataset.val || "0") || 0;
  el.dataset.val = String(target);
  const t0 = performance.now();
  function frame(now) {
    const p = Math.min(1, (now - t0) / 650);
    const eased = 1 - Math.pow(1 - p, 3);
    const val = start + (target - start) * eased;
    el.textContent = decimals > 0 ? val.toFixed(decimals) : Math.round(val);
    if (p < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}
function updateGauge(score, summary) {
  const circ = 552.92;
  const clamped = Math.max(0, Math.min(100, Number(score) || 0));
  if ($("gauge-arc")) $("gauge-arc").style.strokeDashoffset = String(circ * (1 - clamped / 100));
  if ($("gauge-number")) animateNumber($("gauge-number"), clamped, 1);
  let grade = "C";
  if (clamped >= 90) grade = "A+";
  else if (clamped >= 80) grade = "A";
  else if (clamped >= 70) grade = "B";
  else if (clamped >= 60) grade = "B-";
  if ($("grade-badge")) $("grade-badge").textContent = clamped > 0 ? `Grade ${grade}` : "--";
  const cats = summary?.category_percentages || {};
  const pillars = [
    ["CTR & Snippets (30%)", cats.ctr_readiness ?? 0],
    ["Technical & Crawl (25%)", cats.technical ?? 0],
    ["Content & Headings (20%)", cats.content ?? 0],
    ["Schema / JSON-LD (15%)", cats.schema ?? 0],
    ["Speed & Alt Tags (10%)", cats.performance ?? 0],
  ];
  if ($("pillar-bars")) {
    $("pillar-bars").innerHTML = pillars.map(([label, pct]) => `
      <div class="pillar-row">
        <div class="pillar-meta"><span>${esc(label)}</span><span>${Number(pct).toFixed(0)}%</span></div>
        <div class="bar-bg"><div class="bar-fill" style="width:${Math.max(0, Math.min(100, pct))}%"></div></div>
      </div>`).join("");
  }
}
function renderCharts(pages, summary) {
  if (typeof Chart === "undefined") return;
  Chart.defaults.color = "#94a3b8";
  const labels = pages.map((p) => (p.path.length > 18 ? p.path.slice(0, 17) + "…" : p.path));
  if (state.charts.pages) state.charts.pages.destroy();
  if ($("pagesChart")) {
    state.charts.pages = new Chart($("pagesChart"), {
      type: "bar",
      data: {
        labels,
        datasets: [
          { label: "Page Score (/100)", data: pages.map((p) => p.page_score), backgroundColor: "rgba(16,185,129,0.55)", borderColor: "#34d399", borderWidth: 1.5, borderRadius: 6, yAxisID: "y" },
          { label: "Response (ms)", data: pages.map((p) => Math.round(p.response_ms)), type: "line", borderColor: "#38bdf8", tension: 0.35, pointRadius: 3.5, yAxisID: "y1" },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, max: 100 }, y1: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false } } } },
    });
  }
  const sev = summary?.severity_counts || {};
  if (state.charts.severity) state.charts.severity.destroy();
  if ($("severityChart")) {
    state.charts.severity = new Chart($("severityChart"), {
      type: "doughnut",
      data: { labels: ["Critical", "High", "Medium", "Low"], datasets: [{ data: [sev.critical || 0, sev.high || 0, sev.medium || 0, sev.low || 0], backgroundColor: ["#f43f5e", "#f59e0b", "#06b6d4", "#64748b"], borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "64%", plugins: { legend: { position: "bottom" } } },
    });
  }
  const cats = summary?.category_percentages || {};
  if (state.charts.radar) state.charts.radar.destroy();
  if ($("radarChart")) {
    state.charts.radar = new Chart($("radarChart"), {
      type: "radar",
      data: { labels: ["CTR", "Technical", "Content", "Schema", "Speed/Alt"], datasets: [{ data: [cats.ctr_readiness || 0, cats.technical || 0, cats.content || 0, cats.schema || 0, cats.performance || 0], backgroundColor: "rgba(99,102,241,0.25)", borderColor: "#818cf8", pointBackgroundColor: "#34d399" }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { r: { beginAtZero: true, max: 100, ticks: { display: false } } } },
    });
  }
}
function renderRewrites(rewrites) {
  if (!$("rewrites-grid")) return;
  $("rewrites-count").textContent = `${rewrites.length} proposals`;
  if (!rewrites.length) { $("rewrites-grid").innerHTML = `<p class="panel-sub">No CTR rewrites generated yet.</p>`; return; }
  $("rewrites-grid").innerHTML = rewrites.map((r) => `
    <div class="rewrite-card">
      <div class="rw-head"><span class="rw-path">${esc(r.path)}</span><span class="impact-badge impact-${esc(r.expected_ctr_impact)}">${esc(r.expected_ctr_impact)} CTR Lift Potential</span></div>
      <div class="serp-box"><div class="serp-label"><span>Measured Current SERP</span></div><div class="serp-title">${esc(r.current_title)}</div><div class="serp-meta">${esc(r.current_meta)}</div></div>
      <div class="serp-box suggested"><div class="serp-label"><span>Proposed CTR Rewrite</span></div><div class="serp-title">${esc(r.suggested_title)}</div><div class="serp-meta">${esc(r.suggested_meta)}</div></div>
      <p class="rw-rationale">${esc(r.rationale)}</p>
    </div>`).join("");
}
function renderIssues(issues) {
  if (!$("issues-list")) return;
  if (!issues.length) { $("issues-list").innerHTML = `<p class="panel-sub">No findings yet.</p>`; return; }
  $("issues-list").innerHTML = issues.map((i) => `
    <div class="issue-item sev-${esc(i.severity)}">
      <div class="issue-top"><span class="issue-title">${esc(i.title)}</span><span class="sev-tag sev-${esc(i.severity)}-tag">${esc(i.severity)} · ${esc(i.category)}</span></div>
      <div class="issue-detail">${esc(i.detail)}</div>
      <div class="issue-rec">Fix: ${esc(i.recommendation)}</div>
    </div>`).join("");
}
function renderPagesTable(pages) {
  if (!$("pages-tbody")) return;
  $("pages-count").textContent = `${pages.length} pages`;
  $("pages-tbody").innerHTML = pages.map((p) => {
    const cls = p.page_score >= 80 ? "score-good" : p.page_score >= 60 ? "score-mid" : "score-low";
    const schemaText = p.json_ld_types && p.json_ld_types.length ? p.json_ld_types.join(", ") : "None";
    return `<tr><td class="path-cell">${esc(p.path)}</td><td><span class="score-pill ${cls}">${p.page_score}</span></td><td>${p.status_code}</td><td>${Math.round(p.response_ms)}</td><td>${p.title_len}c / ${p.meta_desc_len}c</td><td>${p.h1_count}</td><td>${esc(schemaText)}</td></tr>`;
  }).join("");
}
function renderKeywords(keywords) {
  if (!$("keyword-cloud")) return;
  if (!keywords.length) { $("keyword-cloud").innerHTML = `<p class="panel-sub">No keyword suggestions yet. Run an audit.</p>`; return; }
  $("keyword-cloud").innerHTML = keywords.map((k) => {
    const size = (0.76 + (k.relevance_score / 100) * 0.24).toFixed(2);
    return `<div class="kw-pill" title="${esc(k.suggested_angle || "")}"><span class="kw-text" style="font-size:${size}rem">${esc(k.keyword)}</span><span class="kw-meta">${esc(k.intent)} · ${k.relevance_score}</span></div>`;
  }).join("");
}
function renderDashboard(snap) {
  state.snapshot = snap;
  const run = snap.active_run || {};
  const pages = snap.pages || [];
  const issues = snap.issues || [];
  const summary = run.summary || run.result?.summary || snap.summary || {};
  const score = run.overall_score || run.result?.overall_score || 0;
  const running = !!snap.running;
  const pill = $("status-pill");
  const txt = $("status-text");
  const runBtn = $("run-btn");
  if (pill && txt) {
    pill.classList.toggle("status-crawling", running);
    pill.classList.toggle("status-idle", !running);
    txt.textContent = running ? "AUDITING" : "READY";
  }
  if (runBtn) runBtn.disabled = running;
  if (run && (run.status === "completed" || score)) {
    animateNumber($("kpi-score"), score, 1);
    $("kpi-score-sub").textContent = `Run #${run.id || "—"} · ${run.status || ""}`;
    animateNumber($("kpi-pages"), run.pages_crawled || pages.length, 0);
    const robots = run.result?.robots_found ?? run.robots_found;
    const sitemap = run.result?.sitemap_found ?? run.sitemap_found;
    if ($("kpi-robots-badges")) {
      $("kpi-robots-badges").innerHTML = `<span class="mini-badge ${robots ? "ok" : "warn"}">robots.txt ${robots ? "✓" : "✕"}</span><span class="mini-badge ${sitemap ? "ok" : "warn"}">sitemap ${sitemap ? "✓" : "✕"}</span>`;
    }
    animateNumber($("kpi-issues"), issues.length, 0);
    const sev = summary.severity_counts || {};
    if ($("kpi-sev-pills")) $("kpi-sev-pills").innerHTML = `<span class="mini-badge crit">${sev.critical || 0}C</span><span class="mini-badge warn">${sev.high || 0}H</span><span class="mini-badge">${sev.medium || 0}M</span><span class="mini-badge">${sev.low || 0}L</span>`;
    animateNumber($("kpi-ms"), run.avg_response_ms || run.result?.avg_response_ms || 0, 0);
    updateGauge(score, summary);
    renderCharts(pages, summary);
  }
  renderRewrites(snap.rewrites || []);
  renderIssues(issues);
  renderPagesTable(pages);
  renderKeywords(snap.keywords || []);
}
async function fetchDashboard() {
  const id = window.TENANT_SITE_ID;
  const resp = await fetch(`/api/app/sites/${id}`, { credentials: "same-origin" });
  if (resp.status === 401) { window.location = "/app/login"; return; }
  if (!resp.ok) return;
  renderDashboard(await resp.json());
}
function connectSSE() {
  const id = window.TENANT_SITE_ID;
  const badge = $("sse-badge");
  const es = new EventSource(`/api/app/sites/${id}/events`);
  es.onopen = () => { if (badge) badge.textContent = "SSE LIVE STREAMING"; };
  es.addEventListener("activity", (evt) => {
    try {
      const ev = JSON.parse(evt.data);
      appendLogLine(ev);
      if (ev.meta && ev.meta.done) fetchDashboard();
    } catch {}
  });
  es.onerror = () => { if (badge) badge.textContent = "SSE RECONNECTING..."; };
}
document.addEventListener("DOMContentLoaded", async () => {
  await fetchDashboard();
  connectSSE();
  setInterval(fetchDashboard, 8000);
});
