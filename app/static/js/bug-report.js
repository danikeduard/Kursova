import { api } from "./api.js";
import { toast } from "./toast.js";
import { EASTER_EGG_NAME, EASTER_EGG_TITLE_MESSAGE, EASTER_EGG_CARD_MESSAGE } from "./easter-egg.js";

console.log(`Hello ${EASTER_EGG_NAME}`);

const button = document.querySelector("#bug-report-button");
const backdrop = document.querySelector("#bug-report-backdrop");
const panel = document.querySelector("#bug-report-panel");
const form = document.querySelector("#bug-report-form");
if (button && backdrop && panel && form) {
  const closeButton = document.querySelector("#bug-report-close");
  const success = document.querySelector("#bug-report-success");
  const successMessage = document.querySelector("#bug-success-message");
  const title = document.querySelector("#bug-title");
  const easterLine = document.querySelector("#bug-easter-line");
  const description = document.querySelector("#bug-description");
  const count = document.querySelector("#bug-description-count");
  const submit = document.querySelector("#bug-submit");
  const formError = document.querySelector("#bug-form-error");
  const descriptionError = document.querySelector("#bug-description-error");
  const draftKey = `linguapath:bug-draft:${window.bugDraftUserId}`;
  let draftTimer;
  let submitting = false;
  let clickTimes = [];
  let previousFocus = null;

  function saveDraft() {
    try {
      const draft = {
        category: form.elements.category.value,
        title: title.value.slice(0, 120),
        description: description.value.slice(0, 2000),
        includeDetails: document.querySelector("#bug-include-details").checked,
      };
      localStorage.setItem(draftKey, JSON.stringify(draft));
    } catch (_) {}
  }

  function restoreDraft() {
    try {
      const draft = JSON.parse(localStorage.getItem(draftKey) || "null");
      if (!draft || typeof draft !== "object") return;
      if ([...form.elements.category.options].some((option) => option.value === draft.category)) form.elements.category.value = draft.category;
      title.value = typeof draft.title === "string" ? draft.title.slice(0, 120) : "";
      description.value = typeof draft.description === "string" ? draft.description.slice(0, 2000) : "";
      document.querySelector("#bug-include-details").checked = draft.includeDetails !== false;
      count.textContent = `${description.value.length} / 2000`;
      easterLine.hidden = title.value.toLowerCase() !== "daihleky";
      if (!easterLine.hidden) easterLine.textContent = EASTER_EGG_TITLE_MESSAGE;
    } catch (_) {
      try { localStorage.removeItem(draftKey); } catch (_) {}
    }
  }

  function openPanel() {
    previousFocus = document.activeElement;
    restoreDraft();
    backdrop.hidden = false;
    form.hidden = false;
    success.hidden = true;
    document.body.classList.add("bug-report-open");
    window.setTimeout(() => panel.querySelector("#bug-category").focus(), 0);
  }

  function closePanel() {
    backdrop.hidden = true;
    document.body.classList.remove("bug-report-open");
    if (previousFocus instanceof HTMLElement) previousFocus.focus();
  }

  function trapFocus(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      closePanel();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...panel.querySelectorAll('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])')].filter((element) => !element.hidden);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventEvent?.(); event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  button.addEventListener("click", () => {
    const now = Date.now();
    clickTimes = clickTimes.filter((time) => now - time <= 2000);
    clickTimes.push(now);
    if (clickTimes.length === 5) {
      clickTimes = [];
      const icon = button.querySelector("img") || button.querySelector("svg");
      if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        icon.classList.remove("bug-wiggle");
        void icon.offsetWidth;
        icon.classList.add("bug-wiggle");
      }
      toast(`🐞 ${EASTER_EGG_CARD_MESSAGE}`);
      return;
    }
    if (clickTimes.length === 1) openPanel();
  });

  closeButton.addEventListener("click", closePanel);
  document.querySelector("#bug-success-close").addEventListener("click", closePanel);
  backdrop.addEventListener("mousedown", (event) => { if (event.target === backdrop) closePanel(); });
  panel.addEventListener("keydown", trapFocus);

  title.addEventListener("input", () => {
    easterLine.hidden = title.value.toLowerCase() !== "daihleky";
    easterLine.textContent = easterLine.hidden ? "" : EASTER_EGG_TITLE_MESSAGE;
  });
  description.addEventListener("input", () => {
    count.textContent = `${description.value.length} / 2000`;
  });
  form.addEventListener("input", () => {
    window.clearTimeout(draftTimer);
    draftTimer = window.setTimeout(saveDraft, 300);
  });
  form.addEventListener("change", () => {
    window.clearTimeout(draftTimer);
    draftTimer = window.setTimeout(saveDraft, 300);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitting) return;
    descriptionError.hidden = true;
    formError.hidden = true;
    if (description.value.trim().length < 10) {
      descriptionError.textContent = "Description must be at least 10 characters.";
      descriptionError.hidden = false;
      description.focus();
      return;
    }
    submitting = true;
    submit.disabled = true;
    submit.textContent = "Sending...";
    const includeDetails = document.querySelector("#bug-include-details").checked;
    const context = includeDetails ? {
      page_path: window.location.pathname,
      browser: navigator.userAgent.slice(0, 300),
      screen: `${window.screen.width}x${window.screen.height}`,
      viewport: `${window.innerWidth}x${window.innerHeight}`,
      theme: document.documentElement.dataset.theme || "dark",
      app_version: "web",
      timestamp: new Date().toISOString(),
      ...(window.location.pathname.match(/^\/chat\/(\d+)$/) ? { conversation_id: Number(window.location.pathname.match(/^\/chat\/(\d+)$/)[1]) } : {}),
    } : {};
    try {
      const result = await api("/api/bug-reports", {
        method: "POST",
        body: JSON.stringify({ category: form.elements.category.value, title: title.value, description: description.value, context }),
      });
      try { localStorage.removeItem(draftKey); } catch (_) {}
      form.reset();
      count.textContent = "0 / 2000";
      form.hidden = true;
      success.hidden = false;
      successMessage.textContent = `Thanks! Report #${result.id} received.`;
      document.querySelector("#bug-success-close").focus();
    } catch (error) {
      formError.textContent = error.message.includes("429") ? "Too many reports, please try again later." : error.message;
      formError.hidden = false;
    } finally {
      submitting = false;
      submit.disabled = false;
      submit.textContent = "Submit report";
    }
  });

  function updateBugPosition() {
    const chatComposer = document.querySelector(".composer-wrap");
    const narrow = window.innerWidth < 1100;
    let overlap = false;
    if (chatComposer) {
      const rect = chatComposer.getBoundingClientRect();
      const buttonRect = button.getBoundingClientRect();
      overlap = buttonRect.left < rect.right && buttonRect.right > rect.left && buttonRect.bottom > rect.top && buttonRect.top < rect.bottom;
    }
    document.documentElement.style.setProperty("--bug-lift", chatComposer && (narrow || overlap) ? `${Math.ceil(chatComposer.getBoundingClientRect().height)}px` : "0px");
  }
  if ("ResizeObserver" in window) {
    const composer = document.querySelector(".composer-wrap");
    if (composer) new ResizeObserver(updateBugPosition).observe(composer);
  }
  window.addEventListener("resize", updateBugPosition);
  updateBugPosition();
}
