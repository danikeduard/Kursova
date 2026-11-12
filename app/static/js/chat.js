import { api, conversations, messageFeedback, settings } from "./api.js";
import { setupSidebar, setupSidebarChrome } from "./sidebar.js";
import { renderMarkdown } from "./markdown.js";
import { setTheme } from "./theme.js";
import { toast } from "./toast.js";
import { setupShortcuts } from "./shortcuts.js";
import { closeMenu, openMenu } from "./menu.js";

const state = { conversationId: Number(document.body.dataset.conversationId) || null, query: "", archived: false, streaming: false };
const messages = document.querySelector("#messages");
const messageArea = document.querySelector(".message-area");
const empty = document.querySelector("#empty-state");
const suggestions = document.querySelector("#suggestions");
const composerWrap = document.querySelector(".composer-wrap");
const input = document.querySelector("#chat-input");
const form = document.querySelector("#chat-form");
const send = form.querySelector(".send-button");
const sidebar = document.querySelector("#sidebar");
const title = document.querySelector("#conversation-title");
const titleText = title.querySelector(".conversation-title-text");
const titleChevron = title.querySelector(".conversation-title-chevron");
const userDisplayName = document.querySelector("#user-display-name");
const userAvatar = document.querySelector("#user-avatar");
const maxInputLines = 8;

function renderLevels(levels = {}) {
  const chips = document.querySelector("#level-chips");
  const previous = Object.fromEntries([...chips.children].map((chip) => chip.dataset.skill && [chip.dataset.skill, chip.textContent]));
  chips.replaceChildren();
  [["grammar", "Grammar"], ["vocab", "Vocab"], ["writing", "Writing"]].forEach(([skill, name]) => {
    const level = levels[skill] || "—";
    const chip = document.createElement("span");
    chip.className = "level-chip";
    chip.dataset.skill = skill;
    chip.title = `${name}: ${level}`;
    chip.textContent = `${name} ${level}`;
    chips.append(chip);
    if (previous[skill] && previous[skill] !== chip.textContent) {
      chip.classList.add("chip-updated");
      chip.addEventListener("animationend", () => chip.classList.remove("chip-updated"), { once: true });
    }
  });
}
function addMessage(role, content, id = "", feedback = null, isNew = false) {
  const article = document.createElement("article"); article.className = `message-item ${role}${isNew ? " is-new" : ""}`; if (id) article.dataset.id = id;
  if (isNew) article.addEventListener("animationend", () => article.classList.remove("is-new"), { once: true });
  const avatar = document.createElement("span"); avatar.className = "message-avatar"; avatar.textContent = role === "assistant" ? "✦" : document.querySelector(".avatar").textContent;
  const body = document.createElement("div"); body.className = "message-body"; body.innerHTML = role === "assistant" ? renderMarkdown(content) : ""; if (role === "user") body.textContent = content;
  const actions = document.createElement("div"); actions.className = "message-actions";
  if (role === "assistant" && id) {
    [["up", "Helpful"], ["down", "Not helpful"]].forEach(([rating, label]) => {
      const button = document.createElement("button"); button.type = "button"; button.textContent = rating === "up" ? "👍" : "👎"; button.title = label;
      button.classList.toggle("selected", feedback === rating);
      button.addEventListener("click", async () => {
        try { await messageFeedback(id, rating); actions.querySelectorAll("button").forEach((item) => item.classList.remove("selected")); button.classList.add("selected"); toast("Feedback saved"); }
        catch (error) { toast(error.message); }
      });
      actions.append(button);
    });
  }
  article.append(avatar, body);
  if (role === "assistant" && id) article.append(actions);
  messages.append(article); return body;
}
function addTypingMessage() {
  const body = addMessage("assistant", "", "", null, true);
  body.replaceChildren();
  const indicator = document.createElement("span");
  indicator.className = "typing-indicator";
  indicator.setAttribute("aria-label", "Tutor is typing");
  for (let index = 0; index < 3; index += 1) indicator.append(document.createElement("i"));
  body.append(indicator);
  return { article: body.closest(".message-item"), body };
}
async function loadConversation(id) {
  state.conversationId = id; history.pushState({}, "", `/chat/${id}`);
  const data = await conversations.messages(id); messages.replaceChildren(); setEmptyChat(data.messages.length === 0); data.messages.forEach((message) => addMessage(message.role, message.content, message.id, message.feedback)); messageArea.scrollTop = messageArea.scrollHeight; sidebarController.load();
  const item = document.querySelector(`.conversation-row[data-id="${id}"] .conversation-link`); if (item) titleText.textContent = item.textContent;
}
async function newChat() { const data = await conversations.create(); await loadConversation(data.conversation.id); }
async function submitMessage(event, { skipAssessment = false } = {}) {
  event?.preventDefault(); const content = input.value.trim(); if (!content || state.streaming) return;
  if (!state.conversationId) { const data = await conversations.create(); await loadConversation(data.conversation.id); }
  setEmptyChat(false);
  state.streaming = true; send.textContent = "■"; send.classList.add("stop"); addMessage("user", content, "", null, true); const typing = addTypingMessage(); input.value = ""; updateCounter();
  try {
    const data = await api("/api/chat", { method: "POST", body: JSON.stringify({ content, conversation_id: state.conversationId, skip_assessment: skipAssessment }) });
    typing.body.replaceChildren();
    typing.body.innerHTML = renderMarkdown(data.reply);
    if (data.conversation_title) {
      titleText.textContent = data.conversation_title;
    }
    if (data.assessment_status === "failed") {
      toast("Your reply was sent, but the evaluator failed. Your progress was not updated.");
    } else if (data.assessment_status === "not_english") {
      toast("Your reply was sent, but it was not assessed as English.");
    } else if (data.assessment_status === "low_confidence") {
      toast("Your reply was assessed, but there was not enough evidence to update your ratings.");
    }
    data.level_changed?.forEach((change) => {
      const message = `Your ${change.skill} level is now ${change.label}`;
      const action = Number.isInteger(change.change_id)
        ? { label: "Why?", onClick: () => showLevelChange(change.change_id) }
        : null;
      toast(message, action);
    });
    sidebarController.load();
  } catch (error) {
    typing.article.classList.add("is-failed");
    typing.body.replaceChildren();
    typing.body.textContent = error.message;
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "retry-button";
    retry.textContent = "Retry";
    retry.addEventListener("click", () => {
      typing.article.remove();
      input.value = content;
      updateCounter();
      submitMessage();
    });
    typing.body.append(document.createElement("br"), retry);
  } finally { state.streaming = false; send.textContent = "↑"; send.classList.remove("stop"); }
}
async function showLevelChange(id) {
  try {
    const data = await api(`/api/level-changes/${id}`);
    const explanation = data.explanation;
    document.querySelector("#level-change-heading").textContent = `${data.skill}: ${data.label}`;
    document.querySelector("#level-change-summary").textContent = explanation.summary;
    const reasons = document.querySelector("#level-change-reasons");
    reasons.replaceChildren();
    explanation.reasons.forEach((reason) => {
      const item = document.createElement("li");
      item.textContent = reason.quote ? `${reason.text} “${reason.quote}”` : reason.text;
      reasons.append(item);
    });
    document.querySelector("#level-change-caveat").textContent = explanation.caveat;
    document.querySelector("#modal-backdrop").hidden = false;
    document.querySelector("#level-change-modal").hidden = false;
  } catch (error) { toast(error.message); }
}
function autoResize(textarea) {
  const styles = getComputedStyle(textarea);
  const lineHeight = parseFloat(styles.lineHeight);
  const verticalPadding = parseFloat(styles.paddingTop) + parseFloat(styles.paddingBottom);
  const maxHeight = lineHeight * maxInputLines + verticalPadding;
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
  textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
}
function updateCounter() {
  document.querySelector("#char-count").textContent = `${input.value.length} / 4000`;
  autoResize(input);
}
function renderSuggestions() {
  const items = [["Introduce yourself", "Tell me about yourself in English."], ["Describe your day", "Describe your typical day and routine."], ["Practice vocabulary", "Help me practice useful everyday vocabulary."], ["Discuss a topic", "Let's discuss an interesting news topic."]];
  const target = document.querySelector("#suggestions");
  items.forEach(([label, prompt]) => {
    const card = document.createElement("button");
    card.className = "suggestion-card"; card.type = "button"; card.textContent = label;
    card.addEventListener("click", () => { input.value = prompt; updateCounter(); submitMessage(undefined, { skipAssessment: true }); });
    target.append(card);
  });
}

const sidebarController = setupSidebar(state, loadConversation);
const { conversationSearch } = setupSidebarChrome();
composerWrap.after(suggestions);
function setEmptyChat(isEmpty) {
  document.body.classList.toggle("chat-empty", isEmpty);
  empty.hidden = !isEmpty;
  suggestions.hidden = !isEmpty;
}
renderSuggestions();
setEmptyChat(!state.conversationId);
sidebarController.load();
if (state.conversationId) loadConversation(state.conversationId).catch((error) => toast(error.message));
input.addEventListener("input", updateCounter);
input.addEventListener("input", () => {
  const commandMenu = document.querySelector("#command-menu");
  if (input.value.trimStart().startsWith("/") && !state.streaming) {
    if (commandMenu.hidden) openMenu(input, commandMenu);
  } else closeMenu(false);
});
input.addEventListener("paste", () => requestAnimationFrame(() => autoResize(input)));
input.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submitMessage(); } });
window.addEventListener("resize", () => autoResize(input));
form.addEventListener("submit", submitMessage);
updateCounter();
document.querySelector("#new-chat").addEventListener("click", newChat);
document.querySelector("#settings-open").addEventListener("click", () => { document.querySelector("#modal-backdrop").hidden = false; document.querySelector("#settings-modal").hidden = false; });
document.querySelectorAll(".modal-close").forEach((button) => button.addEventListener("click", () => { document.querySelector("#modal-backdrop").hidden = true; document.querySelectorAll("[role=dialog]").forEach((dialog) => { dialog.hidden = true; }); }));
document.querySelector("#theme-select").addEventListener("change", (event) => setTheme(event.target.value));
async function loadSettings() {
  try {
    const value = await settings.get();
    document.querySelector("#theme-select").value = value.theme;
    document.documentElement.lang = "en";
    document.querySelector("#reply-length").value = value.reply_length;
    document.querySelector("#emoji-toggle").checked = value.use_emojis;
    document.querySelector("#preferred-name").value = value.preferred_name || "";
    updatePreferredName(value.preferred_name);
    setTheme(value.theme);
  } catch (error) { toast(error.message); }
}
["theme-select", "reply-length", "emoji-toggle", "preferred-name"].forEach((id) => {
  document.querySelector(`#${id}`).addEventListener("change", async () => {
    try {
      await settings.update({
        theme: document.querySelector("#theme-select").value,
        reply_length: document.querySelector("#reply-length").value,
        use_emojis: document.querySelector("#emoji-toggle").checked,
        preferred_name: document.querySelector("#preferred-name").value,
      });
      updatePreferredName(document.querySelector("#preferred-name").value);
      if (id === "theme-select") setTheme(document.querySelector("#theme-select").value);
      toast("Settings saved");
    } catch (error) { toast(error.message); }
  });
});
function updatePreferredName(value) {
  const name = value?.trim() || "Learner";
  userDisplayName.textContent = name;
  userAvatar.textContent = name.charAt(0).toUpperCase();
}
document.querySelectorAll(".settings-tabs button").forEach((button) => button.addEventListener("click", () => { document.querySelectorAll(".settings-tabs button").forEach((item) => item.classList.toggle("active", item === button)); document.querySelectorAll(".settings-panel").forEach((panel) => { panel.hidden = panel.dataset.panel !== button.dataset.tab; }); }));
function startTitleEdit() {
  if (!state.conversationId || title.querySelector("input")) return;
  const previousTitle = titleText.textContent;
  const editor = document.createElement("input");
  editor.className = "conversation-title-editor";
  editor.type = "text";
  editor.maxLength = 200;
  editor.value = previousTitle;
  editor.setAttribute("aria-label", "Chat title");
  titleText.replaceWith(editor);
  titleChevron.hidden = true;
  editor.focus();
  editor.select();

  let finished = false;
  let saving = false;
  const finish = (value) => {
    if (finished) return;
    finished = true;
    titleText.textContent = value;
    editor.replaceWith(titleText);
    titleChevron.hidden = false;
  };
  const save = async () => {
    if (finished || saving) return;
    const value = editor.value.trim();
    if (!value || value === previousTitle) { finish(previousTitle); return; }
    saving = true;
    editor.disabled = true;
    try {
      const result = await conversations.update(state.conversationId, { title: value });
      finish(result.conversation.title);
      sidebarController.load();
    } catch (error) {
      finish(previousTitle);
      toast(error.message);
    }
  };
  editor.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); save(); }
    if (event.key === "Escape") { event.preventDefault(); finish(previousTitle); }
  });
  editor.addEventListener("blur", save, { once: true });
}
title.addEventListener("click", startTitleEdit);
title.addEventListener("keydown", (event) => {
  if (event.target === title && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    startTitleEdit();
  }
});
setupShortcuts({ search: document.querySelector("#conversation-search"), newChat, toggleSidebar: () => document.body.classList.toggle("sidebar-collapsed"), close: () => { document.body.classList.remove("sidebar-open"); document.querySelector("#modal-backdrop").hidden = true; } });
loadSettings();
if (new URLSearchParams(window.location.search).get("settings") === "1") {
  document.querySelector("#modal-backdrop").hidden = false;
  document.querySelector("#settings-modal").hidden = false;
  history.replaceState({}, "", window.location.pathname);
}
