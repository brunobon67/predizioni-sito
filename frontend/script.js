/* =========================
   Config
========================= */
const BACKEND_URL = (() => {
  const isLocal = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  if (isLocal) return "http://127.0.0.1:5000";
  return "https://predizioni-sito.onrender.com";
})();

const $ = (id) => document.getElementById(id);

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
  // Card "Goal & medie"
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

  // Card "Under / Over 2,5 & BTTS"
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
   NEW: VS ranking bands table (A+B)
========================= */
function renderVsBandsTable(vsg) {
  const body = document.getElementById("vs-bands-body");
  if (!body) return; // se non hai ancora aggiornato l'HTML, non fa nulla

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
   Stats: fetch teams + fetch stats + view toggle
========================= */
let lastStatsPayload = null;
let currentView = "overall"; // overall | home | away

function getStatsViewBlock(stats) {
  if (!stats) return null;
  if (currentView === "home") return stats.home;
  if (currentView === "away") return stats.away;
  return stats; // overall
}

function renderStats(stats) {
  if (!stats) return;

  ensureExtraStatsUI();

  // header pills
  setText("stats-team-name", stats.team || "-");
  setText("stats-competition-name", stats.competition === "All" ? "Tutte" : (stats.competition || "Tutte"));
  setText("stats-season-name", stats.season === "All" ? "Tutte" : (stats.season || "Tutte"));

  // scegli il blocco in base a Totale/Casa/Trasferta
  const view = getStatsViewBlock(stats) || {};

  // matches played
  const played = (currentView === "overall") ? stats.matches_played : (view.matches || 0);
  setText("stats-played", played);

  // W/D/L + rates (KPI)
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

  // Goals KPI
  const goalsFor = (currentView === "overall") ? (stats.goals_scored ?? 0) : (view.goals_scored ?? 0);
  const goalsAgainst = (currentView === "overall") ? (stats.goals_conceded ?? 0) : (view.goals_conceded ?? 0);
  setText("stats-goals-for", goalsFor);
  setText("stats-goals-against", goalsAgainst);

  // VS Top/Mid/Bottom + Bands
  const vsg = stats.vs_rank_groups || null;
  if (!vsg || vsg.note) {
    setText("vs-top-n", vsg?.top_n ?? "6");
    setText("vs-bottom-n", vsg?.bottom_n ?? "5");

    setText("vs-top-wdl", "0W-0D-0L");
    setText("vs-top-winrate", "0.0%");
    setText("vs-top-matches", "0");

    // NEW: mid
    setText("vs-mid-wdl", "0W-0D-0L");
    setText("vs-mid-winrate", "0.0%");
    setText("vs-mid-matches", "0");

    setText("vs-bottom-wdl", "0W-0D-0L");
    setText("vs-bottom-winrate", "0.0%");
    setText("vs-bottom-matches", "0");

    setText("vs-bottom-threshold", "-");
    setText("vs-total-teams", "-");

    // NEW: bands table placeholder
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

    // NEW: mid
    setText("vs-mid-wdl", `${mid.wins}W-${mid.draws}D-${mid.losses}L`);
    setText("vs-mid-winrate", pct(mid.win_rate));
    setText("vs-mid-matches", mid.matches);

    setText("vs-bottom-wdl", `${bottom.wins}W-${bottom.draws}D-${bottom.losses}L`);
    setText("vs-bottom-winrate", pct(bottom.win_rate));
    setText("vs-bottom-matches", bottom.matches);

    setText("vs-bottom-threshold", vsg.bottom_threshold_rank);
    setText("vs-total-teams", vsg.total_teams);

    // NEW: bands table (respects Totale/Casa/Trasferta)
    renderVsBandsTable(vsg);
  }

  // Advanced: Goal & medie
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

  // NEW: avg_total_goals
  const avgTotalGoals = (currentView === "overall")
    ? (stats.goals?.avg_total_goals ?? 0)
    : (view.avg_total_goals ?? 0);
  setText("stats-avg-total-goals", num(avgTotalGoals, 2));

  // NEW: failed_to_score
  const fts = (currentView === "overall")
    ? (stats.failed_to_score?.count ?? 0)
    : (view.failed_to_score?.count ?? 0);
  const ftsRate = (currentView === "overall")
    ? (stats.failed_to_score?.rate ?? 0)
    : (view.failed_to_score?.rate ?? 0);

  setText("stats-fts", fts);
  setText("stats-fts-rate", pct(ftsRate));

  // Advanced: Under/Over 2.5 & BTTS
  const ou = view.over_under || stats.over_under || {};
  setText("stats-over25", ou.over_25 ?? 0);
  setText("stats-under25", ou.under_25 ?? 0);
  setText("stats-btts", ou.btts ?? 0);

  setText("stats-over25-rate", pct(ou.over_25_rate ?? 0));
  setText("stats-under25-rate", pct(ou.under_25_rate ?? 0));
  setText("stats-btts-rate", pct(ou.btts_rate ?? 0));

  // NEW: extra O/U lines
  renderExtraOULines(ou);

  // Form
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
  const competition = $("stats-competition")?.value || "";
  const season = $("stats-season")?.value || "";
  const params = new URLSearchParams();
  if (competition) params.set("competition", competition);
  if (season) params.set("season", season);

  const url = `${BACKEND_URL}/api/teams?${params.toString()}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Errore caricando squads");
  const data = await res.json();

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
}

async function fetchStats() {
  const competition = $("stats-competition")?.value || "";
  const season = $("stats-season")?.value || "";
  const team = $("stats-team")?.value || "";

  if (!team) {
    alert("Seleziona una squadra.");
    return;
  }

  const params = new URLSearchParams();
  params.set("team", team);
  if (competition) params.set("competition", competition);
  if (season) params.set("season", season);

  const url = `${BACKEND_URL}/api/stats?${params.toString()}`;
  const res = await fetch(url);
  const data = await res.json();

  if (!res.ok) {
    alert(data?.error || "Errore nel calcolo statistiche");
    return;
  }

  lastStatsPayload = data;
  renderStats(lastStatsPayload);
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

  if (comp) comp.addEventListener("change", () => fetchTeamsForFilters().catch(console.error));
  if (season) season.addEventListener("change", () => fetchTeamsForFilters().catch(console.error));
  if (btn) btn.addEventListener("click", () => fetchStats().catch(console.error));

  const bOverall = $("view-overall");
  const bHome = $("view-home");
  const bAway = $("view-away");

  if (bOverall) bOverall.addEventListener("click", () => setStatsView("overall"));
  if (bHome) bHome.addEventListener("click", () => setStatsView("home"));
  if (bAway) bAway.addEventListener("click", () => setStatsView("away"));

  fetchTeamsForFilters().catch(console.error);
})();

/* =========================
   Standings
========================= */
async function fetchStandings() {
  const competition = $("standings-competition")?.value || "";
  const season = $("standings-season")?.value || "";
  const date = $("standings-date")?.value || "";

  if (!competition || !season || !date) {
    alert("Seleziona competizione, stagione e data.");
    return;
  }

  const params = new URLSearchParams({ competition, season, date });
  const url = `${BACKEND_URL}/api/standings?${params.toString()}`;

  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) {
    alert(data?.error || "Errore nel caricamento classifica");
    return;
  }

  renderStandingsTable(data.standings || []);
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
  if (btn) btn.addEventListener("click", () => fetchStandings().catch(console.error));
})();

/* =========================
   Predictions (placeholder)
========================= */
async function fetchMatchesForPredictions() {
  const res = await fetch(`${BACKEND_URL}/api/matches`);
  const data = await res.json();
  if (!res.ok) return;

  const matchSel = $("pred-match");
  if (!matchSel) return;

  matchSel.innerHTML = `<option value="">Seleziona match</option>`;

  (data.matches || []).forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = `${m.date} — ${m.home_team} vs ${m.away_team} (${m.competition})`;
    matchSel.appendChild(opt);
  });
}

async function predict() {
  const matchId = $("pred-match")?.value || "";
  const model = $("pred-model")?.value || "";

  const msg = $("prediction-message");
  if (msg) msg.textContent = "";

  if (!matchId || !model) {
    if (msg) msg.textContent = "Seleziona match e modello.";
    return;
  }

  const res = await fetch(`${BACKEND_URL}/api/predict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ match_id: Number(matchId), model })
  });

  const data = await res.json();
  if (!res.ok) {
    if (msg) msg.textContent = data?.error || "Errore previsione";
    return;
  }

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

  setText("prediction-explanation-text", p.explanation || "—");
}

(function initPredictions() {
  fetchMatchesForPredictions().catch(console.error);

  const btn = $("predict-button");
  if (btn) btn.addEventListener("click", () => predict().catch(console.error));
})();
