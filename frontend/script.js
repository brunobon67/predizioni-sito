/* =========================
   Config
========================= */
const BACKEND_URL = (() => {
  const isLocal = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  if (isLocal) return "http://127.0.0.1:5000";
  return "https://predizioni-sito.onrender.com";
})();

const $ = (id) => document.getElementById(id);

/* =========================
   Global UX helpers
========================= */
function showUserMessage(text, type = "info") {
  // type: info | warn | error | success
  const el = document.getElementById("global-message");
  if (el) {
    el.textContent = text;
    el.style.display = "block";
    el.style.padding = "10px 12px";
    el.style.borderRadius = "10px";
    el.style.margin = "10px 0";
    el.style.fontWeight = "700";
    el.style.lineHeight = "1.2";
    el.style.border = "1px solid rgba(0,0,0,0.15)";
    el.style.background =
      type === "error" ? "rgba(220, 53, 69, 0.12)" :
      type === "warn"  ? "rgba(255, 193, 7, 0.16)" :
      type === "success" ? "rgba(25, 135, 84, 0.14)" :
      "rgba(13, 110, 253, 0.12)";
    el.style.color =
      type === "error" ? "#b02a37" :
      type === "warn" ? "#8a6d1d" :
      type === "success" ? "#0f5132" :
      "#084298";
    return;
  }

  // fallback
  alert(text);
}

function clearUserMessage() {
  const el = document.getElementById("global-message");
  if (el) el.style.display = "none";
}

function withTimeout(ms = 15000) {
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), ms);
  return { controller, clear: () => clearTimeout(t) };
}

async function fetchJSON(url, opts = {}, { timeoutMs = 20000, label = "request" } = {}) {
  const { controller, clear } = withTimeout(timeoutMs);
  try {
    const res = await fetch(url, { ...opts, signal: controller.signal });
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      // non-JSON response
    }

    if (!res.ok) {
      const msg = (data && (data.error || data.message)) || `${label} failed (${res.status})`;
      const details = data ? JSON.stringify(data) : "";
      console.error(`[${label}]`, res.status, url, details);
      throw new Error(msg);
    }

    return data;
  } catch (err) {
    if (String(err?.name) === "AbortError") {
      console.error(`[${label}] timeout`, url);
      throw new Error(`${label}: timeout`);
    }
    console.error(`[${label}]`, url, err);
    throw err;
  } finally {
    clear();
  }
}

function pct(x) {
  const v = Number(x || 0);
  return `${(v * 100).toFixed(1)}%`;
}

function num(x, digits = 2) {
  const v = Number(x || 0);
  return v.toFixed(digits);
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function setBar(id, fraction) {
  const el = $(id);
  if (!el) return;
  const f = Math.max(0, Math.min(1, Number(fraction || 0)));
  el.style.width = `${(f * 100).toFixed(1)}%`;
}

/* =========================
   Navbar active link + CTA
========================= */
(function initNav() {
  const links = document.querySelectorAll(".nav-link");
  const sections = ["home", "stats", "standings", "predictions"]
    .map((id) => document.getElementById(id))
    .filter(Boolean);

  function onScroll() {
    const y = window.scrollY + 120;
    let current = "home";
    for (const s of sections) {
      if (s.offsetTop <= y) current = s.id;
    }
    links.forEach((a) => {
      const href = a.getAttribute("href") || "";
      a.classList.toggle("active", href === `#${current}`);
    });
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  const startBtn = $("start-button");
  if (startBtn) {
    startBtn.addEventListener("click", () => {
      const target = document.getElementById("stats");
      if (target) target.scrollIntoView({ behavior: "smooth" });
    });
  }

  const year = $("year");
  if (year) year.textContent = String(new Date().getFullYear());
})();

/* =========================
   Helpers: dynamic UI injection
========================= */
function ensureExtraStatsUI() {
  // Also ensure there is a global message placeholder (optional but helpful)
  if (!document.getElementById("global-message")) {
    const statsSection = document.getElementById("stats");
    if (statsSection) {
      const div = document.createElement("div");
      div.id = "global-message";
      div.style.display = "none";
      // place it at top of stats section
      statsSection.insertBefore(div, statsSection.firstChild);
    }
  }

  const goalsCard = (() => {
    const gf = $("stats-adv-gf");
    if (!gf) return null;
    return gf.closest(".stats-card");
  })();

  if (goalsCard) {
    if (!document.getElementById("stats-avg-total-goals")) {
      const p = document.createElement("p");
      p.innerHTML = `<strong>Media goal totali:</strong> <span id="stats-avg-total-goals">0.00</span>`;
      goalsCard.appendChild(p);
    }

    if (!document.getElementById("stats-fts")) {
      const p = document.createElement("p");
      p.innerHTML = `<strong>Failed to score:</strong> <span id="stats-fts">0</span> (<span id="stats-fts-rate">0.0%</span>)`;
      goalsCard.appendChild(p);
    }
  }

  const ouCard = (() => {
    const over25 = $("stats-over25");
    if (!over25) return null;
    return over25.closest(".stats-card");
  })();

  if (ouCard) {
    if (!document.getElementById("ou-extra-lines")) {
      const div = document.createElement("div");
      div.id = "ou-extra-lines";
      div.style.marginTop = "10px";
      div.innerHTML = `
        <div style="font-weight:800; margin: 10px 0 6px 0;">Altre linee O/U</div>
        <div id="ou-lines-container"></div>
      `;
      ouCard.appendChild(div);
    }
  }
}

function renderExtraOULines(overUnderBlock) {
  ensureExtraStatsUI();

  const container = document.getElementById("ou-lines-container");
  if (!container) return;

  container.innerHTML = "";

  const lines = overUnderBlock?.lines || {};
  const order = ["0_5", "1_5", "3_5", "4_5"];

  for (const key of order) {
    const L = lines[key];
    if (!L) continue;

    const row = document.createElement("p");
    row.style.margin = "6px 0";
    row.innerHTML = `
      <strong>Over ${L.line}:</strong> ${L.over} (<span>${pct(L.over_rate)}</span>)
      &nbsp;—&nbsp;
      <strong>Under ${L.line}:</strong> ${L.under} (<span>${pct(L.under_rate)}</span>)
    `;
    container.appendChild(row);
  }
}

/* =========================
   VS ranking bands table
========================= */
let currentView = "overall";
let lastStatsPayload = null;

function renderVsBandsTable(vsg) {
  const body = document.getElementById("vs-bands-body");
  if (!body) return;

  if (!vsg || vsg.note || !Array.isArray(vsg.rank_bands)) {
    body.innerHTML = `<tr><td colspan="8" class="muted">Seleziona competizione + stagione.</td></tr>`;
    return;
  }

  const scope =
    currentView === "home" ? vsg.bands_home :
    currentView === "away" ? vsg.bands_away :
    vsg.bands;

  const bands = vsg.rank_bands || [];
  if (!bands.length || !scope) {
    body.innerHTML = `<tr><td colspan="8" class="muted">Dati non disponibili.</td></tr>`;
    return;
  }

  body.innerHTML = bands.map((name) => {
    const b = scope[name] || {};
    const mp = b.matches ?? 0;
    const w = b.wins ?? 0;
    const d = b.draws ?? 0;
    const l = b.losses ?? 0;
    const ppg = (b.ppg ?? 0).toFixed(2);
    const gf = b.goals_for ?? 0;
    const ga = b.goals_against ?? 0;

    return `
      <tr>
        <td><b>${name}</b></td>
        <td>${mp}</td>
        <td>${w}</td>
        <td>${d}</td>
        <td>${l}</td>
        <td><b>${ppg}</b></td>
        <td>${gf}</td>
        <td>${ga}</td>
      </tr>
    `;
  }).join("");
}

/* =========================
   Stats
========================= */
function getStatsViewBlock(stats) {
  if (!stats) return null;
  if (currentView === "home") return stats.home;
  if (currentView === "away") return stats.away;
  return stats;
}

function renderStats(stats) {
  if (!stats) return;
  ensureExtraStatsUI();

  setText("stats-team-name", stats.team || "-");
  setText("stats-competition-name", stats.competition === "All" ? "Tutte" : (stats.competition || "Tutte"));
  setText("stats-season-name", stats.season === "All" ? "Tutte" : (stats.season || "Tutte"));

  const view = getStatsViewBlock(stats) || {};
  const played = (currentView === "overall") ? stats.matches_played : (view.matches || 0);
  setText("stats-played", played);

  const wins = view.wins ?? stats.wins ?? 0;
  const draws = view.draws ?? stats.draws ?? 0;
  const losses = view.losses ?? stats.losses ?? 0;

  const winRate = view.win_rate ?? stats.win_rate ?? 0;
  const drawRate = view.draw_rate ?? stats.draw_rate ?? 0;
  const lossRate = view.loss_rate ?? stats.loss_rate ?? 0;

  setText("stats-wins", wins);
  setText("stats-draws", draws);
  setText("stats-losses", losses);

  setText("stats-win-rate", pct(winRate));
  setText("stats-draw-rate", pct(drawRate));
  setText("stats-loss-rate", pct(lossRate));

  setBar("bar-wins", winRate);
  setBar("bar-draws", drawRate);
  setBar("bar-losses", lossRate);

  const goalsFor = (currentView === "overall") ? (stats.goals_scored ?? 0) : (view.goals_scored ?? 0);
  const goalsAgainst = (currentView === "overall") ? (stats.goals_conceded ?? 0) : (view.goals_conceded ?? 0);
  setText("stats-goals-for", goalsFor);
  setText("stats-goals-against", goalsAgainst);

  const vsg = stats.vs_rank_groups || null;
  if (!vsg || vsg.note) {
    setText("vs-top-n", vsg?.top_n ?? "6");
    setText("vs-bottom-n", vsg?.bottom_n ?? "5");

    setText("vs-top-wdl", "0W-0D-0L");
    setText("vs-top-winrate", "0.0%");
    setText("vs-top-matches", "0");

    setText("vs-mid-wdl", "0W-0D-0L");
    setText("vs-mid-winrate", "0.0%");
    setText("vs-mid-matches", "0");

    setText("vs-bottom-wdl", "0W-0D-0L");
    setText("vs-bottom-winrate", "0.0%");
    setText("vs-bottom-matches", "0");

    setText("vs-bottom-threshold", "-");
    setText("vs-total-teams", "-");

    renderVsBandsTable(null);
  } else {
    const scope = currentView === "home" ? vsg.home : (currentView === "away" ? vsg.away : vsg);

    const top = scope.vs_top || { wins: 0, draws: 0, losses: 0, win_rate: 0, matches: 0 };
    const mid = scope.vs_mid || { wins: 0, draws: 0, losses: 0, win_rate: 0, matches: 0 };
    const bottom = scope.vs_bottom || { wins: 0, draws: 0, losses: 0, win_rate: 0, matches: 0 };

    setText("vs-top-n", vsg.top_n);
    setText("vs-bottom-n", vsg.bottom_n);

    setText("vs-top-wdl", `${top.wins}W-${top.draws}D-${top.losses}L`);
    setText("vs-top-winrate", pct(top.win_rate));
    setText("vs-top-matches", top.matches);

    setText("vs-mid-wdl", `${mid.wins}W-${mid.draws}D-${mid.losses}L`);
    setText("vs-mid-winrate", pct(mid.win_rate));
    setText("vs-mid-matches", mid.matches);

    setText("vs-bottom-wdl", `${bottom.wins}W-${bottom.draws}D-${bottom.losses}L`);
    setText("vs-bottom-winrate", pct(bottom.win_rate));
    setText("vs-bottom-matches", bottom.matches);

    setText("vs-bottom-threshold", vsg.bottom_threshold_rank);
    setText("vs-total-teams", vsg.total_teams);

    renderVsBandsTable(vsg);
  }

  const avgGF = (currentView === "overall") ? (stats.goals?.avg_scored ?? 0) : (view.avg_scored ?? 0);
  const avgGA = (currentView === "overall") ? (stats.goals?.avg_conceded ?? 0) : (view.avg_conceded ?? 0);

  const gd = (currentView === "overall")
    ? (stats.goals?.goal_difference ?? (goalsFor - goalsAgainst))
    : ((view.goals_scored ?? 0) - (view.goals_conceded ?? 0));

  setText("stats-adv-gf", goalsFor);
  setText("stats-adv-ga", goalsAgainst);
  setText("stats-adv-gd", gd);

  setText("stats-avg-gf", num(avgGF, 2));
  setText("stats-avg-ga", num(avgGA, 2));

  const avgTotalGoals = (currentView === "overall")
    ? (stats.goals?.avg_total_goals ?? 0)
    : (view.avg_total_goals ?? 0);
  setText("stats-avg-total-goals", num(avgTotalGoals, 2));

  const fts = (currentView === "overall")
    ? (stats.failed_to_score?.count ?? 0)
    : (view.failed_to_score?.count ?? 0);
  const ftsRate = (currentView === "overall")
    ? (stats.failed_to_score?.rate ?? 0)
    : (view.failed_to_score?.rate ?? 0);

  setText("stats-fts", fts);
  setText("stats-fts-rate", pct(ftsRate));

  const ou = view.over_under || stats.over_under || {};
  setText("stats-over25", ou.over_25 ?? 0);
  setText("stats-under25", ou.under_25 ?? 0);
  setText("stats-btts", ou.btts ?? 0);

  setText("stats-over25-rate", pct(ou.over_25_rate ?? 0));
  setText("stats-under25-rate", pct(ou.under_25_rate ?? 0));
  setText("stats-btts-rate", pct(ou.btts_rate ?? 0));

  renderExtraOULines(ou);

  const form = (currentView === "overall") ? stats.form : (view.form || {});
  const f5 = form?.last_5 || {};
  const f10 = form?.last_10 || {};

  setText("stats-form5-record", f5.record || "0W-0D-0L");
  setText("stats-form5-points", f5.points ?? 0);
  setText("stats-form5-gf", f5.goals_scored ?? 0);
  setText("stats-form5-ga", f5.goals_conceded ?? 0);

  setText("stats-form10-record", f10.record || "0W-0D-0L");
  setText("stats-form10-points", f10.points ?? 0);
  setText("stats-form10-gf", f10.goals_scored ?? 0);
  setText("stats-form10-ga", f10.goals_conceded ?? 0);
}

async function fetchTeamsForFilters() {
  clearUserMessage();
  const competition = $("stats-competition")?.value || "";
  const season = $("stats-season")?.value || "";
  const params = new URLSearchParams();
  if (competition) params.set("competition", competition);
  if (season) params.set("season", season);

  // Primary: /api/teams
  const url = `${BACKEND_URL}/api/teams?${params.toString()}`;

  try {
    const data = await fetchJSON(url, {}, { label: "fetch teams", timeoutMs: 20000 });

    const sel = $("stats-team");
    if (!sel) return;
    const current = sel.value;

    sel.innerHTML = `<option value="">Seleziona squadra</option>`;
    (data.teams || []).forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    });

    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
    return;
  } catch (e) {
    console.warn("fetchTeamsForFilters primary failed:", e);
  }

  // Fallback: derive teams from /api/matches (UPCOMING cache)
  try {
    const matchesData = await fetchJSON(`${BACKEND_URL}/api/matches`, {}, { label: "fallback matches", timeoutMs: 20000 });
    const matches = Array.isArray(matchesData.matches) ? matchesData.matches : [];
    const teams = new Set();

    for (const m of matches) {
      if (competition && m.competition !== competition) continue;
      if (season && String(m.season) !== String(season)) continue;
      if (m.home_team) teams.add(m.home_team);
      if (m.away_team) teams.add(m.away_team);
    }

    const sel = $("stats-team");
    if (!sel) return;

    sel.innerHTML = `<option value="">Seleziona squadra</option>`;
    [...teams].sort((a, b) => String(a).localeCompare(String(b))).forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    });

    showUserMessage("⚠️ /api/teams non disponibile: ho caricato le squadre da /api/matches (fallback).", "warn");
  } catch (e) {
    showUserMessage("❌ Impossibile caricare le squadre (backend non raggiungibile o CORS).", "error");
  }
}

async function fetchStats() {
  clearUserMessage();
  const competition = $("stats-competition")?.value || "";
  const season = $("stats-season")?.value || "";
  const team = $("stats-team")?.value || "";

  if (!team) {
    showUserMessage("Seleziona una squadra.", "warn");
    return;
  }

  const params = new URLSearchParams();
  params.set("team", team);
  if (competition) params.set("competition", competition);
  if (season) params.set("season", season);

  const url = `${BACKEND_URL}/api/stats?${params.toString()}`;

  try {
    const data = await fetchJSON(url, {}, { label: "fetch stats", timeoutMs: 25000 });
    lastStatsPayload = data;
    renderStats(lastStatsPayload);
    showUserMessage("✅ Statistiche aggiornate.", "success");
  } catch (e) {
    showUserMessage(`❌ Statistiche non disponibili: ${e.message}`, "error");
  }
}

function setStatsView(view) {
  currentView = view;

  ["overall", "home", "away"].forEach((v) => {
    const id = `view-${v}`;
    const btn = $(id);
    if (btn) btn.classList.toggle("active", v === view);
  });

  if (lastStatsPayload) renderStats(lastStatsPayload);
}

(function initStats() {
  ensureExtraStatsUI();

  const comp = $("stats-competition");
  const season = $("stats-season");
  const btn = $("stats-button");

  if (comp) comp.addEventListener("change", () => fetchTeamsForFilters());
  if (season) season.addEventListener("change", () => fetchTeamsForFilters());
  if (btn) btn.addEventListener("click", () => fetchStats());

  const bOverall = $("view-overall");
  const bHome = $("view-home");
  const bAway = $("view-away");

  if (bOverall) bOverall.addEventListener("click", () => setStatsView("overall"));
  if (bHome) bHome.addEventListener("click", () => setStatsView("home"));
  if (bAway) bAway.addEventListener("click", () => setStatsView("away"));

  fetchTeamsForFilters();
})();

/* =========================
   Standings
========================= */
async function fetchStandings() {
  clearUserMessage();
  const competition = $("standings-competition")?.value || "";
  const season = $("standings-season")?.value || "";
  const date = $("standings-date")?.value || "";

  if (!competition || !season || !date) {
    showUserMessage("Seleziona competizione, stagione e data.", "warn");
    return;
  }

  const params = new URLSearchParams({ competition, season, date });
  const url = `${BACKEND_URL}/api/standings?${params.toString()}`;

  try {
    const data = await fetchJSON(url, {}, { label: "fetch standings", timeoutMs: 25000 });
    renderStandingsTable(data.standings || []);
  } catch (e) {
    showUserMessage(`❌ Classifica non disponibile: ${e.message}`, "error");
  }
}

function renderStandingsTable(rows) {
  const wrap = $("standings-table");
  if (!wrap) return;

  if (!rows.length) {
    wrap.innerHTML = `<p class="muted">Nessun dato disponibile.</p>`;
    return;
  }

  const thead = `
    <thead>
      <tr>
        <th>#</th>
        <th>Squadra</th>
        <th>P</th>
        <th>G</th>
        <th>V</th>
        <th>N</th>
        <th>P</th>
        <th>GF</th>
        <th>GA</th>
        <th>DG</th>
      </tr>
    </thead>
  `;

  const tbody = rows.map((r) => `
    <tr>
      <td>${r.rank}</td>
      <td>${r.team}</td>
      <td>${r.points}</td>
      <td>${r.played}</td>
      <td>${r.wins}</td>
      <td>${r.draws}</td>
      <td>${r.losses}</td>
      <td>${r.gf}</td>
      <td>${r.ga}</td>
      <td>${r.gd}</td>
    </tr>
  `).join("");

  wrap.innerHTML = `
    <div class="table-wrap">
      <table class="table">
        ${thead}
        <tbody>${tbody}</tbody>
      </table>
    </div>
  `;
}

(function initStandings() {
  const btn = $("standings-button");
  if (btn) btn.addEventListener("click", () => fetchStandings());
})();

/* =========================
   Predictions (BASE = rules_v1)
========================= */
let upcomingMatchesCache = [];

function uniqSorted(arr) {
  return [...new Set(arr.filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b)));
}

function setSelectOptions(selectEl, values, { includeAll = true, allLabel = "Tutte" } = {}) {
  if (!selectEl) return;
  const current = selectEl.value;
  selectEl.innerHTML = "";
  if (includeAll) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = allLabel;
    selectEl.appendChild(opt);
  }
  values.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = String(v);
    opt.textContent = String(v);
    selectEl.appendChild(opt);
  });
  if ([...selectEl.options].some(o => o.value === current)) selectEl.value = current;
}

function formatMatchLabel(m) {
  return `${m.date} — ${m.home_team} vs ${m.away_team} (${m.competition}, ${m.season})`;
}

function filterUpcomingMatches() {
  const comp = $("pred-competition")?.value || "";
  const season = $("pred-season")?.value || "";

  return upcomingMatchesCache.filter((m) => {
    const okComp = !comp || m.competition === comp;
    const okSeason = !season || String(m.season) === String(season);
    return okComp && okSeason;
  });
}

function renderPredMatchSelect() {
  const matchSel = $("pred-match");
  if (!matchSel) return;

  const filtered = filterUpcomingMatches();

  matchSel.innerHTML = `<option value="">Seleziona match</option>`;
  filtered.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = String(m.id);
    opt.textContent = formatMatchLabel(m);
    matchSel.appendChild(opt);
  });

  if (!filtered.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Nessun match futuro con questi filtri";
    matchSel.appendChild(opt);
  }
}

function buildPredFiltersFromMatches() {
  const compSel = $("pred-competition");
  const seasonSel = $("pred-season");

  const comps = uniqSorted(upcomingMatchesCache.map(m => m.competition));
  setSelectOptions(compSel, comps, { includeAll: true, allLabel: "Tutte" });

  const seasons = uniqSorted(upcomingMatchesCache.map(m => String(m.season)));
  setSelectOptions(seasonSel, seasons, { includeAll: true, allLabel: "Tutte" });

  renderPredMatchSelect();
}

async function fetchMatchesForPredictions() {
  clearUserMessage();
  try {
    const data = await fetchJSON(`${BACKEND_URL}/api/matches`, {}, { label: "fetch matches", timeoutMs: 25000 });
    upcomingMatchesCache = Array.isArray(data.matches) ? data.matches : [];
    buildPredFiltersFromMatches();
  } catch (e) {
    showUserMessage(`❌ Impossibile caricare i match futuri: ${e.message}`, "error");
  }
}

function buildExplanationFromDebug(data) {
  const r = data?.debug?.ranks || {};
  const c = data?.debug?.components || {};

  const parts = [];
  if (r && (r.home_rank_before || r.away_rank_before)) {
    parts.push(`Rank pre-match: Casa ${r.home_rank_before} — Trasferta ${r.away_rank_before} (diff ${r.rank_diff}).`);
  }

  const compLines = [
    ["Rank score", c.rank_score],
    ["Home perf", c.home_perf_score],
    ["Away perf (sub)", c.away_perf_score_subtracted],
    ["Vs fascia", c.vs_score],
    ["Goal score", c.goals_score],
    ["Forma (last5)", c.form_score],
    ["Totale", c.home_score_total],
    ["Draw score", c.draw_score],
  ].filter(([, v]) => typeof v === "number" && !Number.isNaN(v));

  if (compLines.length) {
    parts.push("Componenti (punti): " + compLines.map(([k, v]) => `${k}: ${v.toFixed(2)}`).join(" | "));
  }

  return parts.join("\n");
}

async function predict() {
  clearUserMessage();
  const matchId = $("pred-match")?.value || "";
  const uiModel = $("pred-model")?.value || "";

  const msg = $("prediction-message");
  if (msg) msg.textContent = "";

  if (!matchId || !uiModel) {
    if (msg) msg.textContent = "Seleziona competizione, stagione, match e modello.";
    return;
  }

  if (uiModel !== "modello_base") {
    if (msg) msg.textContent = "Questo modello è in arrivo. Usa 'Base'.";
    return;
  }

  const backendModel = "rules_v1";

  try {
    const data = await fetchJSON(`${BACKEND_URL}/api/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ match_id: Number(matchId), model: backendModel })
    }, { label: "predict", timeoutMs: 25000 });

    const p = data?.probabilities || {};
    const home = Number(p.home_win || 0);
    const draw = Number(p.draw || 0);
    const away = Number(p.away_win || 0);

    setText("prob-home", `${(home * 100).toFixed(1)} %`);
    setText("prob-draw", `${(draw * 100).toFixed(1)} %`);
    setText("prob-away", `${(away * 100).toFixed(1)} %`);

    setBar("prob-home-bar", home);
    setBar("prob-draw-bar", draw);
    setBar("prob-away-bar", away);

    const explanation = buildExplanationFromDebug(data) || "—";
    setText("prediction-explanation-text", explanation);
  } catch (e) {
    if (msg) msg.textContent = `Errore previsione: ${e.message}`;
    showUserMessage(`❌ Previsione non disponibile: ${e.message}`, "error");
  }
}

(function initPredictions() {
  fetchMatchesForPredictions();

  const btn = $("predict-button");
  if (btn) btn.addEventListener("click", () => predict());

  const compSel = $("pred-competition");
  const seasonSel = $("pred-season");
  if (compSel) compSel.addEventListener("change", () => renderPredMatchSelect());
  if (seasonSel) seasonSel.addEventListener("change", () => renderPredMatchSelect());
})();
