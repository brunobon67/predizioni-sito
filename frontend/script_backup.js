const API_BASE_URL = "http://127.0.0.1:5000";

let allMatches = [];

// ===== HERO: pulsante "Inizia ora" =====
function setupCtaScroll() {
  const ctaButton = document.getElementById("cta-button");
  const overviewSection = document.getElementById("overview");

  if (ctaButton && overviewSection) {
    ctaButton.addEventListener("click", () => {
      overviewSection.scrollIntoView({ behavior: "smooth" });
    });
  }
}

// ===== NAVBAR: evidenzia sezione attiva =====
function setupNavActive() {
  const navLinks = document.querySelectorAll(".nav-link");
  const sections = document.querySelectorAll("section[id]");

  function setActiveLink() {
    let currentId = "";

    sections.forEach((section) => {
      const rect = section.getBoundingClientRect();
      const offsetTop = rect.top;
      if (
        offsetTop <= window.innerHeight * 0.4 &&
        offsetTop >= -section.offsetHeight * 0.6
      ) {
        currentId = section.id;
      }
    });

    navLinks.forEach((link) => {
      const hrefId = link.getAttribute("href").replace("#", "");
      if (hrefId === currentId) {
        link.classList.add("active");
      } else {
        link.classList.remove("active");
      }
    });
  }

  window.addEventListener("scroll", setActiveLink);
  window.addEventListener("load", setActiveLink);
}

// ===== FOOTER: anno corrente =====
function setupYear() {
  const yearSpan = document.getElementById("year");
  if (yearSpan) {
    yearSpan.textContent = new Date().getFullYear();
  }
}

// ===== PREVISIONI: carica partite dal backend =====
async function loadMatches() {
  const competitionSelect = document.getElementById("pred-competition");
  const matchSelect = document.getElementById("pred-match");
  const messageEl = document.getElementById("prediction-message");

  if (!competitionSelect || !matchSelect) return;

  try {
    const res = await fetch(`${API_BASE_URL}/api/matches`);
    if (!res.ok) {
      throw new Error("Errore dal server");
    }

    const data = await res.json();
    allMatches = data.matches || [];

    const competitions = Array.from(
      new Set(allMatches.map((m) => m.competition))
    );

    competitionSelect.innerHTML = `<option value="">Tutte le competizioni</option>`;
    competitions.forEach((comp) => {
      const opt = document.createElement("option");
      opt.value = comp;
      opt.textContent = comp;
      competitionSelect.appendChild(opt);
    });

    populateMatchSelect();

    if (messageEl) {
      messageEl.textContent = "Partite caricate dal backend.";
      messageEl.className = "prediction-message success";
    }
  } catch (err) {
    console.error("Errore nel caricamento delle partite:", err);
    if (messageEl) {
      messageEl.textContent =
        "Impossibile caricare le partite. Verifica che il backend sia avviato.";
      messageEl.className = "prediction-message error";
    }
  }
}

// Filtra e popola il select partite in base alla competizione scelta
function populateMatchSelect() {
  const competitionSelect = document.getElementById("pred-competition");
  const matchSelect = document.getElementById("pred-match");

  if (!competitionSelect || !matchSelect) return;

  const selectedCompetition = competitionSelect.value;

  let filtered = allMatches;
  if (selectedCompetition) {
    filtered = allMatches.filter(
      (m) => m.competition === selectedCompetition
    );
  }

  matchSelect.innerHTML = `<option value="">Seleziona partita</option>`;

  filtered.forEach((match) => {
    const opt = document.createElement("option");
    opt.value = match.id;
    opt.textContent = `${match.competition} - ${match.home_team} vs ${match.away_team} (${match.date})`;
    matchSelect.appendChild(opt);
  });
}

// ===== PREVISIONI: invia richiesta al backend /api/predict =====
async function requestPrediction() {
  const matchSelect = document.getElementById("pred-match");
  const modelSelect = document.getElementById("pred-model");
  const messageEl = document.getElementById("prediction-message");

  const probHomeEl = document.getElementById("prob-home");
  const probDrawEl = document.getElementById("prob-draw");
  const probAwayEl = document.getElementById("prob-away");
  const explanationEl = document.getElementById("prediction-explanation-text");

  if (
    !matchSelect ||
    !modelSelect ||
    !probHomeEl ||
    !probDrawEl ||
    !probAwayEl ||
    !explanationEl
  ) {
    return;
  }

  const matchId = parseInt(matchSelect.value, 10);
  const model = modelSelect.value;

  if (!matchId || !model) {
    if (messageEl) {
      messageEl.textContent =
        "Seleziona una partita e un modello prima di calcolare le previsioni.";
      messageEl.className = "prediction-message error";
    }
    return;
  }

  try {
    if (messageEl) {
      messageEl.textContent = "Calcolo in corso...";
      messageEl.className = "prediction-message";
    }

    const res = await fetch(`${API_BASE_URL}/api/predict`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        match_id: matchId,
        model: model,
      }),
    });

    if (!res.ok) {
      throw new Error("Errore nella risposta del server");
    }

    const data = await res.json();
    const probs = data.probabilities;

    probHomeEl.textContent = (probs.home_win * 100).toFixed(1) + " %";
    probDrawEl.textContent = (probs.draw * 100).toFixed(1) + " %";
    probAwayEl.textContent = (probs.away_win * 100).toFixed(1) + " %";

    explanationEl.textContent = probs.explanation || "Nessuna spiegazione disponibile.";

    if (messageEl) {
      messageEl.textContent = "Previsione aggiornata dal modello.";
      messageEl.className = "prediction-message success";
    }
  } catch (err) {
    console.error("Errore durante la previsione:", err);
    if (messageEl) {
      messageEl.textContent =
        "Errore nel calcolo della previsione. Controlla che il backend sia attivo.";
      messageEl.className = "prediction-message error";
    }
  }
}

// ===== STATISTICHE: richiesta al backend /api/stats =====
async function requestStats() {
  const teamInput = document.getElementById("stats-team");
  const competitionSelect = document.getElementById("stats-competition");
  const messageEl = document.getElementById("stats-message");

  const teamNameEl = document.getElementById("stats-team-name");
  const compNameEl = document.getElementById("stats-competition-name");
  const playedEl = document.getElementById("stats-played");
  const winsEl = document.getElementById("stats-wins");
  const drawsEl = document.getElementById("stats-draws");
  const lossesEl = document.getElementById("stats-losses");
  const gfEl = document.getElementById("stats-goals-for");
  const gaEl = document.getElementById("stats-goals-against");
  const homeRateEl = document.getElementById("stats-home-rate");
  const awayRateEl = document.getElementById("stats-away-rate");
  // Nuovi elementi per statistiche avanzate
  const advGfEl = document.getElementById("stats-adv-gf");
  const advGaEl = document.getElementById("stats-adv-ga");
  const advGdEl = document.getElementById("stats-adv-gd");
  const avgGfEl = document.getElementById("stats-avg-gf");
  const avgGaEl = document.getElementById("stats-avg-ga");

  const over25El = document.getElementById("stats-over25");
  const under25El = document.getElementById("stats-under25");
  const over25RateEl = document.getElementById("stats-over25-rate");
  const under25RateEl = document.getElementById("stats-under25-rate");
  const bttsEl = document.getElementById("stats-btts");
  const bttsRateEl = document.getElementById("stats-btts-rate");

  const homeMatchesEl = document.getElementById("stats-home-matches");
  const homeGfEl = document.getElementById("stats-home-gf");
  const homeGaEl = document.getElementById("stats-home-ga");
  const homeAvgGfEl = document.getElementById("stats-home-avg-gf");
  const homeAvgGaEl = document.getElementById("stats-home-avg-ga");

  const awayMatchesEl = document.getElementById("stats-away-matches");
  const awayGfEl = document.getElementById("stats-away-gf");
  const awayGaEl = document.getElementById("stats-away-ga");
  const awayAvgGfEl = document.getElementById("stats-away-avg-gf");
  const awayAvgGaEl = document.getElementById("stats-away-avg-ga");

  const form5RecordEl = document.getElementById("stats-form5-record");
  const form5PointsEl = document.getElementById("stats-form5-points");
  const form5GfEl = document.getElementById("stats-form5-gf");
  const form5GaEl = document.getElementById("stats-form5-ga");

  const form10RecordEl = document.getElementById("stats-form10-record");
  const form10PointsEl = document.getElementById("stats-form10-points");
  const form10GfEl = document.getElementById("stats-form10-gf");
  const form10GaEl = document.getElementById("stats-form10-ga");

  const seasonSelect = document.getElementById("stats-season");
  const seasonNameEl = document.getElementById("stats-season-name");
  
  const vsTopNEl = document.getElementById("vs-top-n");
  const vsBottomNEl = document.getElementById("vs-bottom-n");
  const vsTopWdlEl = document.getElementById("vs-top-wdl");
  const vsBottomWdlEl = document.getElementById("vs-bottom-wdl");
  const vsTopWinrateEl = document.getElementById("vs-top-winrate");
  const vsBottomWinrateEl = document.getElementById("vs-bottom-winrate");
  const vsTopMatchesEl = document.getElementById("vs-top-matches");
  const vsBottomMatchesEl = document.getElementById("vs-bottom-matches");
  const vsBottomThresholdEl = document.getElementById("vs-bottom-threshold");
  const vsTotalTeamsEl = document.getElementById("vs-total-teams");


  if (!teamInput || !competitionSelect) return;

  const team = teamInput.value.trim();
  const competition = competitionSelect.value;
  const season = seasonSelect ? seasonSelect.value : "";


  if (!team) {
    if (messageEl) {
      messageEl.textContent = "Inserisci il nome di una squadra.";
      messageEl.className = "prediction-message error";
    }
    return;
  }

  try {
    if (messageEl) {
      messageEl.textContent = "Calcolo statistiche...";
      messageEl.className = "prediction-message";
    }

    const params = new URLSearchParams();
    params.set("team", team);
    if (competition) {
      params.set("competition", competition);
    }
    if (season) {
      params.set("season", season);
    }

    const res = await fetch(`${API_BASE_URL}/api/stats?` + params.toString());
    if (!res.ok) {
      throw new Error("Errore dal server");
    }

    const data = await res.json();

    // ===== VS TOP/BOTTOM (rank al momento) =====
    const vs = data.vs_rank_groups || null;

    if (vs && vs.vs_top && vs.vs_bottom) {
      if (vsTopNEl) vsTopNEl.textContent = vs.top_n ?? 6;
      if (vsBottomNEl) vsBottomNEl.textContent = vs.bottom_n ?? 5;

      const top = vs.vs_top;
      const bottom = vs.vs_bottom;

      if (vsTopWdlEl) vsTopWdlEl.textContent = `${top.wins}W-${top.draws}D-${top.losses}L`;
      if (vsBottomWdlEl) vsBottomWdlEl.textContent = `${bottom.wins}W-${bottom.draws}D-${bottom.losses}L`;

      if (vsTopWinrateEl) vsTopWinrateEl.textContent = ((top.win_rate || 0) * 100).toFixed(1) + "%";
      if (vsBottomWinrateEl) vsBottomWinrateEl.textContent = ((bottom.win_rate || 0) * 100).toFixed(1) + "%";

      if (vsTopMatchesEl) vsTopMatchesEl.textContent = top.matches ?? 0;
      if (vsBottomMatchesEl) vsBottomMatchesEl.textContent = bottom.matches ?? 0;

      if (vsBottomThresholdEl) vsBottomThresholdEl.textContent = vs.bottom_threshold_rank ?? "-";
      if (vsTotalTeamsEl) vsTotalTeamsEl.textContent = vs.total_teams ?? "-";
    } else {
      if (vsTopWdlEl) vsTopWdlEl.textContent = "—";
      if (vsBottomWdlEl) vsBottomWdlEl.textContent = "—";
      if (vsTopWinrateEl) vsTopWinrateEl.textContent = "—";
      if (vsBottomWinrateEl) vsBottomWinrateEl.textContent = "—";
      if (vsTopMatchesEl) vsTopMatchesEl.textContent = "—";
      if (vsBottomMatchesEl) vsBottomMatchesEl.textContent = "—";
      if (vsBottomThresholdEl) vsBottomThresholdEl.textContent = "—";
      if (vsTotalTeamsEl) vsTotalTeamsEl.textContent = "—";
    }


    if (teamNameEl) teamNameEl.textContent = data.team || team;
    if (compNameEl)
      compNameEl.textContent =
        data.competition || (competition ? competition : "Tutte");
    if (seasonNameEl)
      seasonNameEl.textContent =
        data.season || (season ? season : "Tutte");


    if (playedEl) playedEl.textContent = data.matches_played ?? 0;
    if (winsEl) winsEl.textContent = data.wins ?? 0;
    if (drawsEl) drawsEl.textContent = data.draws ?? 0;
    if (lossesEl) lossesEl.textContent = data.losses ?? 0;
    if (gfEl) gfEl.textContent = data.goals_scored ?? 0;
    if (gaEl) gaEl.textContent = data.goals_conceded ?? 0;

    if (homeRateEl)
      homeRateEl.textContent = ((data.home_win_rate || 0) * 100).toFixed(1) + " %";
    if (awayRateEl)
      awayRateEl.textContent = ((data.away_win_rate || 0) * 100).toFixed(1) + " %";

    // ---- Sezioni avanzate ----
    const goals = data.goals || {};
    const overUnder = data.over_under || {};
    const home = data.home || {};
    const away = data.away || {};
    const form = data.form || {};
    const last5 = form.last_5 || {};
    const last10 = form.last_10 || {};

    // Goal & medie
    if (advGfEl) advGfEl.textContent = goals.scored ?? data.goals_scored ?? 0;
    if (advGaEl) advGaEl.textContent = goals.conceded ?? data.goals_conceded ?? 0;
    if (advGdEl)
      advGdEl.textContent =
        goals.goal_difference ??
        (data.goals_scored || 0) - (data.goals_conceded || 0);

    if (avgGfEl)
      avgGfEl.textContent = (goals.avg_scored || 0).toFixed
        ? goals.avg_scored.toFixed(2)
        : Number(goals.avg_scored || 0).toFixed(2);
    if (avgGaEl)
      avgGaEl.textContent = (goals.avg_conceded || 0).toFixed
        ? goals.avg_conceded.toFixed(2)
        : Number(goals.avg_conceded || 0).toFixed(2);

    // Over / Under / BTTS
    if (over25El) over25El.textContent = overUnder.over_25 ?? 0;
    if (under25El) under25El.textContent = overUnder.under_25 ?? 0;
    if (bttsEl) bttsEl.textContent = overUnder.btts ?? 0;

    if (over25RateEl)
      over25RateEl.textContent =
        ((overUnder.over_25_rate || 0) * 100).toFixed(1) + "%";
    if (under25RateEl)
      under25RateEl.textContent =
        ((overUnder.under_25_rate || 0) * 100).toFixed(1) + "%";
    if (bttsRateEl)
      bttsRateEl.textContent =
        ((overUnder.btts_rate || 0) * 100).toFixed(1) + "%";

    // Casa / trasferta
    if (homeMatchesEl) homeMatchesEl.textContent = home.matches ?? 0;
    if (homeGfEl) homeGfEl.textContent = home.goals_scored ?? 0;
    if (homeGaEl) homeGaEl.textContent = home.goals_conceded ?? 0;
    if (homeAvgGfEl)
      homeAvgGfEl.textContent = (home.avg_scored || 0).toFixed
        ? home.avg_scored.toFixed(2)
        : Number(home.avg_scored || 0).toFixed(2);
    if (homeAvgGaEl)
      homeAvgGaEl.textContent = (home.avg_conceded || 0).toFixed
        ? home.avg_conceded.toFixed(2)
        : Number(home.avg_conceded || 0).toFixed(2);

    if (awayMatchesEl) awayMatchesEl.textContent = away.matches ?? 0;
    if (awayGfEl) awayGfEl.textContent = away.goals_scored ?? 0;
    if (awayGaEl) awayGaEl.textContent = away.goals_conceded ?? 0;
    if (awayAvgGfEl)
      awayAvgGfEl.textContent = (away.avg_scored || 0).toFixed
        ? away.avg_scored.toFixed(2)
        : Number(away.avg_scored || 0).toFixed(2);
    if (awayAvgGaEl)
      awayAvgGaEl.textContent = (away.avg_conceded || 0).toFixed
        ? away.avg_conceded.toFixed(2)
        : Number(away.avg_conceded || 0).toFixed(2);

    // Forma recente
    if (form5RecordEl) form5RecordEl.textContent = last5.record || "0W-0D-0L";
    if (form5PointsEl) form5PointsEl.textContent = last5.points ?? 0;
    if (form5GfEl) form5GfEl.textContent = last5.goals_scored ?? 0;
    if (form5GaEl) form5GaEl.textContent = last5.goals_conceded ?? 0;

    if (form10RecordEl) form10RecordEl.textContent = last10.record || "0W-0D-0L";
    if (form10PointsEl) form10PointsEl.textContent = last10.points ?? 0;
    if (form10GfEl) form10GfEl.textContent = last10.goals_scored ?? 0;
    if (form10GaEl) form10GaEl.textContent = last10.goals_conceded ?? 0;


    if (messageEl) {
      messageEl.textContent =
        data.matches_played > 0
          ? "Statistiche aggiornate dalle partite passate."
          : "Nessuna partita trovata per i filtri selezionati.";
      messageEl.className =
        "prediction-message " + (data.matches_played > 0 ? "success" : "error");
    }
  } catch (err) {
    console.error("Errore durante il calcolo statistiche:", err);
    if (messageEl) {
      messageEl.textContent =
        "Errore nel calcolo delle statistiche. Controlla che il backend sia attivo.";
      messageEl.className = "prediction-message error";
    }
  }
}

// ===== CARICA ELENCO SQUADRE DAL BACKEND =====
// ===== CARICA ELENCO SQUADRE DAL BACKEND, FILTRATE PER COMPETIZIONE + STAGIONE =====
async function loadTeams() {
  const teamInput = document.getElementById("stats-team");
  const messageEl = document.getElementById("stats-message");
  const compSelect = document.getElementById("stats-competition");
  const seasonSelect = document.getElementById("stats-season");

  if (!teamInput) return;

  try {
    const params = new URLSearchParams();

    // Filtra per competizione selezionata (se presente)
    if (compSelect && compSelect.value) {
      params.set("competition", compSelect.value);
    }

    // Filtra per stagione selezionata (se presente)
    if (seasonSelect && seasonSelect.value) {
      params.set("season", seasonSelect.value);
    }

    const url =
      params.toString().length > 0
        ? `${API_BASE_URL}/api/teams?` + params.toString()
        : `${API_BASE_URL}/api/teams`;

    const res = await fetch(url);
    if (!res.ok) {
      throw new Error("Errore dal server");
    }

    const data = await res.json();

    let datalist = document.getElementById("teams-datalist");
    if (!datalist) {
      datalist = document.createElement("datalist");
      datalist.id = "teams-datalist";
      document.body.appendChild(datalist);
      teamInput.setAttribute("list", "teams-datalist");
    }

    datalist.innerHTML = "";
    (data.teams || []).forEach((team) => {
      const option = document.createElement("option");
      option.value = team;
      datalist.appendChild(option);
    });

    // reset del campo squadra quando cambia il filtro
    teamInput.value = "";

    console.log(
      "Squadre caricate per filtri:",
      compSelect ? compSelect.value : "(tutte)",
      seasonSelect ? seasonSelect.value : "(tutte)",
      "→",
      (data.teams || []).length
    );
  } catch (err) {
    console.error("Errore caricamento squadre", err);
    if (messageEl) {
      messageEl.textContent = "Impossibile caricare l’elenco squadre.";
      messageEl.className = "prediction-message error";
    }
  }
}


// ===== Inizializzazione =====
document.addEventListener("DOMContentLoaded", () => {
  setupCtaScroll();
  setupNavActive();
  setupYear();

  // Previsioni
  const competitionSelect = document.getElementById("pred-competition");
  const predictButton = document.getElementById("predict-button");

  if (competitionSelect) {
    competitionSelect.addEventListener("change", populateMatchSelect);
  }

  if (predictButton) {
    predictButton.addEventListener("click", requestPrediction);
  }

  // Statistiche
  const statsButton = document.getElementById("stats-button");
  const statsCompSelect = document.getElementById("stats-competition");
  const statsSeasonSelect = document.getElementById("stats-season");

  if (statsButton) {
    statsButton.addEventListener("click", requestStats);
  }

  // Quando cambia competizione o stagione → ricarica l'elenco squadre
  if (statsCompSelect) {
    statsCompSelect.addEventListener("change", loadTeams);
  }
  if (statsSeasonSelect) {
    statsSeasonSelect.addEventListener("change", loadTeams);
  }

  // Carica dati dal backend
  loadMatches();   // per Previsioni
  loadTeams();     // primo caricamento per Statistiche (con filtri iniziali)

});
