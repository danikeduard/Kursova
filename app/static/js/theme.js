const root = document.documentElement;
let current = localStorage.getItem("linguapath-theme") || "dark";
function apply(theme) {
  root.dataset.theme = theme;
  root.style.colorScheme = theme === "system" ? "light dark" : theme;
}
apply(current);
export function setTheme(theme) { current = theme; localStorage.setItem("linguapath-theme", theme); apply(theme); }
