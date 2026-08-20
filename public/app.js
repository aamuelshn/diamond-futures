const $ = (id) => document.getElementById(id);
const state = { result: null, chartPoints: [], duel: [], quickSearch: false };

const els = {
  search: $("playerSearch"), matches: $("matches"), forecast: $("forecast"),
  loading: $("loadingPanel"), rerun: $("rerunBtn"), toast: $("toast"),
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}

function number(value, digits = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return parsed.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function pct(value) { return `${number(value, 1)}%`; }
function cap(value) { return String(value || "").replace(/^./, (first) => first.toUpperCase()); }

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({ detail: "The server returned an unexpected response." }));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

let toastTimer;
function toast(message, error = false) {
  clearTimeout(toastTimer);
  els.toast.textContent = message;
  els.toast.className = error ? "toast error" : "toast";
  els.toast.hidden = false;
  toastTimer = setTimeout(() => { els.toast.hidden = true; }, 4200);
}

function setLoading(active, title = "Building 5,000 futures…", detail = "Reading recent form, Statcast traits, and historical age transitions.") {
  els.loading.hidden = !active;
  $("loadingTitle").textContent = title;
  $("loadingDetail").textContent = detail;
  if (active && !state.result) els.forecast.hidden = true;
  document.body.classList.toggle("is-loading", active);
}

async function searchPlayers(autoSelect = false) {
  const query = els.search.value.trim();
  if (query.length < 2) return toast("Enter at least two letters.", true);
  els.matches.hidden = false;
  els.matches.innerHTML = `<div class="match-loading"><span></span> Searching active MLB players…</div>`;
  try {
    const data = await jsonFetch(`/api/search?q=${encodeURIComponent(query)}`);
    renderMatches(data.matches || []);
    if (autoSelect && data.matches?.length) loadSimulation(data.matches[0].player_id, "auto");
  } catch (error) {
    els.matches.innerHTML = `<div class="match-empty">${escapeHtml(error.message)}</div>`;
  }
}

function renderMatches(matches) {
  if (!matches.length) {
    els.matches.innerHTML = `<div class="match-empty">No active MLB players found. Try a fuller name.</div>`;
    return;
  }
  els.matches.innerHTML = matches.map((player) => {
    const details = [player.team, player.position, player.birth_date ? `Born ${player.birth_date.slice(0, 4)}` : ""].filter(Boolean).join(" · ");
    const initials = player.full_name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("");
    return `<button class="match" type="button" data-player-id="${player.player_id}">
      <span class="match-avatar">${escapeHtml(initials)}</span>
      <span><strong>${escapeHtml(player.full_name)}</strong><small>${escapeHtml(details)}</small></span>
      <b>SIMULATE <i>→</i></b>
    </button>`;
  }).join("");
  els.matches.querySelectorAll(".match").forEach((button) => button.addEventListener("click", () => loadSimulation(button.dataset.playerId, "auto")));
}

function sliderAdjustments() {
  return {
    skill: Number($("skillSlider").value),
    availability: Number($("availabilitySlider").value),
    longevity: Number($("longevitySlider").value),
    environment: Number($("environmentSlider").value),
  };
}

function adjustmentQuery() {
  const params = new URLSearchParams(sliderAdjustments());
  params.set("simulations", "5000");
  return params;
}

async function loadSimulation(playerId, role = "auto") {
  els.matches.hidden = true;
  setLoading(true, "Reading the player…", "Joining MLB history, Statcast traits, and cross-source identity records.");
  try {
    const params = adjustmentQuery();
    params.set("player_id", playerId);
    params.set("role", role);
    const data = await jsonFetch(`/api/simulate?${params}`);
    loadResult(data, true);
    toast(`${data.model.simulations.toLocaleString()} futures complete for ${data.player.full_name}.`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    setLoading(false);
  }
}

async function loadDemo() {
  setLoading(true, "Opening a sample future…", "Using a clearly labeled synthetic five-tool center fielder.");
  try {
    const data = await jsonFetch(`/api/demo-simulation?${adjustmentQuery()}`);
    loadResult(data, false);
    toast("Sample player loaded. Move the sliders and rerun the future.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    setLoading(false);
  }
}

async function rerun(role = state.result?.role) {
  if (!state.result) return;
  els.rerun.disabled = true;
  els.rerun.querySelector("span").textContent = "Running new futures…";
  try {
    const payload = {
      player: state.result.player, history: state.result.history, statcast: state.result.statcast,
      role, adjustments: sliderAdjustments(), simulations: 5000,
      sources: state.result.sources, fangraphs: state.result.fangraphs,
    };
    const data = await jsonFetch("/api/resimulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    loadResult(data, true);
    toast("The multiverse has been rerun with your assumptions.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    els.rerun.disabled = false;
    els.rerun.querySelector("span").textContent = "Run 5,000 new futures";
  }
}

function loadResult(data, updateUrl) {
  state.result = data;
  els.forecast.hidden = false;
  renderPlayer();
  renderSummary();
  renderTrajectory();
  renderSkills();
  renderPaths();
  renderMilestones();
  renderComparables();
  renderDrivers();
  renderSeasonTable();
  renderSources();
  renderBacktest();
  renderRoleSwitch();
  renderDuel();
  updateSliderOutputs();
  if (updateUrl && !data.player.demo) updateAddress();
  requestAnimationFrame(() => els.forecast.scrollIntoView({ behavior: "smooth", block: "start" }));
}

function updateAddress() {
  const url = new URL(window.location.href);
  url.search = "";
  url.searchParams.set("player", state.result.player.player_id);
  url.searchParams.set("role", state.result.role);
  Object.entries(sliderAdjustments()).forEach(([key, value]) => { if (value) url.searchParams.set(key, value); });
  history.replaceState({}, "", url);
}

function initials(name) { return String(name || "DF").split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase(); }

function renderPlayer() {
  const { player, role, confidence } = state.result;
  $("playerName").textContent = player.full_name;
  $("playerMeta").textContent = [player.team, player.position, `Age ${player.age}`, role === "pitcher" ? `${player.throws || "?"}HP` : `${player.bats || "?"} bats`].filter(Boolean).join(" · ");
  $("sourceEyebrow").innerHTML = `<span>02</span> ${player.demo ? "SYNTHETIC MODEL DEMO" : "LIVE CAREER OUTLOOK"}`;
  $("playerInitials").textContent = initials(player.full_name);
  const img = $("playerHeadshot");
  if (player.demo) {
    img.hidden = true;
  } else {
    img.hidden = false;
    img.alt = `${player.full_name} headshot`;
    img.src = `https://img.mlbstatic.com/mlb-photos/image/upload/w_300,q_auto:best/v1/people/${player.player_id}/headshot/67/current`;
    img.onerror = () => { img.hidden = true; };
  }
  $("confidenceValue").textContent = `${confidence.label} · ${confidence.score}/100`;
  $("confidenceBar").style.width = `${confidence.score}%`;
}

function summarySpec() {
  const result = state.result;
  const s = result.summary;
  if (result.role === "hitter") {
    return [
      ["CAREER HOME RUNS", s.career_home_runs, "HR", "The middle 80% of futures"],
      ["CAREER HITS", s.career_hits, "H", "Including current totals"],
      ["VALUE STILL AHEAD", s.remaining_value, "CV", "WAR-like internal value"],
      ["ACTIVE IN 3 YEARS", { p50: s.three_year_survival }, "%", `${number(s.cliff_risk, 1)}% early-cliff risk`],
    ];
  }
  return [
    ["CAREER STRIKEOUTS", s.career_strikeouts, "K", "The middle 80% of futures"],
    ["CAREER WINS", s.career_wins, "W", "Including current totals"],
    ["VALUE STILL AHEAD", s.remaining_value, "CV", "WAR-like internal value"],
    ["ACTIVE IN 3 YEARS", { p50: s.three_year_survival }, "%", `${number(s.cliff_risk, 1)}% early-cliff risk`],
  ];
}

function renderSummary() {
  const result = state.result;
  const count = result.role === "hitter" ? result.summary.career_home_runs : result.summary.career_strikeouts;
  const noun = result.role === "hitter" ? "home runs" : "strikeouts";
  $("forecastHeadline").textContent = `The median path reaches ${number(count.p50)} career ${noun} and lasts through ${number(result.summary.retirement_year.p50)}.`;
  $("summaryCards").innerHTML = summarySpec().map(([label, values, unit, note], index) => {
    const hasRange = values.p10 !== undefined && values.p90 !== undefined;
    return `<article class="summary-card ${index === 0 ? "featured" : ""}">
      <span>${label}</span><strong>${number(values.p50, unit === "CV" ? 1 : unit === "%" ? 1 : 0)}<small>${unit}</small></strong>
      ${hasRange ? `<div class="mini-range"><i></i><b style="left:${rangePosition(values)}%"></b></div><p>${number(values.p10)} low · ${number(values.p90)} high</p>` : `<p>${escapeHtml(note)}</p>`}
      ${hasRange ? `<em>${escapeHtml(note)}</em>` : ""}
    </article>`;
  }).join("");
}

function rangePosition(values) {
  const span = Number(values.p90) - Number(values.p10);
  return span > 0 ? Math.max(5, Math.min(95, (Number(values.p50) - Number(values.p10)) / span * 100)) : 50;
}

function renderRoleSwitch() {
  const roles = state.result.available_roles || [];
  const box = $("roleSwitch");
  box.hidden = roles.length < 2;
  box.innerHTML = roles.map((role) => `<button type="button" data-role="${role}" class="${role === state.result.role ? "active" : ""}">${cap(role)}</button>`).join("");
  box.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
    if (button.dataset.role !== state.result.role) {
      if (state.result.player.demo) rerun(button.dataset.role);
      else loadSimulation(state.result.player.player_id, button.dataset.role);
    }
  }));
}

function chartSeries() {
  const metric = $("chartMetric").value;
  const role = state.result.role;
  const labelMap = {
    value: ["Annual CURVE Value", "CV"], workload: [`Projected ${state.result.metric_labels.workload}`, state.result.metric_labels.workload],
    rate: [`Projected ${state.result.metric_labels.rate}`, state.result.metric_labels.rate],
    count: [role === "hitter" ? "Projected home runs" : "Projected strikeouts", role === "hitter" ? "HR" : "K"],
  };
  const key = metric === "count" ? (role === "hitter" ? "home_runs" : "strikeouts") : metric;
  return { metric, key, title: labelMap[metric][0], unit: labelMap[metric][1], rows: state.result.seasons.map((row) => ({ season: row.season, age: row.age, active: row.active_probability, ...row[key] })) };
}

function renderTrajectory() {
  const series = chartSeries();
  $("chartTitle").textContent = series.title;
  const canvas = $("trajectoryChart");
  const wrap = canvas.parentElement;
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(420, wrap.clientWidth);
  const height = width < 650 ? 330 : 410;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);
  const pad = { left: 54, right: 22, top: 26, bottom: 44 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const lows = series.rows.map((row) => Number(row.p10));
  const highs = series.rows.map((row) => Number(row.p90));
  let min = series.metric === "rate" ? Math.min(...lows) : 0;
  let max = Math.max(...highs, 1);
  if (series.metric === "rate") { const room = Math.max(0.05, (max - min) * 0.12); min -= room; max += room; }
  else max *= 1.10;
  const x = (index) => pad.left + (series.rows.length === 1 ? 0 : index / (series.rows.length - 1) * plotW);
  const y = (value) => pad.top + (max - value) / (max - min || 1) * plotH;

  ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) {
    const value = min + (max - min) * (4 - i) / 4;
    const yy = pad.top + plotH * i / 4;
    ctx.strokeStyle = "rgba(241,236,216,.12)";
    ctx.beginPath(); ctx.moveTo(pad.left, yy); ctx.lineTo(width - pad.right, yy); ctx.stroke();
    ctx.fillStyle = "rgba(241,236,216,.55)";
    ctx.textAlign = "right";
    ctx.fillText(number(value, series.metric === "rate" ? 2 : 0), pad.left - 10, yy);
  }
  series.rows.forEach((row, index) => {
    if (index % Math.max(1, Math.ceil(series.rows.length / 7)) === 0 || index === series.rows.length - 1) {
      ctx.fillStyle = "rgba(241,236,216,.52)"; ctx.textAlign = "center"; ctx.fillText(String(row.season), x(index), height - 19);
    }
  });

  const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
  gradient.addColorStop(0, "rgba(184,255,100,.32)");
  gradient.addColorStop(1, "rgba(184,255,100,.035)");
  ctx.beginPath();
  series.rows.forEach((row, index) => { const xx = x(index), yy = y(row.p90); index ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); });
  [...series.rows].reverse().forEach((row, reverseIndex) => { const index = series.rows.length - 1 - reverseIndex; ctx.lineTo(x(index), y(row.p10)); });
  ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();

  ctx.beginPath();
  series.rows.forEach((row, index) => { const xx = x(index), yy = y(row.p50); index ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); });
  ctx.strokeStyle = "#b8ff64"; ctx.lineWidth = 3; ctx.lineJoin = "round"; ctx.stroke();
  state.chartPoints = series.rows.map((row, index) => ({ x: x(index), y: y(row.p50), row, unit: series.unit, title: series.title }));
  state.chartLayout = { width, height, pad, series };
}

function showChartTooltip(event) {
  if (!state.chartPoints.length) return;
  const canvas = $("trajectoryChart");
  const rect = canvas.getBoundingClientRect();
  const mouseX = event.clientX - rect.left;
  const point = state.chartPoints.reduce((best, candidate) => Math.abs(candidate.x - mouseX) < Math.abs(best.x - mouseX) ? candidate : best);
  const tip = $("chartTooltip");
  tip.innerHTML = `<b>${point.row.season} · age ${point.row.age}</b><strong>${number(point.row.p50, point.unit === "ERA" ? 2 : 1)} ${point.unit}</strong><span>${number(point.row.p10, 1)}–${number(point.row.p90, 1)} range</span><small>${pct(point.row.active)} active</small>`;
  tip.style.left = `${Math.max(8, Math.min(rect.width - 176, point.x - 78))}px`;
  tip.style.top = `${Math.max(8, point.y - 108)}px`;
  tip.hidden = false;
}

function renderSkills() {
  $("skillBars").innerHTML = state.result.skills.map((skill) => `<div class="skill-row"><span>${escapeHtml(skill.label)}</span><div><i style="width:${skill.grade}%"></i><b style="left:${skill.grade}%"></b></div><strong>${skill.grade}</strong></div>`).join("");
}

function renderPaths() {
  const r = state.result;
  const key = r.role === "hitter" ? "career_home_runs" : "career_strikeouts";
  const unit = r.role === "hitter" ? "HR" : "K";
  const paths = [
    ["10TH", "Tough landing", "p10", "The short, low-output branch"],
    ["50TH", "Median future", "p50", "The center of the distribution"],
    ["90TH", "Long prime", "p90", "Health and skill both hold"],
  ];
  $("pathCards").innerHTML = paths.map(([rank, title, percentile, note]) => `<article class="path-card ${percentile}"><span>${rank}</span><h4>${title}</h4><strong>${number(r.summary[key][percentile])}<small>${unit}</small></strong><p>${number(r.summary.career_value[percentile], 1)} CV · through ${number(r.summary.retirement_year[percentile])}</p><em>${note}</em></article>`).join("");
}

function renderMilestones() {
  $("milestoneGrid").innerHTML = state.result.milestones.map((item, index) => {
    const probability = Math.max(0, Math.min(100, Number(item.probability)));
    return `<article class="milestone-card"><div class="prob-ring" style="--prob:${probability * 3.6}deg"><span>${number(probability, probability < 10 ? 1 : 0)}<small>%</small></span></div><div><span>LEGACY MARK ${String(index + 1).padStart(2, "0")}</span><h3>${escapeHtml(item.label)}</h3><p>Current model total: ${number(item.current, item.unit === "CV" ? 1 : 0)}${item.unit ? ` ${item.unit}` : ""}</p></div></article>`;
  }).join("");
}

function renderComparables() {
  $("compsGrid").innerHTML = state.result.comparables.map((comp, index) => {
    const career = state.result.role === "hitter" ? `${number(comp.career_hr)} HR · ${number(comp.career_hits)} H` : `${number(comp.career_so)} K · ${number(comp.career_wins)} W`;
    return `<article class="comp-card"><div class="comp-rank">${String(index + 1).padStart(2, "0")}</div><div class="comp-score"><b>${comp.similarity}</b><span>% MATCH</span></div><h3>${escapeHtml(comp.name)}</h3><p>Age ${comp.age} · ${comp.season}</p><strong>${escapeHtml(comp.signature)}</strong><footer><span>${career}</span><span>${comp.next_seasons} seasons followed</span></footer></article>`;
  }).join("");
}

function renderDrivers() {
  $("driversList").innerHTML = state.result.drivers.map((driver) => `<div class="driver"><i class="${driver.impact}">${driver.impact === "positive" ? "↗" : driver.impact === "negative" ? "↘" : "→"}</i><div><strong>${escapeHtml(driver.label)}</strong><p>${escapeHtml(driver.detail)}</p></div></div>`).join("");
}

function renderSeasonTable() {
  const hitter = state.result.role === "hitter";
  $("seasonTableHead").innerHTML = `<tr><th>Season</th><th>Age</th><th>Track</th><th>${hitter ? "PA" : "IP"}</th><th>${hitter ? "HR" : "K"}</th><th>${hitter ? "OPS" : "ERA"}</th><th>CV</th></tr>`;
  const actual = (state.result.role_history || []).slice(-5).map((row) => `<tr><td>${row.season}</td><td>${row.age || "—"}</td><td><span class="actual-tag">ACTUAL</span></td><td>${number(hitter ? row.pa : row.ip, hitter ? 0 : 1)}</td><td>${number(hitter ? row.hr : row.so)}</td><td>${number(hitter ? row.ops : row.era, hitter ? 3 : 2)}</td><td>—</td></tr>`);
  const projected = state.result.seasons.slice(0, 8).map((row) => `<tr><td>${row.season}</td><td>${row.age}</td><td><span class="projected-tag">P50</span></td><td>${number(row.workload.p50, hitter ? 0 : 1)}</td><td>${number((hitter ? row.home_runs : row.strikeouts).p50)}</td><td>${number(row.rate.p50, hitter ? 3 : 2)}</td><td>${number(row.value.p50, 1)}</td></tr>`);
  $("seasonTableBody").innerHTML = [...actual, ...projected].join("");
}

function renderSources() {
  $("sourceRows").innerHTML = (state.result.sources || []).map((source) => `<div class="source-row"><span>${escapeHtml(source.name)}</span><p>${escapeHtml(source.detail)}</p><b class="status-${source.status}"><i></i>${escapeHtml(source.status)}</b></div>`).join("");
}

function renderBacktest() {
  const all = state.result.model?.backtest;
  if (!all) return;
  const score = all[state.result.role];
  $("backtestDescription").textContent = `${number(score.player_seasons)} ${state.result.role} age-seasons from ${all.holdout}, held out from the aging-curve training window.`;
  $("backtestStats").innerHTML = [
    ["ONE-YEAR ERROR", score.mae, score.one_year_metric, `Naive baseline ${score.naive_mae}`],
    ["80% BAND COVERAGE", score.interval_80_coverage, "%", "Target: 80%"],
    ["SURVIVAL BRIER", score.survival_brier, "", "Lower is better"],
  ].map(([label, value, unit, note]) => `<div><span>${label}</span><strong>${number(value, unit === "%" ? 1 : score.one_year_metric === "OPS" ? 3 : 2)}<small>${unit}</small></strong><p>${note}</p></div>`).join("");
}

function updateSliderOutputs() {
  const configs = [
    ["skillSlider", "skillOutput", "Baseline"], ["availabilitySlider", "availabilityOutput", "Baseline"],
    ["longevitySlider", "longevityOutput", "Baseline"], ["environmentSlider", "environmentOutput", "Neutral"],
  ];
  configs.forEach(([sliderId, outputId, zero]) => {
    const value = Number($(sliderId).value);
    $(outputId).textContent = value === 0 ? zero : `${value > 0 ? "+" : ""}${value}%`;
  });
}

function applyPreset(name) {
  const presets = { breakout: [8, 5, 4, 2], healthy: [1, 18, 12, 0], rough: [-8, -18, -12, -3], baseline: [0, 0, 0, 0] };
  const [skill, availability, longevity, environment] = presets[name] || presets.baseline;
  $("skillSlider").value = skill; $("availabilitySlider").value = availability;
  $("longevitySlider").value = longevity; $("environmentSlider").value = environment;
  updateSliderOutputs();
}

function pinToDuel() {
  if (!state.result) return;
  const snapshot = {
    key: `${state.result.player.player_id}-${state.result.role}`, player: state.result.player,
    role: state.result.role, summary: state.result.summary,
  };
  state.duel = state.duel.filter((item) => item.key !== snapshot.key);
  state.duel.push(snapshot);
  state.duel = state.duel.slice(-2);
  saveDuel(); renderDuel();
  toast(state.duel.length === 1 ? "Pinned. Load another player and pin them to start a duel." : "Career duel ready.");
  if (state.duel.length === 2) $("duel").scrollIntoView({ behavior: "smooth" });
}

function saveDuel() { try { localStorage.setItem("diamond-futures-duel", JSON.stringify(state.duel)); } catch (_) {} }
function loadDuel() { try { state.duel = JSON.parse(localStorage.getItem("diamond-futures-duel") || "[]").slice(-2); } catch (_) { state.duel = []; } }

function renderDuel() {
  const section = $("duel");
  section.hidden = state.duel.length < 2;
  if (state.duel.length < 2) return;
  $("duelGrid").innerHTML = state.duel.map((item, index) => {
    const hitter = item.role === "hitter";
    const count = hitter ? item.summary.career_home_runs : item.summary.career_strikeouts;
    return `<article class="duel-card"><span>PLAYER ${index + 1}</span><h3>${escapeHtml(item.player.full_name)}</h3><p>${cap(item.role)} · age ${item.player.age}</p><div><strong>${number(count.p50)}<small>${hitter ? "HR" : "K"}</small></strong><span>Median career total</span></div><dl><dt>Career value</dt><dd>${number(item.summary.career_value.p50, 1)} CV</dd><dt>Years left</dt><dd>${number(item.summary.remaining_seasons.p50)}</dd><dt>3-year survival</dt><dd>${pct(item.summary.three_year_survival)}</dd></dl></article>`;
  }).join(`<div class="versus">VS</div>`);
}

async function shareForecast() {
  updateAddress();
  const r = state.result;
  const count = r.role === "hitter" ? `${number(r.summary.career_home_runs.p50)} HR` : `${number(r.summary.career_strikeouts.p50)} K`;
  const shareData = { title: `${r.player.full_name} — Diamond Futures`, text: `${r.player.full_name}'s median simulated career: ${count}, ${number(r.summary.career_value.p50, 1)} CURVE Value.`, url: window.location.href };
  try {
    if (navigator.share) await navigator.share(shareData);
    else { await navigator.clipboard.writeText(`${shareData.text} ${shareData.url}`); toast("Forecast link copied."); }
  } catch (error) { if (error.name !== "AbortError") toast("Could not share this forecast.", true); }
}

function downloadCsv() {
  const hitter = state.result.role === "hitter";
  const headers = ["season", "age", "p10_workload", "p50_workload", "p90_workload", `p50_${hitter ? "home_runs" : "strikeouts"}`, `p50_${hitter ? "ops" : "era"}`, "p50_curve_value", "active_probability"];
  const rows = state.result.seasons.map((row) => [row.season, row.age, row.workload.p10, row.workload.p50, row.workload.p90, (hitter ? row.home_runs : row.strikeouts).p50, row.rate.p50, row.value.p50, row.active_probability]);
  const csv = [headers, ...rows].map((row) => row.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${state.result.player.full_name.replace(/[^a-z0-9]+/gi, "_")}_${state.result.role}_curve.csv`;
  link.click(); URL.revokeObjectURL(link.href);
}

$("searchBtn").addEventListener("click", () => searchPlayers(false));
els.search.addEventListener("keydown", (event) => { if (event.key === "Enter") searchPlayers(false); });
$("demoBtn").addEventListener("click", loadDemo);
document.querySelectorAll("[data-player]").forEach((button) => button.addEventListener("click", () => { els.search.value = button.dataset.player; searchPlayers(true); }));
$("rerunBtn").addEventListener("click", () => rerun());
$("resetLab").addEventListener("click", () => applyPreset("baseline"));
document.querySelectorAll("[data-preset]").forEach((button) => button.addEventListener("click", () => applyPreset(button.dataset.preset)));
["skillSlider", "availabilitySlider", "longevitySlider", "environmentSlider"].forEach((id) => $(id).addEventListener("input", updateSliderOutputs));
$("chartMetric").addEventListener("change", renderTrajectory);
$("trajectoryChart").addEventListener("mousemove", showChartTooltip);
$("trajectoryChart").addEventListener("mouseleave", () => { $("chartTooltip").hidden = true; });
$("pinBtn").addEventListener("click", pinToDuel);
$("shareBtn").addEventListener("click", shareForecast);
$("downloadBtn").addEventListener("click", downloadCsv);
$("clearDuel").addEventListener("click", () => { state.duel = []; saveDuel(); renderDuel(); toast("Career duel cleared."); });

let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (state.result) renderTrajectory(); }, 120); });

async function boot() {
  loadDuel();
  const params = new URLSearchParams(window.location.search);
  const playerId = params.get("player");
  ["skill", "availability", "longevity", "environment"].forEach((key) => {
    if (params.has(key) && $(`${key}Slider`)) $(`${key}Slider`).value = params.get(key);
  });
  updateSliderOutputs();
  if (playerId) await loadSimulation(playerId, params.get("role") || "auto");
  else await loadDemo();
}

boot();
