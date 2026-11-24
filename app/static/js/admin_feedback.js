import { setupSidebarChrome, setupSidebar } from "./sidebar.js";

setupSidebarChrome();
setupSidebar({ query: "", archived: false }, (id) => { window.location.href = `/chat/${id}`; }).load();

const stats = window.feedbackQuestionStats || [];
const styles = getComputedStyle(document.documentElement);
const textColor = styles.getPropertyValue("--text").trim();
const mutedColor = styles.getPropertyValue("--muted").trim();
const gridColor = styles.getPropertyValue("--border").trim();
const accent = styles.getPropertyValue("--accent").trim();

const meansCanvas = document.querySelector("#feedback-means");
const distributionCanvas = document.querySelector("#feedback-distribution");
if (window.Chart && stats.length) {
  new Chart(meansCanvas, {
    type: "bar",
    data: {
      labels: stats.map((item) => item.label),
      datasets: [{ label: "Mean", data: stats.map((item) => item.mean), backgroundColor: accent, borderRadius: 6 }]
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { min: 1, max: 5, ticks: { color: mutedColor }, grid: { color: gridColor } },
        y: { ticks: { color: textColor }, grid: { display: false } }
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (context) => `${context.raw ?? "—"} average · n=${stats[context.dataIndex].n}` } }
      }
    }
  });

  const colors = ["#8a9ba8", "#7aa7b4", "#55b7c8", "#8aa7ff", "#e5a56b"];
  new Chart(distributionCanvas, {
    type: "bar",
    data: {
      labels: stats.map((item) => item.label),
      datasets: [1, 2, 3, 4, 5].map((score, index) => ({
        label: String(score),
        data: stats.map((item) => item.distribution[index]),
        backgroundColor: colors[index],
        borderWidth: 0
      }))
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { stacked: true, ticks: { color: textColor }, grid: { display: false } },
        y: { stacked: true, beginAtZero: true, ticks: { precision: 0, color: mutedColor }, grid: { color: gridColor } }
      },
      plugins: { legend: { labels: { color: textColor } } }
    }
  });
}
