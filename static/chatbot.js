(function () {
  function el(tag, attrs, children) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "class") e.className = attrs[k]; else if (k === "text") e.textContent = attrs[k]; else e.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { e.appendChild(c); });
    return e;
  }

  function mount() {
    if (document.getElementById("cc-chat-fab") || document.getElementById("cc-chat")) return;

    var fab = el("div", { id: "cc-chat-fab", title: "Chat" }, [el("span", { text: "✦" })]);

    var head = el("div", { class: "cc-head" }, [
      el("div", { class: "cc-title", text: "Assistant" }),
      el("button", { class: "cc-close", "aria-label": "Close", type: "button" }, [el("span", { text: "×" })])
    ]);

    var body = el("div", { class: "cc-body" }, [
      el("div", { class: "cc-msg", text: "Hi! Ask about events, alumni, or registration." })
    ]);

    var input = el("div", { class: "cc-input" }, [
      el("input", { type: "text", placeholder: "Type a message…" }),
      el("button", { type: "button", text: "Send" })
    ]);

    var win = el("div", { id: "cc-chat" }, [head, body, input]);

    fab.addEventListener("click", function () {
      win.classList.toggle("open");
    });
    head.querySelector(".cc-close").addEventListener("click", function () {
      win.classList.remove("open");
    });

    input.querySelector("button").addEventListener("click", function () {
      var val = input.querySelector("input").value.trim();
      if (!val) return;
      var mine = el("div", { class: "cc-msg me", text: val });
      body.appendChild(mine);
      input.querySelector("input").value = "";
      body.scrollTop = body.scrollHeight;
    });

    document.body.appendChild(fab);
    document.body.appendChild(win);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
