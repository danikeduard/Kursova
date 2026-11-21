import "./theme.js";
import { setupSidebarChrome } from "./sidebar.js";

setupSidebarChrome();

const form = document.querySelector("#feedback-form");
if (form) {
  const storageKey = `linguapath:feedback-draft:${window.feedbackDraftKey}`;
  const submitButton = document.querySelector("#feedback-submit");
  const progressText = document.querySelector("#feedback-progress-text");
  const progressBar = document.querySelector("#feedback-progress-bar");
  const submitError = document.querySelector("#feedback-submit-error");
  const comment = document.querySelector("#free-text");
  const characterCount = document.querySelector("#feedback-character-count");
  const unsavedHint = document.querySelector("#feedback-unsaved-hint");
  const discardLink = document.querySelector("#feedback-discard");
  let draftTimer;

  function readAnswers() {
    const answers = {};
    form.querySelectorAll('input[type="radio"]:checked').forEach((radio) => {
      answers[radio.name] = Number(radio.value);
    });
    return answers;
  }

  function serverSnapshot() {
    return {
      answers: readAnswers(),
      comment: comment.value,
      consent: form.elements.consent_research.checked,
    };
  }

  let serverValue = serverSnapshot();

  function saveDraft() {
    const draft = { version: 1, answers: readAnswers(), comment: comment.value, consent: form.elements.consent_research.checked };
    try {
      localStorage.setItem(storageKey, JSON.stringify(draft));
    } catch (_) {}
  }

  function scheduleSave() {
    window.clearTimeout(draftTimer);
    draftTimer = window.setTimeout(saveDraft, 300);
  }

  function restoreDraft() {
    try {
      const draft = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (!draft || draft.version !== 1 || typeof draft !== "object") return false;
      for (const [name, value] of Object.entries(draft.answers || {})) {
        const radio = form.querySelector(`input[name="${name}"][value="${value}"]`);
        if (radio) radio.checked = true;
      }
      if (typeof draft.comment === "string") comment.value = draft.comment.slice(0, 1000);
      form.elements.consent_research.checked = draft.consent === true;
      const differs = JSON.stringify(serverValue) !== JSON.stringify({
        answers: readAnswers(),
        comment: comment.value,
        consent: form.elements.consent_research.checked,
      });
      if (unsavedHint && differs) unsavedHint.hidden = false;
      if (discardLink) discardLink.hidden = false;
      return differs;
    } catch (_) {
      try { localStorage.removeItem(storageKey); } catch (_) {}
      return false;
    }
  }

  function updateProgress() {
    let count = 0;
    for (let index = 1; index <= 5; index += 1) {
      if (form.querySelector(`input[name="q${index}"]:checked`)) count += 1;
    }
    progressText.textContent = `${count} / 5 answered`;
    progressBar.style.width = `${count * 20}%`;
    submitButton.disabled = count !== 5;
    characterCount.textContent = `${comment.value.length} / 1000`;
  }

  restoreDraft();
  updateProgress();
  form.addEventListener("change", () => { updateProgress(); scheduleSave(); });
  comment.addEventListener("input", () => { updateProgress(); scheduleSave(); });
  window.addEventListener("pageshow", () => { restoreDraft(); updateProgress(); });
  if (discardLink) discardLink.addEventListener("click", (event) => {
    event.preventDefault();
    try { localStorage.removeItem(storageKey); } catch (_) {}
    window.location.reload();
  });

  form.addEventListener("submit", (event) => {
    updateProgress();
    const missing = [];
    for (let index = 1; index <= 5; index += 1) {
      const name = `q${index}`;
      if (!form.querySelector(`input[name="${name}"]:checked`)) missing.push(name);
    }
    if (missing.length) {
      event.preventDefault();
      submitError.hidden = false;
      for (const name of missing) {
        const fieldset = form.querySelector(`[data-question="${name}"]`);
        fieldset.classList.add("has-error");
        fieldset.querySelector(".feedback-field-error").hidden = false;
      }
      form.querySelector(`[data-question="${missing[0]}"]`).scrollIntoView({ block: "center", behavior: "smooth" });
      form.querySelector(`[data-question="${missing[0]}"] input`).focus();
      return;
    }
    submitError.hidden = true;
    submitButton.disabled = true;
    submitButton.textContent = "Saving...";
  });

  form.querySelectorAll(".feedback-score input").forEach((radio) => {
    radio.addEventListener("change", () => {
      const fieldset = radio.closest("fieldset");
      fieldset.classList.remove("has-error");
      fieldset.querySelector(".feedback-field-error").hidden = true;
    });
  });
} else {
  try { localStorage.removeItem(`linguapath:feedback-draft:${window.feedbackDraftKey}`); } catch (_) {}
}
