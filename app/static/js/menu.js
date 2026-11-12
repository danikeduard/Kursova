let openState = null;

const viewportMargin = 8;

function viewportHeight() {
  return window.visualViewport?.height || window.innerHeight;
}

export function positionMenu(triggerEl, menuEl) {
  const trigger = triggerEl.getBoundingClientRect();
  const width = menuEl.offsetWidth;
  const naturalHeight = menuEl.offsetHeight;
  const viewportWidth = window.innerWidth;
  const viewportBottom = viewportHeight();
  const below = viewportBottom - trigger.bottom - viewportMargin;
  const above = trigger.top - viewportMargin;
  const fitsBelow = below >= naturalHeight;
  const fitsAbove = above >= naturalHeight;
  const useBelow = fitsBelow || (!fitsAbove && below >= above);
  const space = useBelow ? below : above;
  const constrained = !fitsBelow && !fitsAbove;
  const maxHeight = Math.max(0, space - viewportMargin);
  const height = constrained ? Math.min(naturalHeight, maxHeight) : naturalHeight;
  const top = useBelow
    ? trigger.bottom + viewportMargin
    : trigger.top - height - viewportMargin;
  const left = Math.min(
    Math.max(viewportMargin, trigger.right - width),
    Math.max(viewportMargin, viewportWidth - width - viewportMargin),
  );

  menuEl.style.maxHeight = constrained ? `${maxHeight}px` : "";
  menuEl.style.overflowY = constrained ? "auto" : "";
  menuEl.style.left = `${left}px`;
  menuEl.style.top = `${Math.max(viewportMargin, Math.min(top, viewportBottom - height - viewportMargin))}px`;
}

function focusItem(menuEl, index) {
  const items = [...menuEl.querySelectorAll('[role="menuitem"]:not([disabled])')];
  if (!items.length) return;
  items[(index + items.length) % items.length].focus();
}

function closeCurrent(restoreFocus = true) {
  if (!openState) return;
  const { menuEl, triggerEl, onClose, scrollEl, onScroll } = openState;
  menuEl.hidden = true;
  menuEl.classList.remove("menu-portal-open");
  menuEl.style.visibility = "hidden";
  scrollEl?.removeEventListener("scroll", onScroll);
  openState = null;
  onClose?.();
  if (restoreFocus && triggerEl.isConnected) triggerEl.focus();
}

export function closeMenu(restoreFocus = true) {
  closeCurrent(restoreFocus);
}

function onDocumentPointerDown(event) {
  if (!openState || openState.menuEl.contains(event.target) || openState.triggerEl.contains(event.target)) return;
  closeCurrent();
}

function onKeyDown(event) {
  if (!openState) return;
  const { menuEl } = openState;
  const items = [...menuEl.querySelectorAll('[role="menuitem"]:not([disabled])')];
  const index = items.indexOf(document.activeElement);
  if (event.key === "Escape" || event.key === "Tab") {
    event.preventDefault();
    closeCurrent();
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    focusItem(menuEl, index + 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    focusItem(menuEl, index - 1);
  } else if (event.key === "Home") {
    event.preventDefault();
    focusItem(menuEl, 0);
  } else if (event.key === "End") {
    event.preventDefault();
    focusItem(menuEl, items.length - 1);
  } else if ((event.key === "Enter" || event.key === " ") && index >= 0) {
    event.preventDefault();
    items[index].click();
  }
}

function reposition() {
  if (openState) positionMenu(openState.triggerEl, openState.menuEl);
}

["resize", "orientationchange"].forEach((eventName) => window.addEventListener(eventName, reposition));
window.visualViewport?.addEventListener("resize", reposition);
document.addEventListener("pointerdown", onDocumentPointerDown, true);
document.addEventListener("keydown", onKeyDown);

export function openMenu(triggerEl, menuEl, { onClose, scrollEl } = {}) {
  if (openState?.triggerEl === triggerEl) {
    closeCurrent();
    return;
  }
  closeCurrent(false);
  triggerEl.setAttribute("aria-haspopup", "menu");
  triggerEl.setAttribute("aria-expanded", "true");
  menuEl.setAttribute("role", "menu");
  menuEl.classList.add("menu-portal");
  menuEl.hidden = false;
  document.body.append(menuEl);
  [...menuEl.querySelectorAll("button, a")].forEach((item) => {
    item.setAttribute("role", "menuitem");
    if (!item.dataset.menuCloseBound) {
      item.dataset.menuCloseBound = "true";
      item.addEventListener("click", () => closeCurrent(false));
    }
  });
  const restore = () => {
    triggerEl.setAttribute("aria-expanded", "false");
  };
  const onScroll = () => closeCurrent(false);
  openState = { triggerEl, menuEl, onClose: () => { restore(); onClose?.(); }, scrollEl, onScroll };
  scrollEl?.addEventListener("scroll", onScroll, { once: true, passive: true });
  menuEl.style.visibility = "hidden";
  positionMenu(triggerEl, menuEl);
  menuEl.style.visibility = "";
  menuEl.classList.add("menu-portal-open");
  focusItem(menuEl, 0);
}
