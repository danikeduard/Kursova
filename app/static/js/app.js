const chat = document.getElementById("chat");
const input = document.getElementById("userInput");
const indicator = document.getElementById("levelIndicator");
const levelButtons = document.querySelectorAll(".lvl-btn");

let currentLevel = "beginner";

function addMessage(text, cls) {
    const el = document.createElement("div");
    el.className = "msg " + cls;
    el.textContent = text; // textContent, щоб уникнути XSS
    chat.appendChild(el);
    chat.scrollTop = chat.scrollHeight;
}

function showLevel(level) {
    currentLevel = level;
    indicator.textContent = "LEVEL: " + level.toUpperCase();
    levelButtons.forEach(b => b.classList.toggle("active", b.dataset.level === level));
}

async function setLevel(level) {
    showLevel(level);
    // лишаємо тільки привітання
    chat.querySelectorAll(".msg:not(#welcome)").forEach(el => el.remove());
    await fetch("/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ level }),
    });
}

async function send() {
    const text = input.value.trim();
    if (!text) return;

    addMessage(text, "user");
    input.value = "";

    try {
        const res = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text }),
        });
        const data = await res.json();
        addMessage(data.reply, res.ok ? "bot" : "bot error");
        if (data.level) showLevel(data.level);
    } catch (e) {
        addMessage("Помилка підключення", "bot error");
    }
}

levelButtons.forEach(b => b.addEventListener("click", () => setLevel(b.dataset.level)));
document.getElementById("send-btn").addEventListener("click", send);
input.addEventListener("keypress", e => { if (e.key === "Enter") send(); });
