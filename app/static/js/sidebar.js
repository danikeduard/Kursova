import { conversations } from "./api.js";
import { closeMenu, openMenu } from "./menu.js";
import { toast } from "./toast.js";

export function setupSidebarChrome() {
  const conversationSearch = document.querySelector("#conversation-search");
  const searchBox = conversationSearch.closest(".search-box");
  const sidebarHead = document.querySelector(".sidebar-head");
  const sidebarToggle = document.querySelector("#sidebar-toggle");
  const searchButton = document.createElement("button");
  searchButton.className = "topbar-icon-button search-toggle";
  searchButton.type = "button";
  searchButton.setAttribute("aria-label", "Search chats");
  searchButton.title = "Search chats";
  searchButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.8"></circle><path d="m16 16 5 5"></path></svg>';
  searchButton.addEventListener("click", () => {
    document.body.classList.add("search-open");
    if (window.innerWidth < 768) document.body.classList.add("sidebar-open");
    else document.body.classList.remove("sidebar-collapsed");
    window.setTimeout(() => conversationSearch.focus(), 180);
  });
  sidebarToggle.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"></rect><path d="M9 4v16"></path></svg>';
  sidebarToggle.classList.add("topbar-icon-button", "sidebar-toggle-button");
  sidebarToggle.setAttribute("aria-label", "Toggle sidebar");
  sidebarToggle.title = "Toggle sidebar";
  conversationSearch.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      conversationSearch.value = "";
      conversationSearch.dispatchEvent(new Event("input", { bubbles: true }));
      document.body.classList.remove("search-open");
      conversationSearch.blur();
    }
  });
  sidebarHead.append(searchButton, searchBox, sidebarToggle);
  sidebarToggle.addEventListener("click", () => {
    if (window.innerWidth < 768) document.body.classList.toggle("sidebar-open");
    else document.body.classList.toggle("sidebar-collapsed");
  });
  document.querySelector("#mobile-menu").addEventListener("click", () => document.body.classList.add("sidebar-open"));
  document.querySelector("#mobile-scrim").addEventListener("click", () => document.body.classList.remove("sidebar-open"));
  const userMenu = document.querySelector("#user-menu");
  const userPopover = document.querySelector("#user-popover");
  userMenu.addEventListener("click", () => openMenu(userMenu, userPopover));
  return { conversationSearch };
}

export function setupSidebar(state, renderChat) {
  const list = document.querySelector("#conversation-list");
  let searchTimer;
  async function load() {
    try {
      const data = await conversations.list(state.query || "", state.archived);
      list.replaceChildren();
      if (!data.items.length) {
        const empty = document.createElement("p");
        empty.className = "list-empty";
        empty.textContent = state.query ? "No chats found" : "No conversations yet";
        list.append(empty);
        return;
      }
      let group;
      data.items.forEach((item) => {
        const elapsed = (Date.now() - new Date(item.updated_at).getTime()) / 86400000;
        const label = item.pinned ? "Pinned" : elapsed < 1 ? "Today" : elapsed < 2 ? "Yesterday" : elapsed < 7 ? "Previous 7 days" : elapsed < 30 ? "Previous 30 days" : new Date(item.updated_at).toLocaleDateString(undefined, { month: "long", year: "numeric" });
        if (label !== group) { group = label; const heading = document.createElement("div"); heading.className = "list-heading"; heading.textContent = label; list.append(heading); }
        const row = document.createElement("div");
        row.className = `conversation-row${item.id === state.conversationId ? " active" : ""}`;
        row.dataset.id = item.id;
        const link = document.createElement("button");
        link.className = "conversation-link"; link.type = "button"; link.textContent = item.title; link.title = item.title;
        link.addEventListener("click", () => renderChat(item.id));
        const menu = document.createElement("button");
        menu.className = "conversation-menu"; menu.type = "button"; menu.setAttribute("aria-label", `Actions for ${item.title}`); menu.textContent = "•••";
        menu.setAttribute("aria-haspopup", "menu");
        menu.setAttribute("aria-expanded", "false");
        menu.addEventListener("click", () => openConversationMenu(menu, item));
        row.append(link, menu); list.append(row);
      });
    } catch (error) { toast(error.message); }
  }
  async function openConversationMenu(trigger, item) {
    const menu = document.createElement("div"); menu.className = "row-menu";
    const actions = [
      ["Rename", async () => {
        const title = window.prompt("Chat name", item.title);
        if (title?.trim()) await conversations.update(item.id, { title: title.trim() });
      }],
      [item.pinned ? "Unpin" : "Pin", () => conversations.update(item.id, { pinned: !item.pinned })],
      [item.archived ? "Restore" : "Archive", () => conversations.update(item.id, { archived: !item.archived })],
      ["Delete", () => conversations.remove(item.id)],
    ];
    actions.forEach(([label, action]) => { const button = document.createElement("button"); button.type = "button"; button.textContent = label; if (label === "Delete") button.className = "menu-danger"; button.addEventListener("click", async () => { closeMenu(false); await action(); await load(); }); menu.append(button); });
    openMenu(trigger, menu, { scrollEl: list });
  }
  document.querySelector("#conversation-search").addEventListener("input", (event) => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { state.query = event.target.value; load(); }, 250); });
  document.querySelector("#archive-toggle").addEventListener("click", () => { state.archived = !state.archived; load(); });
  return { load };
}
