import { api } from "./api.js";
import { setupSidebar, setupSidebarChrome } from "./sidebar.js";
import { toast } from "./toast.js";

const skills = ["grammar", "vocab", "writing"];
const colors = { grammar: "#55b7c8", vocab: "#8aa7ff", writing: "#e5a56b" };
const charts = new Map();
const state = { query: "", archived: false };
const chartArea = document.querySelector("#charts");
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
})[char]);

function levelBand(value) {
  if (value < 1750) return "A1";
  if (value < 2250) return "A2";
  if (value < 2750) return "B1";
  if (value < 3250) return "B2";
  if (value < 3750) return "C1";
  return "C2";
}

const bandPlugin = {
  id: "cefrBands",
  beforeDraw(chart) {
    const { ctx, chartArea: area, scales } = chart;
    if (!area || !scales.y) return;
    const bounds = [0, 1750, 2250, 2750, 3250, 3750, 5000];
    ctx.save();
    for (let index = 0; index < 6; index += 1) {
      const top = scales.y.getPixelForValue(bounds[index + 1]);
      const bottom = scales.y.getPixelForValue(bounds[index]);
      ctx.fillStyle = index % 2 ? "rgba(255,255,255,.025)" : "rgba(255,255,255,.055)";
      ctx.fillRect(area.left, top, area.right - area.left, bottom - top);
      ctx.fillStyle = "rgba(155,155,155,.75)";
      ctx.font = "12px system-ui";
      ctx.textAlign = "right";
      ctx.fillText(["A1", "A2", "B1", "B2", "C1", "C2"][index], area.right + 42, (top + bottom) / 2 + 4);
    }
    ctx.restore();
  },
};

function renderSummary(data) {
  const summary = document.querySelector("#summary");
  summary.className = "progress-summary";
  summary.innerHTML = `
    <article class="progress-stat"><small>Verified messages</small><strong>${data.user.assessed_messages}</strong><span>Past evaluator errors: ${data.user.assessment_failures}</span></article>
    <article class="progress-stat"><small>Overall level</small><strong>${data.user.overall.label}</strong><span>${Math.round(data.user.overall.rating)} rating</span></article>
    <article class="progress-stat"><small>Self-declared</small><strong>${data.user.self_level} → ${data.user.overall.label}</strong><span>Active days: ${data.user.days_active}</span></article>
  `;
}

function chartCard(skill, data) {
  const card = document.createElement("article");
  card.className = "progress-chart-card";
  const points = data.points;
  const first = points[0]?.rating ?? data.start_rating;
  const last = points.at(-1)?.rating ?? data.start_rating;
  const lowBand = Math.max(0, Math.floor(Math.min(first, last) / 500) * 500 - 500);
  const highBand = Math.min(5000, Math.max(lowBand + 1500, Math.ceil(Math.max(first, last) / 500) * 500 + 500));
  const change = Math.round(last - first);
  card.innerHTML = `<div class="chart-card-head"><div><h2>${skill[0].toUpperCase() + skill.slice(1)}</h2><small>${data.label} · ${change >= 0 ? "+" : ""}${change} points</small></div><span class="level-badge">${data.label}</span></div>`;
  if (points.length === 0) {
    card.insertAdjacentHTML("beforeend", `<p class="chart-empty">Send a few more messages in English to see your trend.</p>`);
    return card;
  }
  const canvas = document.createElement("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", `${skill}: from ${levelBand(first)} to ${levelBand(last)} over ${points.length} messages`);
  card.append(canvas);
  charts.set(skill, new Chart(canvas, {
    type: "line",
    plugins: [bandPlugin],
    data: {
      datasets: [{
        label: skill,
        data: [{ x: 0, y: data.start_rating, pointLabel: "Start" }, ...points.map((point) => ({ x: point.n, y: point.rating, point })),
        ],
        borderColor: colors[skill],
        backgroundColor: colors[skill],
        tension: 0.2,
        borderWidth: 2,
        pointRadius: points.length <= 40 ? [4, ...points.map((point, index) => index === points.length - 1 ? 6 : point.label !== (points[index - 1]?.label || levelBand(data.start_rating)) ? 7 : 4)] : 0,
        pointBackgroundColor: [colors[skill], ...points.map((point, index) => index === points.length - 1 ? "#fff" : point.skipped ? "transparent" : colors[skill])],
        pointBorderColor: [colors[skill], ...points.map((point) => point.skipped ? "#9b9b9b" : colors[skill])],
        pointBorderWidth: [1, ...points.map((point) => point.skipped ? 2 : 1)],
      }],
    },
    options: {
      animation: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 400 },
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "nearest" },
      scales: {
        x: { type: "linear", ticks: { precision: 0 }, grid: { color: "rgba(155,155,155,.1)" } },
        y: { min: lowBand, max: highBand, grid: { color: "rgba(155,155,155,.12)" } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (item) => Boolean(item.raw.point),
          callbacks: {
            label: (context) => {
              const change = Math.round(context.raw.point.change);
              return `${change > 0 ? "+" : ""}${change} rating points`;
            },
            title: (items) => items[0]?.raw.point
              ? new Date(items[0].raw.point.ts).toLocaleDateString()
              : "",
          },
        },
      },
    },
  }));
  return card;
}

function renderData(data) {
  renderSummary(data);
  charts.forEach((chart) => chart.destroy());
  charts.clear();
  chartArea.replaceChildren(...skills.map((skill) => chartCard(skill, data.skills[skill])));
  const changes = document.querySelector("#level-changes");
  changes.innerHTML = data.level_changes.length ? data.level_changes.map((change) => `<button class="timeline-row" data-change="${change.id}"><span>${new Date(change.ts).toLocaleDateString()}</span><strong>${change.skill}: ${change.from} → ${change.to}</strong><span>Why?</span></button>`).join("") : "<p class='muted'>No level changes yet.</p>";
  const topics = document.querySelector("#weak-topics");
  topics.innerHTML = data.weak_topics.length ? data.weak_topics.map((topic) => `<div class="topic-row"><strong>${escapeHtml(topic.topic)}</strong><span>${topic.count} recent errors</span><small>${escapeHtml(topic.example_original)} → ${escapeHtml(topic.example_corrected)}</small></div>`).join("") : "<p class='muted'>No correction topics yet.</p>";
  changes.querySelectorAll("[data-change]").forEach((button) => button.addEventListener("click", () => showChange(button.dataset.change)));
}

async function load(range = "7d") {
  const error = document.querySelector("#progress-error");
  error.hidden = true;
  try { renderData(await api(`/api/progress?range=${range}`)); }
  catch (reason) { error.hidden = false; error.textContent = `${reason.message} Retry`; error.onclick = () => load(range); }
}

async function showChange(id) {
  try {
    const data = await api(`/api/level-changes/${id}`);
    document.querySelector("#progress-modal-title").textContent = `${data.skill}: ${data.label}`;
    document.querySelector("#progress-modal-summary").textContent = data.explanation.summary;
    document.querySelector("#progress-modal-reasons").replaceChildren(...data.explanation.reasons.map((reason) => { const item = document.createElement("li"); item.textContent = reason.quote ? `${reason.text} “${reason.quote}”` : reason.text; return item; }));
    document.querySelector("#progress-modal-caveat").textContent = data.explanation.caveat;
    document.querySelector("#progress-modal").hidden = false;
  } catch (reason) { toast(reason.message); }
}

setupSidebarChrome();
setupSidebar(state, (id) => { window.location.href = `/chat/${id}`; }).load();
document.querySelectorAll("[data-range]").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll("[data-range]").forEach((item) => item.classList.toggle("active", item === button));
  load(button.dataset.range);
}));
document.querySelector("#progress-modal-close").addEventListener("click", () => { document.querySelector("#progress-modal").hidden = true; });
load("7d");
