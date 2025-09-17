(function () {
  const t = document.getElementById("cc-toggle");
  const p = document.getElementById("cc-panel");
  const m = document.getElementById("cc-messages");
  const i = document.getElementById("cc-input");
  const s = document.getElementById("cc-send");
  if (!t || !p) return;
  t.addEventListener("click", () => {
    p.style.display = p.style.display === "block" ? "none" : "block";
  });
  function add(text, cls) {
    const div = document.createElement("div");
    div.className = cls || "text-light";
    div.style.margin = "6px 0";
    div.innerText = text;
    m.appendChild(div); m.scrollTop = m.scrollHeight;
  }
  s.addEventListener("click", () => {
    const q = i.value.trim();
    if (!q) return;
    add("You: " + q, "text-info");
    if (/event|upcoming|latest/i.test(q)) add("Bot: Check Home for Upcoming Events, click an item for full details.", "text-light");
    else if (/alumni|directory/i.test(q)) add("Bot: Open the Alumni page to browse and filter.", "text-light");
    else if (/register/i.test(q)) add("Bot: Use Register to verify your college email via OTP.", "text-light");
    else add("Bot: Try asking about events, alumni, or register.", "text-light");
    i.value = "";
  });
})()
