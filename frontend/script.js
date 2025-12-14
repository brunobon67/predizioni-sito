const API_BASE_URL = "https://predizioni-sito.onrender.com";
let lastStatsData = null;
let currentView = "overall";

/* =========================
   UTIL
========================= */
function pct(x) {
  return (Number(x || 0) * 100).toFixed(1) + "%";
}

function byId(id) {
  return document.getElementById(id);
}

function setBarWidth(el, ratio) {
  if (!el) return;
  const v = Math.max(0, Math.min(1, Number(ratio || 0)));
  el.style.width = (v * 100).toFixed(1) + "%";
}

/* =========================
   VIEW DATA
========================= */
function getViewData(mode) {
  if (!lastStatsData) return null;

  if (mode === "home") {
    return {
      label: "Casa",
      matches: lastStatsData.home?.matches ?? 0,
      wins: lastStatsData.home?.wins ?? 0,
      draws: lastStatsData.home?.draws ?? 0,
      losses: lastStatsData.home?.losses ?? 0,
      win_rate: lastStatsData.home?.win_rate ?? 0,
      draw_rate: lastStatsData.home?.draw_rate ?? 0,
      loss_rate: lastStatsData.home?.loss_rate ?? 0,
      goals_scored: lastStatsData.home?.goals_scored ?? 0,
      goals_conceded: lastStatsData.home?.goals_conceded ?? 0,
      avg_scored: lastStatsData.home?.avg_scored ?? 0,
      avg_conceded: lastStatsData.home?.avg_conceded ?? 0,
      over_under: lastStatsData.home?.over_under ?? null,
      form: lastStatsData.home?.form ?? null,
      vs: lastStatsData.vs_rank_groups?.home ?? null
    };
  }

  if (mode === "away") {
    return {
      label: "Trasferta",
      matches: lastStatsData.away?.matches ?? 0,
      wins: lastStatsData.away?.wins ?? 0,
      draws: lastStatsData.away?.draws ?? 0,
      losses: lastStatsData.away?.losses ?? 0,
      win_rate: lastStatsData.away?.win_rate ?? 0,
      draw_rate: lastStatsData.away?.draw_rate ?? 0,
      loss_rate: lastStatsData.away?.loss_rate ?? 0,
      goals_scored: lastStatsData.away?.goals_scored ?? 0,
      goals_conceded: lastStatsData.away?.goals_conceded ?? 0,
      avg_scored: lastStatsData.away?.avg_scored ?? 0,
      avg_conceded: lastStatsData.away?.avg_conceded ?? 0,
      over_under: lastStatsData.away?.over_under ?? null,
      form: lastStatsData.away?.form ?? null,
      vs: lastStatsData.vs_rank_groups?.away ?? null
    };
  }

  // overall
  return {
    label: "Totale",
    matches: lastStatsData.matches_played ?? 0,
    wins: lastStatsData.wins ?? 0,
    draws: lastStatsData.draws ?? 0,
    losses: lastStatsData.losses ?? 0,
    win_rate: lastStatsData.win_rate ?? 0,
    draw_rate: lastStatsData.draw_rate ?? 0,
    loss_rate: lastStatsData.loss_rate ?? 0,
    goals_scored: lastStatsData.goals?.scored ?? 0,
    goals_conceded: lastStatsData.goals?.conceded ?? 0,
    avg_scored: lastStatsData.goals?.avg_scored ?? 0,
    avg_conceded: lastStatsData.goals?.avg_conceded ?? 0,
    over_under: lastStatsData.over_under ?? null,
    form: lastStatsData.form ?? null,
    vs: lastStatsData.vs_rank_groups ?? null
  };
}

/* =========================
   APPLY VIEW
========================= */
function applyView(mode) {
  currentView = mode;
  const v = getViewData(mode);
  if (!v) return;

  // main counts
  byId("stats-played").textContent = v.matches ?? 0;
  byId("stats-wins").textContent = v.wins ?? 0;
  byId("stats-draws").textContent = v.draws ?? 0;
  byId("stats-losses").textContent = v.losses ?? 0;

  // percentages
  byId("stats-win-rate").textContent = pct(v.win_rate);
  byId("stats-draw-rate").textContent = pct(v.draw_rate);
  byId("stats-loss-rate").textContent = pct(v.loss_rate);

  // bars (use rates)
  setBarWidth(byId("bar-wins"), v.win_rate);
  setBarWidth(byId("bar-draws"), v.draw_rate);
  setBarWidth(byId("bar-losses"), v.loss_rate);

  // goals
  byId("stats-goals-for").textContent = v.goals_scored ?? 0;
  byId("stats-goals-against").textContent = v.goals_conceded ?? 0;

  // advanced: goals & averages
  byId("stats-adv-gf").textContent = v.goals_scored ?? 0;
  byId("stats-adv-ga").textContent = v.goals_conceded ?? 0;
  byId("stats-adv-gd").textContent = (v.goals_scored - v.goals_conceded) || 0;
  byId("stats-avg-gf").textContent = Number(v.avg_scored || 0).toFixed(2);
  byId("stats-avg-ga").textContent = Number(v.avg_conceded || 0).toFixed(2);

  // advanced: over/under + btts (per view)
  const ou = v.over_under || { over_25: 0, under_25: 0, btts: 0, over_25_rate: 0, under_25_rate: 0, btts_rate: 0 };
  byId("stats-over25").textContent = ou.over_25 ?? 0;
  byId("stats-under25").textContent = ou.under_25 ?? 0;
  byId("stats-btts").textContent = ou.btts ?? 0;
  byId("stats-over25-rate").textContent = pct(ou.over_25_rate);
  byId("stats-under25-rate").textContent = pct(ou.under_25_rate);
  byId("stats-btts-rate").textContent = pct(ou.btts_rate);

  // advanced: form (per view)
  const f = v.form || {};
  const f5 = f.last_5 || {};
  const f10 = f.last_10 || {};
  byId("stats-form5-record").textContent = f5.record || "—";
  byId("stats-form5-points").textContent = f5.points ?? 0;
  byId("stats-form5-gf").textContent = f5.goals_scored ?? 0;
  byId("stats-form5-ga").textContent = f5.goals_conceded ?? 0;

  byId("stats-form10-record").textContent = f10.record || "—";
  byId("stats-form10-points").textContent = f10.points ?? 0;
  byId("stats-form10-gf").textContent = f10.goals_scored ?? 0;
  byId("stats-form10-ga").textContent = f10.goals_conceded ?? 0;

  // vs top/bottom (per view)
  const vsAll = lastStatsData.vs_rank_groups || {};
  const topN = vsAll.top_n ?? 6;
  const bottomN = vsAll.bottom_n ?? 5;
  byId("vs-top-n").textContent = topN;
  byId("vs-bottom-n").textContent = bottomN;

  if (vsAll.total_teams) {
    byId("vs-total-teams").textContent = vsAll.total_teams;
    byId("vs-bottom-threshold").textContent = vsAll.bottom_threshold_rank;
  } else {
    byId("vs-total-teams").textContent = "-";
    byId("vs-bottom-threshold").textContent = "-";
  }

  const vs = v.vs || {};
  const vsTop = vs.vs_top || { wins: 0, draws: 0, losses: 0, win_rate: 0, matches: 0 };
  const vsBottom = vs.vs_bottom || { wins: 0, draws: 0, losses: 0, win_rate: 0, matches: 0 };

  byId("vs-top-wdl").textContent = `${vsTop.wins}W-${vsTop.draws}D-${vsTop.losses}L`;
  byId("vs-bottom-wdl").textContent = `${vsBottom.wins}W-${vsBottom.draws}D-${vsBottom.losses}L`;
  byId("vs-top-winrate").textContent = pct(vsTop.win_rate);
  byId("vs-bottom-winrate").textContent = pct(vsBottom.win_rate);
  byId("vs-top-matches").textContent = vsTop.matches ?? 0;
  byId("vs-bottom-matches").textContent = vsBottom.matches ?? 0;

  setActiveSegment(mode);
}

/* =========================
   SEGMENT UI
========================= */
function setActiveSegment(mode) {
  ["view-overall", "view-home", "view-away"].forEach(id =>
    byId(id)?.classList.remove("active")
  );
  byId(`view-${mode}`)?.classList.add("active");
}

/* =========================
   STATS REQUEST
========================= */
async function requestStats() {
  const team = byId("stats-team").value.trim();
  if (!team) return;

  const params = new URLSearchParams();
  params.set("team", team);

  const comp = byId("stats-competition").value;
  const season = byId("stats-season").value;

  if (comp) params.set("competition", comp);
  if (season) params.set("season", season);

  const res = await fetch(`${API_BASE_URL}/api/stats?${params.toString()}`);
  lastStatsData = await res.json();

  byId("stats-team-name").textContent = lastStatsData.team;
  byId("stats-competition-name").textContent = lastStatsData.competition;
  byId("stats-season-name").textContent = lastStatsData.season;

  applyView("overall");
}

/* =========================
   TEAMS DROPDOWN
========================= */
async function loadTeams() {
  const teamSelect = byId("stats-team");
  const comp = byId("stats-competition")?.value || "";
  const season = byId("stats-season")?.value || "";

  if (!teamSelect) return;

  teamSelect.innerHTML = `<option value="">Seleziona squadra</option>`;
  teamSelect.disabled = true;

  try {
    const params = new URLSearchParams();
    if (comp) params.set("competition", comp);
    if (season) params.set("season", season);

    const url = params.toString()
      ? `${API_BASE_URL}/api/teams?${params.toString()}`
      : `${API_BASE_URL}/api/teams`;

    const res = await fetch(url);
    if (!res.ok) throw new Error("Errore caricamento squadre");

    const data = await res.json();
    const teams = data.teams || [];

    teams.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      teamSelect.appendChild(opt);
    });

    teamSelect.disabled = false;
  } catch (err) {
    console.error(err);
  }
}

/* =========================
   INIT
========================= */
document.addEventListener("DOMContentLoaded", () => {
  // stats
  byId("stats-button")?.addEventListener("click", requestStats);
  byId("view-overall")?.addEventListener("click", () => applyView("overall"));
  byId("view-home")?.addEventListener("click", () => applyView("home"));
  byId("view-away")?.addEventListener("click", () => applyView("away"));

  byId("stats-competition")?.addEventListener("change", loadTeams);
  byId("stats-season")?.addEventListener("change", loadTeams);

  loadTeams();

  // year
  const y = new Date().getFullYear();
  const yearEl = byId("year");
  if (yearEl) yearEl.textContent = y;
});

// Scroll fluido da "Inizia ora"
document.getElementById("start-button")?.addEventListener("click", () => {
  document.getElementById("overview")?.scrollIntoView({
    behavior: "smooth"
  });
});
