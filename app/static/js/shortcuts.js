export function setupShortcuts(actions) {
  document.addEventListener("keydown", (event) => {
    const modifier = event.ctrlKey || event.metaKey;
    if (modifier && event.key.toLowerCase() === "k") { event.preventDefault(); actions.search?.focus(); }
    if (modifier && event.shiftKey && event.key.toLowerCase() === "o") { event.preventDefault(); actions.newChat?.(); }
    if (modifier && event.shiftKey && event.key.toLowerCase() === "s") { event.preventDefault(); actions.toggleSidebar?.(); }
    if (event.key === "Escape") actions.close?.();
  });
}
