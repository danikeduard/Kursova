import { api } from "./api.js";
import { setupSidebarChrome, setupSidebar } from "./sidebar.js";

setupSidebarChrome();
setupSidebar({ query: "", archived: false }, (id) => { window.location.href = `/chat/${id}`; }).load();

const filters = document.querySelector("#bug-admin-filters");
const rows = document.querySelector("#bug-admin-rows");
const pagination = document.querySelector("#bug-admin-pagination");
const summary = document.querySelector("#bug-admin-summary");
const detailBackdrop = document.querySelector("#bug-detail-backdrop");
const detailContent = document.querySelector("#bug-detail-content");
const detailForm = document.querySelector("#bug-detail-form");
let currentPage = 1;
let currentId = null;

function escapeLikeExportParams() {
  const params = new URLSearchParams(new FormData(filters));
  params.delete("q");
  const q = filters.elements.q.value;
  if (q) params.set("q", q);
  return params;
}

async function load(page = 1) {
  currentPage = page;
  const params = escapeLikeExportParams();
  params.set("page", String(page));
  try {
    const data = await api(`/api/admin/bug-reports?${params}`);
    summary.replaceChildren();
    const counts = data.counts;
    for (const [label, value] of [["Total", data.total_count], ["New", counts.new], ["In progress", counts.in_progress], ["Resolved", counts.resolved], ["Wont fix", counts.wont_fix]]) {
      const card = document.createElement("article");
      const small = document.createElement("small"); small.textContent = label;
      const strong = document.createElement("strong"); strong.textContent = String(value);
      card.append(small, strong); summary.append(card);
    }
    rows.replaceChildren();
    data.items.forEach((item) => {
      const tr = document.createElement("tr");
      const values = [
        `#${item.id}`,
        new Date(item.created_at).toLocaleDateString(),
        item.email || "—",
        item.participant_id,
        item.category,
        item.title || item.description.slice(0, 100),
        item.status.replace("_", " "),
        item.context?.page_path || "—",
      ];
      values.forEach((value) => { const td = document.createElement("td"); td.textContent = value; tr.append(td); });
      tr.style.cursor = "pointer";
      tr.addEventListener("click", () => openDetail(item.id));
      rows.append(tr);
    });
    pagination.replaceChildren();
    if (page > 1) { const previous = document.createElement("a"); previous.href = "#"; previous.textContent = "Previous"; previous.onclick = (event) => { event.preventEvent?.(); event.preventDefault(); load(page - 1); }; pagination.append(previous); }
    const label = document.createElement("span"); label.textContent = `Page ${page} of ${data.total_pages}`; pagination.append(label);
    if (page < data.total_pages) { const next = document.createElement("a"); next.href = "#"; next.textContent = "Next"; next.onclick = (event) => { event.preventDefault(); load(page + 1); }; pagination.append(next); }
    document.querySelector("#bug-export").href = `/admin/bug-reports/export.csv?${params}`;
    renderCategoryChart(data.category_counts);
  } catch (error) { rows.replaceChildren(); const tr = document.createElement("tr"); const td = document.createElement("td"); td.colSpan = 8; td.textContent = error.message; tr.append(td); rows.append(tr); }
}

function renderCategoryChart(categoryCounts) {
  const canvas = document.querySelector("#bug-category-chart");
  if (!window.Chart) return;
  const existing = Chart.getChart(canvas);
  if (existing) existing.destroy();
  new Chart(canvas, { type: "bar", data: { labels: categoryCounts.map((item) => item.category), datasets: [{ data: categoryCounts.map((item) => item.count), backgroundColor: getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, precision: 0 } } } });
}

async function openDetail(id) {
  currentId = id;
  const item = await api(`/api/admin/bug-reports/${id}`);
  detailContent.replaceChildren();
  const entries = [
    ["ID", `#${item.id}`], ["Email", item.email || "—"], ["Participant", item.participant_id],
    ["Category", item.category], ["Title", item.title || "—"], ["Description", item.description],
    ["Page path", item.context?.page_path || "—"], ["Browser", item.context?.browser || "—"],
    ["Viewport", item.context?.viewport || "—"], ["Screen", item.context?.screen || "—"],
    ["App version", item.context?.app_version || "—"],
  ];
  entries.forEach(([key, value]) => { const row = document.createElement("div"); const strong = document.createElement("strong"); strong.textContent = key; const span = document.createElement("span"); span.textContent = value; row.append(strong, span); detailContent.append(row); });
  document.querySelector("#bug-detail-status").value = item.status;
  document.querySelector("#bug-detail-note").value = item.admin_note || "";
  detailBackdrop.hidden = false;
  document.querySelector("#bug-detail-close").focus();
}

document.querySelector("#bug-detail-close").addEventListener("click", () => { detailBackdrop.hidden = true; });
detailBackdrop.addEventListener("mousedown", (event) => { if (event.target === detailBackdrop) detailBackdrop.hidden = true; });
detailForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.querySelector("#bug-detail-error");
  error.hidden = true;
  const note = document.querySelector("#bug-detail-note").value;
  if (note.length > 2000) { error.textContent = "Admin note must be 2,000 characters or fewer."; error.hidden = false; return; }
  try {
    await api(`/api/admin/bug-reports/${currentId}`, { method: "PATCH", body: JSON.stringify({ status: document.querySelector("#bug-detail-status").value, admin_note: note }) });
    detailBackdrop.hidden = true;
    load(currentPage);
  } catch (reason) { error.textContent = reason.message; error.hidden = false; }
});
filters.addEventListener("submit", (event) => { event.preventDefault(); load(1); });
load();
