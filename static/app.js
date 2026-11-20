const state = {
  snapshot: null,
  issueFilter: "all",
  kwFilter: "all",
  charts: { pages: null, severity: null, radar: null },
  token: localStorage.getItem("genemeal_seo_token") || "",
  pendingAction: null,
  seenEventIds: new Set(),
};

const $ = (id) => document.getElementById(id);

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showToast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.classList.add("hidden"), 3400);
}

function formatLocalTime(iso) {
  if (!iso) return "--";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

/* Particle Sparkle Background */
function initSparkles() {
  const canvas = $("sparkle-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  let w = 0, h = 0;
  const particles = [];
  const COUNT = 44;

  function resize() {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener("resize", resize);

  for (let i = 0; i < COUNT; i++) {
    particles.push({
      x: Math.random() * window.innerWidth,
      y: Math.random() * window.innerHeight,
      vx: (Math.random() - 0.5) * 0.28,
      vy: (Math.random() - 0.5) * 0.28,
      r: 1 + Math.random() * 1.8,
      hue: Math.random() > 0.5 ? "16,185,129" : "56,189,248",
      a: 0.25 + Math.random() * 0.55,
    });
  }

  function step() {
    ctx.clearRect(0, 0, w, h);
    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0) p.x = w;
      if (p.x > w) p.x = 0;
      if (p.y < 0) p.y = h;
      if (p.y > h) p.y = 0;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${p.hue},${p.a})`;
      ctx.fill();

      for (let j = i + 1; j < particles.length; j++) {
        const q = particles[j];
        const dx = p.x - q.x;
        const dy = p.y - q.y;
        const dist = Math.hypot(dx, dy);
        if (dist < 120) {
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(q.x, q.y);
          ctx.strokeStyle = `rgba(56,189,248,${(1 - dist / 120) * 0.12})`;
          ctx.lineWidth = 0.8;
          ctx.stroke();
        }
      }
    }
    requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

/* Terminal Stream Rendering */
function appendLogLine(ev, animateType = false) {
  if (ev.id && state.seenEventIds.has(ev.id)) return;
  if (ev.id) state.seenEventIds.add(ev.id);

  const log = $("terminal-log");
  const row = document.createElement("div");
  row.className = `log-line log-${ev.level || "info"}`;

  const tsSpan = document.createElement("span");
  tsSpan.className = "log-ts";
  tsSpan.textContent = formatLocalTime(ev.ts);

  const stSpan = document.createElement("span");
  stSpan.className = "log-stage";
  stSpan.textContent = ev.stage || "bot";

  const msgSpan = document.createElement("span");
  msgSpan.className = "log-msg";

  row.append(tsSpan, stSpan, msgSpan);
  log.appendChild(row);

  while (log.children.length > 90) {
    log.removeChild(log.firstChild);
  }

  const fullText = ev.message || "";
  if (animateType && fullText.length > 0 && fullText.length < 180) {
    let idx = 0;
    const timer = setInterval(() => {
      idx += 4;
      msgSpan.textContent = fullText.slice(0, idx);
      log.scrollTop = log.scrollHeight;
      if (idx >= fullText.length) clearInterval(timer);
    }, 14);
  } else {
    msgSpan.textContent = fullText;
    log.scrollTop = log.scrollHeight;
  }
}

/* Gauge & Count-up */
function animateNumber(el, target, decimals = 0) {
  const start = parseFloat(el.dataset.val || "0") || 0;
  el.dataset.val = String(target);
  const t0 = performance.now();
  const dur = 650;
  function frame(now) {
    const p = Math.min(1, (now - t0) / dur);
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
  $("gauge-arc").style.strokeDashoffset = String(circ * (1 - clamped / 100));
  animateNumber($("gauge-number"), clamped, 1);

  let grade = "C";
  if (clamped >= 90) grade = "A+";
  else if (clamped >= 80) grade = "A";
  else if (clamped >= 70) grade = "B";
  else if (clamped >= 60) grade = "B-";
  $("grade-badge").textContent = clamped > 0 ? `Grade ${grade}` : "--";

  const cats = summary?.category_percentages || {};
  const pillars = [
    ["CTR & Snippets (30%)", cats.ctr_readiness ?? 0],
    ["Technical & Crawl (25%)", cats.technical ?? 0],
    ["Content & Headings (20%)", cats.content ?? 0],
    ["Schema / JSON-LD (15%)", cats.schema ?? 0],
    ["Speed & Alt Tags (10%)", cats.performance ?? 0],
  ];
  $("pillar-bars").innerHTML = pillars
    .map(
      ([label, pct]) => `
      <div class="pillar-row">
        <div class="pillar-meta"><span>${esc(label)}</span><span>${Number(pct).toFixed(0)}%</span></div>
        <div class="bar-bg"><div class="bar-fill" style="width:${Math.max(0, Math.min(100, pct))}%"></div></div>
      </div>`
    )
    .join("");
}

/* Charts */
function renderCharts(pages, summary) {
  if (typeof Chart === "undefined") return;
  Chart.defaults.color = "#94a3b8";
  Chart.defaults.font.family = "'Inter', sans-serif";

  const labels = pages.map((p) => (p.path.length > 18 ? p.path.slice(0, 17) + "…" : p.path));
  const scores = pages.map((p) => p.page_score);
  const latencies = pages.map((p) => Math.round(p.response_ms));

  if (state.charts.pages) state.charts.pages.destroy();
  state.charts.pages = new Chart($("pagesChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Page Score (/100)",
          data: scores,
          backgroundColor: "rgba(16, 185, 129, 0.55)",
          borderColor: "#34d399",
          borderWidth: 1.5,
          borderRadius: 6,
          yAxisID: "y",
        },
        {
          label: "Response (ms)",
          data: latencies,
          type: "line",
          borderColor: "#38bdf8",
          backgroundColor: "rgba(56, 189, 248, 0.18)",
          tension: 0.35,
          pointRadius: 3.5,
          yAxisID: "y1",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { boxWidth: 12, font: { size: 11 } } } },
      scales: {
        x: { grid: { color: "rgba(148,163,184,0.08)" } },
        y: { beginAtZero: true, max: 100, grid: { color: "rgba(148,163,184,0.08)" } },
        y1: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false } },
      },
    },
  });

  const sev = summary?.severity_counts || { critical: 0, high: 0, medium: 0, low: 0 };
  if (state.charts.severity) state.charts.severity.destroy();
  state.charts.severity = new Chart($("severityChart"), {
    type: "doughnut",
    data: {
      labels: ["Critical", "High", "Medium", "Low"],
      datasets: [
        {
          data: [sev.critical || 0, sev.high || 0, sev.medium || 0, sev.low || 0],
          backgroundColor: ["#f43f5e", "#f59e0b", "#06b6d4", "#64748b"],
          borderColor: "rgba(10,16,36,0.9)",
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "64%",
      plugins: { legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 11 } } } },
    },
  });

  const cats = summary?.category_percentages || {};
  if (state.charts.radar) state.charts.radar.destroy();
  state.charts.radar = new Chart($("radarChart"), {
    type: "radar",
    data: {
      labels: ["CTR", "Technical", "Content", "Schema", "Speed/Alt"],
      datasets: [
        {
          label: "Measured %",
          data: [
            cats.ctr_readiness || 0,
            cats.technical || 0,
            cats.content || 0,
            cats.schema || 0,
            cats.performance || 0,
          ],
          backgroundColor: "rgba(99, 102, 241, 0.25)",
          borderColor: "#818cf8",
          pointBackgroundColor: "#34d399",
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        r: {
          beginAtZero: true,
          max: 100,
          ticks: { display: false },
          grid: { color: "rgba(148,163,184,0.14)" },
          angleLines: { color: "rgba(148,163,184,0.14)" },
          pointLabels: { color: "#cbd5e1", font: { size: 11 } },
        },
      },
    },
  });
}

function renderRewrites(rewrites) {
  $("rewrites-count").textContent = `${rewrites.length} proposals`;
  if (!rewrites.length) {
    $("rewrites-grid").innerHTML = `<p class="panel-sub">No CTR rewrites generated yet.</p>`;
    return;
  }
  $("rewrites-grid").innerHTML = rewrites
    .map(
      (r) => `
      <div class="rewrite-card">
        <div class="rw-head">
          <span class="rw-path">${esc(r.path)}</span>
          <span class="impact-badge impact-${esc(r.expected_ctr_impact)}">${esc(r.expected_ctr_impact)} CTR Lift Potential</span>
        </div>
        <div class="serp-box">
          <div class="serp-label"><span>Measured Current SERP</span><span>${esc(r.current_title.length)}c / ${esc(r.current_meta === "(missing)" ? 0 : r.current_meta.length)}c</span></div>
          <div class="serp-title">${esc(r.current_title)}</div>
          <div class="serp-meta">${esc(r.current_meta)}</div>
        </div>
        <div class="serp-box suggested">
          <div class="serp-label"><span>Proposed CTR Rewrite</span><span>${esc(r.suggested_title.length)}c / ${esc(r.suggested_meta.length)}c</span></div>
          <div class="serp-title">${esc(r.suggested_title)}</div>
          <div class="serp-meta">${esc(r.suggested_meta)}</div>
        </div>
        <p class="rw-rationale">${esc(r.rationale)}</p>
      </div>`
    )
    .join("");
}

function renderIssues(issues) {
  const filtered = state.issueFilter === "all" ? issues : issues.filter((i) => i.severity === state.issueFilter);
  if (!filtered.length) {
    $("issues-list").innerHTML = `<p class="panel-sub">No findings in this severity filter.</p>`;
    return;
  }
  $("issues-list").innerHTML = filtered
    .map(
      (i) => `
      <div class="issue-item sev-${esc(i.severity)}">
        <div class="issue-top">
          <span class="issue-title">${esc(i.title)}</span>
          <span class="sev-tag sev-${esc(i.severity)}-tag">${esc(i.severity)} · ${esc(i.category)}</span>
        </div>
        <div class="issue-detail">${esc(i.detail)}</div>
        <div class="issue-rec">Fix: ${esc(i.recommendation)}</div>
      </div>`
    )
    .join("");
}

function renderPagesTable(pages) {
  $("pages-count").textContent = `${pages.length} pages`;
  $("pages-tbody").innerHTML = pages
    .map((p) => {
      const cls = p.page_score >= 80 ? "score-good" : p.page_score >= 60 ? "score-mid" : "score-low";
      const schemaText = p.json_ld_types && p.json_ld_types.length ? p.json_ld_types.join(", ") : "None";
      return `
        <tr>
          <td class="path-cell" title="${esc(p.url)}">${esc(p.path)}</td>
          <td><span class="score-pill ${cls}">${p.page_score}</span></td>
          <td>${p.status_code}</td>
          <td>${Math.round(p.response_ms)}</td>
          <td>${p.title_len}c / ${p.meta_desc_len}c</td>
          <td>${p.h1_count}</td>
          <td>${esc(schemaText)}</td>
        </tr>`;
    })
    .join("");
}

function renderKeywords(keywords) {
  const filtered = state.kwFilter === "all" ? keywords : keywords.filter((k) => k.intent === state.kwFilter);
  if (!filtered.length) {
    $("keyword-cloud").innerHTML = `<p class="panel-sub">No keyword suggestions yet. Click Discover Keywords.</p>`;
    return;
  }
  $("keyword-cloud").innerHTML = filtered
    .map((k) => {
      const size = (0.76 + (k.relevance_score / 100) * 0.24).toFixed(2);
      const src = k.source === "google_autocomplete" ? "Autocomplete" : "Positioning Gap";
      return `
        <div class="kw-pill" title="${esc(k.suggested_angle)} (Source: ${src})">
          <span class="kw-text" style="font-size:${size}rem">${esc(k.keyword)}</span>
          <span class="kw-meta">${esc(k.intent)} · ${k.relevance_score}</span>
        </div>`;
    })
    .join("");
}

function renderDrafts(drafts) {
  const pending = drafts.filter((d) => d.status === "pending").length;
  const approved = drafts.filter((d) => d.status === "approved").length;
  $("drafts-summary").textContent = `${pending} pending · ${approved} approved`;

  $("drafts-grid").innerHTML = drafts
    .map(
      (d) => `
      <div class="draft-card status-${esc(d.status)}">
        <div class="draft-top">
          <span class="draft-kw">KW: ${esc(d.target_keyword)}</span>
          <span class="draft-status st-${esc(d.status)}">${esc(d.status)}</span>
        </div>
        <h3 class="draft-title">${esc(d.title)}</h3>
        <p class="draft-meta">${esc(d.meta_description)}</p>
        <ul class="draft-outline">
          ${(d.outline || []).map((h) => `<li>• ${esc(h)}</li>`).join("")}
        </ul>
        <p class="rw-rationale">${esc(d.positioning_notes)}</p>
        <div class="draft-actions">
          <button class="btn btn-sm btn-approve" onclick="setDraftStatus(${d.id}, 'approved')">✓ Approve Outline</button>
          <button class="btn btn-sm btn-reject" onclick="setDraftStatus(${d.id}, 'rejected')">✕ Reject</button>
        </div>
      </div>`
    )
    .join("");
}

function updateStatusPill(botState) {
  const pill = $("status-pill");
  const txt = $("status-text");
  const runBtn = $("run-btn");
  const st = botState?.status || "idle";

  pill.classList.remove("status-idle", "status-crawling");
  if (st === "crawling" || st === "discovering") {
    pill.classList.add("status-crawling");
    txt.textContent = st === "crawling" ? "CRAWLING LIVE" : "DISCOVERING KEYWORDS";
    runBtn.disabled = true;
  } else {
    pill.classList.add("status-idle");
    txt.textContent = "LIVE · IDLE";
    runBtn.disabled = false;
  }
}

function updateTokenBadge() {
  const required = state.snapshot?.auth_required_for_controls;
  const btn = $("token-btn");
  if (!required) {
    btn.classList.add("hidden");
    return;
  }
  btn.classList.remove("hidden");
  if (state.token) {
    $("token-icon").textContent = "🔓";
    $("token-label").textContent = "Controls Unlocked";
  } else {
    $("token-icon").textContent = "🔒";
    $("token-label").textContent = "Unlock Controls";
  }
}

function renderDashboard(snap) {
  state.snapshot = snap;
  const run = snap.active_run;
  const pages = snap.pages || [];
  const issues = snap.issues || [];
  const drafts = snap.drafts || [];

  updateStatusPill(snap.bot_state);
  updateTokenBadge();

  if (run) {
    animateNumber($("kpi-score"), run.overall_score || 0, 1);
    $("kpi-score-sub").textContent = `Run #${run.id} (${run.trigger}) · ${run.status}`;

    animateNumber($("kpi-pages"), run.pages_crawled || 0, 0);
    $("kpi-robots-badges").innerHTML = `
      <span class="mini-badge ${run.robots_found ? "ok" : "warn"}">robots.txt ${run.robots_found ? "✓" : "✕"}</span>
      <span class="mini-badge ${run.sitemap_found ? "ok" : "warn"}">sitemap ${run.sitemap_found ? "✓" : "✕"}</span>`;
    $("kpi-pages-sub").textContent = `${run.sitemap_urls_count || 0} sitemap URLs · ${((run.total_bytes || 0) / 1024).toFixed(1)} KB HTML`;

    animateNumber($("kpi-issues"), issues.length, 0);
    const sev = run.summary?.severity_counts || {};
    $("kpi-sev-pills").innerHTML = `
      <span class="mini-badge crit">${sev.critical || 0}C</span>
      <span class="mini-badge warn">${sev.high || 0}H</span>
      <span class="mini-badge">${sev.medium || 0}M</span>`;

    animateNumber($("kpi-ms"), run.avg_response_ms || 0, 0);
    $("last-run-label").textContent = `Last run: ${formatLocalTime(run.finished_at || run.started_at)}`;
    updateGauge(run.overall_score || 0, run.summary);
    renderCharts(pages, run.summary);
  }

  const pendingDrafts = drafts.filter((d) => d.status === "pending").length;
  const approvedDrafts = drafts.filter((d) => d.status === "approved").length;
  $("kpi-drafts-sub").textContent = `${pendingDrafts} pending / ${approvedDrafts} approved (draft-only)`;

  renderRewrites(snap.rewrites || []);
  renderIssues(issues);
  renderPagesTable(pages);
  renderKeywords(snap.keywords || []);
  renderDrafts(drafts);

  if (Array.isArray(snap.events)) {
    snap.events.forEach((ev) => appendLogLine(ev, false));
  }
}

async function fetchDashboard() {
  try {
    const resp = await fetch("/api/dashboard");
    const data = await resp.json();
    renderDashboard(data);
  } catch (e) {
    console.error("Dashboard load error:", e);
  }
}

async function callControl(url, bodyObj = null) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["X-Control-Token"] = state.token;
  const resp = await fetch(url, {
    method: "POST",
    headers,
    body: bodyObj ? JSON.stringify(bodyObj) : undefined,
  });
  if (resp.status === 401) {
    openTokenModal(() => callControl(url, bodyObj));
    throw new Error("Control token required");
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.detail || data.message || `HTTP ${resp.status}`);
  }
  return data;
}

window.setDraftStatus = async function (draftId, status) {
  try {
    await callControl(`/api/drafts/${draftId}/status`, { status });
    showToast(`Draft marked '${status}' in local queue (not published).`);
    await fetchDashboard();
  } catch (e) {
    if (e.message !== "Control token required") showToast(e.message);
  }
};

function openTokenModal(retryFn = null) {
  state.pendingAction = retryFn;
  $("token-error").classList.add("hidden");
  $("token-input").value = "";
  $("token-modal").classList.remove("hidden");
  $("token-input").focus();
}

function setupControls() {
  $("run-btn").addEventListener("click", async () => {
    try {
      const res = await callControl("/api/run");
      showToast(res.message || "Live SEO audit started.");
      updateStatusPill({ status: "crawling" });
    } catch (e) {
      if (e.message !== "Control token required") showToast(e.message);
    }
  });

  $("keywords-btn").addEventListener("click", async () => {
    try {
      const res = await callControl("/api/keywords/refresh");
      showToast(res.message || "Keyword discovery started.");
      updateStatusPill({ status: "discovering" });
    } catch (e) {
      if (e.message !== "Control token required") showToast(e.message);
    }
  });

  $("token-btn").addEventListener("click", () => openTokenModal(null));
  $("token-cancel").addEventListener("click", () => $("token-modal").classList.add("hidden"));
  $("token-clear").addEventListener("click", () => {
    state.token = "";
    localStorage.removeItem("genemeal_seo_token");
    updateTokenBadge();
    $("token-modal").classList.add("hidden");
    showToast("Saved control token cleared.");
  });

  $("token-save").addEventListener("click", async () => {
    const val = $("token-input").value.trim();
    if (!val) return;
    try {
      const resp = await fetch("/api/auth/verify", {
        method: "POST",
        headers: { "X-Control-Token": val },
      });
      if (!resp.ok) {
        $("token-error").textContent = "Invalid control token.";
        $("token-error").classList.remove("hidden");
        return;
      }
      state.token = val;
      localStorage.setItem("genemeal_seo_token", val);
      updateTokenBadge();
      $("token-modal").classList.add("hidden");
      showToast("Controls unlocked.");
      if (state.pendingAction) {
        const fn = state.pendingAction;
        state.pendingAction = null;
        fn();
      }
    } catch {
      $("token-error").textContent = "Verification failed.";
      $("token-error").classList.remove("hidden");
    }
  });

  $("issue-filters").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-sev]");
    if (!btn) return;
    $("issue-filters").querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    btn.classList.add("active");
    state.issueFilter = btn.dataset.sev;
    renderIssues(state.snapshot?.issues || []);
  });

  $("kw-filters").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-intent]");
    if (!btn) return;
    $("kw-filters").querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    btn.classList.add("active");
    state.kwFilter = btn.dataset.intent;
    renderKeywords(state.snapshot?.keywords || []);
  });
}

function connectSSE() {
  const badge = $("sse-badge");
  const es = new EventSource("/api/events");

  es.onopen = () => {
    badge.textContent = "SSE LIVE STREAMING";
  };

  es.addEventListener("replay", (evt) => {
    try {
      const items = JSON.parse(evt.data);
      items.forEach((ev) => appendLogLine(ev, false));
    } catch {}
  });

  es.addEventListener("activity", (evt) => {
    try {
      const ev = JSON.parse(evt.data);
      appendLogLine(ev, true);
      if (ev.stage === "crawl" || ev.stage === "init") {
        updateStatusPill({ status: "crawling" });
      } else if (ev.stage === "keywords") {
        updateStatusPill({ status: "discovering" });
      }
      if (ev.stage === "score" || ev.stage === "drafts" || (ev.meta && ev.meta.done)) {
        fetchDashboard();
      }
    } catch {}
  });

  es.onerror = () => {
    badge.textContent = "SSE RECONNECTING...";
  };
}

document.addEventListener("DOMContentLoaded", async () => {
  initSparkles();
  setupControls();
  await fetchDashboard();
  connectSSE();
  setInterval(fetchDashboard, 20000);
});
