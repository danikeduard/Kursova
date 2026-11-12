export function toast(message, action = null) {
  const region = document.querySelector("#toast-region");
  if (!region) return;
  const item = document.createElement("div");
  item.className = "toast";
  item.textContent = message;
  if (action) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = action.label;
    button.addEventListener("click", action.onClick);
    item.append(button);
  }
  region.append(item);
  let timeout = window.setTimeout(() => dismiss(), 5000);
  function dismiss() {
    item.classList.add("is-leaving");
    item.addEventListener("animationend", () => item.remove(), { once: true });
  }
  item.addEventListener("mouseenter", () => window.clearTimeout(timeout));
  item.addEventListener("mouseleave", () => { timeout = window.setTimeout(dismiss, 5000); });
}
