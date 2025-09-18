(function () {
  var css = `
#cc-fab{position:fixed;bottom:24px;right:24px;width:56px;height:56px;border-radius:50%;background:#0d6efd;color:#fff;display:grid;place-items:center;box-shadow:0 8px 24px rgba(0,0,0,.35);cursor:pointer;z-index:2147483647}
#cc-fab:active{transform:scale(.98)}
#cc-chat{position:fixed;bottom:92px;right:24px;width:360px;max-width:92vw;background:#0f1b2a;border:1px solid #203247;border-radius:14px;box-shadow:0 16px 40px rgba(0,0,0,.45);display:none;color:#e9f2ff;z-index:2147483646}
#cc-chat.open{display:block}
#cc-chat .cc-head{padding:10px 12px;border-bottom:1px solid #203247;display:flex;gap:10px;align-items:center;justify-content:space-between}
#cc-chat .cc-title{font-weight:600}
#cc-chat .cc-actions{display:flex;gap:8px;align-items:center}
#cc-chat .cc-toggle{appearance:none;width:38px;height:22px;border-radius:20px;background:#203247;position:relative;outline:0;border:0;cursor:pointer}
#cc-chat .cc-toggle:checked{background:#0d6efd}
#cc-chat .cc-toggle:before{content:"";position:absolute;left:3px;top:3px;width:16px;height:16px;border-radius:50%;background:#e9f2ff;transition:transform .18s ease}
#cc-chat .cc-toggle:checked:before{transform:translateX(16px)}
#cc-chat .cc-close{background:transparent;border:0;color:#e9f2ff;font-size:20px;line-height:1;padding:0 6px;cursor:pointer}
#cc-chat .cc-body{height:280px;overflow:auto;padding:12px}
#cc-chat .cc-msg{background:#132134;border:1px solid #203247;border-radius:10px;padding:8px 10px;font-size:14px;margin-bottom:8px;max-width:88%}
#cc-chat .cc-msg.me{background:#0d6efd;border-color:#0d6efd;color:#fff;margin-left:auto}
#cc-chat .cc-input{border-top:1px solid #203247;padding:10px;display:flex;gap:8px}
#cc-chat .cc-input input{flex:1;min-height:40px;background:#0b1729;border:1px solid #203247;color:#e9f2ff;border-radius:8px;padding:8px 10px}
#cc-chat .cc-input button{background:#0d6efd;border:0;color:#fff;border-radius:8px;padding:0 14px;min-height:40px;cursor:pointer}
input[placeholder*="Ask about events"],input[placeholder*="alumni, register"]{display:none!important}
`;
  var s = document.createElement("style");
  s.textContent = css;
  document.head.appendChild(s);

  function el(tag, attrs, children) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "class") e.className = attrs[k];
      else if (k === "text") e.textContent = attrs[k];
      else e.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { e.appendChild(c); });
    return e;
  }

  var fab = el("button", { id: "cc-fab", "aria-label": "Open help", "aria-keyshortcuts": "Alt+/" }, [el("span",{text:"✦"})]);
  var head = el("div", { class: "cc-head" }, [
    el("div", { class: "cc-title", text: "Campus Circle Help" }),
    el("div", { class: "cc-actions" }, [
      el("label", { style: "display:flex;gap:6px;align-items:center;font-size:12px" }, [
        el("span", { text: "TTS" }),
        el("input", { type: "checkbox", class: "cc-toggle", id: "cc-tts" })
      ]),
      el("button", { class: "cc-close", "aria-label": "Close" }, [el("span", { text: "×" })])
    ])
  ]);
  var body = el("div", { class: "cc-body", id: "cc-body" }, [
    el("div", { class: "cc-msg", text: "Hi! Ask me about register, login, alumni filters, events, blogs, profile, change email, or admin." })
  ]);
  var input = el("div", { class: "cc-input" }, [
    el("input", { id: "cc-in", type: "text", placeholder: "Type a question…" }),
    el("button", { id: "cc-send", type: "button", text: "Send" })
  ]);
  var win = el("div", { id: "cc-chat", role: "dialog", "aria-modal": "true", "aria-labelledby": "cc-title" }, [head, body, input]);

  function speak(text) {
    var tts = document.getElementById("cc-tts");
    if (!tts || !tts.checked) return;
    try {
      var synth = window.speechSynthesis;
      if (!synth) return;
      var u = new SpeechSynthesisUtterance(text);
      synth.speak(u);
    } catch (e) {}
  }

  function msg(text, me) {
    var m = el("div", { class: "cc-msg" + (me ? " me" : "") });
    m.textContent = text;
    body.appendChild(m);
    body.scrollTop = body.scrollHeight;
  }

  function openChat() {
    win.classList.add("open");
    setTimeout(function(){ document.getElementById("cc-in").focus(); }, 0);
  }
  function closeChat() {
    win.classList.remove("open");
    fab.focus();
  }

  function normalize(s) { return (s||"").toLowerCase().trim(); }

  var KB = [
    { id:"register", keys:["register","sign up","create account"], a:"Go to Register and enter college email, personal email and password. You’ll get an OTP on your college email. Verify it, then complete your profile. Link: /register" },
    { id:"login", keys:["login","sign in"], a:"Use your personal email to log in at /login. College email is only for initial verification." },
    { id:"forgot", keys:["forgot password","reset password"], a:"Use Forgot on /login. Step 1: enter email to get OTP. Step 2: verify OTP. Step 3: set a new password." },
    { id:"verify", keys:["otp","resend","verify"], a:"OTP lifetime is 10 minutes with resend cooldown about a minute. Try again after a short wait; check spam too." },
    { id:"email change", keys:["change email","update email","new email"], a:"Open Settings → Email at /settings/email. Confirm with your password, an OTP is sent to the new address, verify, done." },
    { id:"profile", keys:["profile","edit profile","update details"], a:"Edit your name, company, branch, year, phone and LinkedIn at /profile. Save after valid entries." },
    { id:"alumni", keys:["alumni","directory","people"], a:"See Alumni at /alumni. Filter by name/company, year, branch. Use the Show N control for pagination (10/25/50). Public view hides phone." },
    { id:"events", keys:["events","upcoming","event"], a:"Home shows Upcoming and Latest. Click an event for details and registration link. Past events say Past Event." },
    { id:"blogs", keys:["blog","blogs","announcements"], a:"Blog lives at /blog. Admins can create/publish; published items appear on Home under Latest Announcements." },
    { id:"admin login", keys:["admin login","/admin/login"], a:"Admin login is only at /admin/login. No create account/forgot there." },
    { id:"admin events", keys:["admin events","publish event","create event"], a:"Admin → Events at /admin/events. Create new, toggle publish, delete, or open to edit." },
    { id:"admin blogs", keys:["admin blogs","publish blog","create blog"], a:"Admin → Blogs at /admin/blogs. Create, search, toggle publish, delete." },
    { id:"admin alumni", keys:["admin alumni","delete alumni","manage alumni"], a:"Admin → Alumni at /admin/alumni. Search, paginate, and delete entries." },
    { id:"contact", keys:["contact","support","help"], a:"Find Contact at /contact. For account issues, include your personal email and any error you see." },
    { id:"where", keys:["where is","how to find","navigate"], a:"Main navigation: Home, Alumni, Blog, About, Contact, Account menu (Profile, Logout). Admin is hidden; go directly to /admin/login." }
  ];

  function bestAnswer(q) {
    var t = normalize(q);
    var top = {score:0, a:null};
    KB.forEach(function(row){
      var score = 0;
      row.keys.forEach(function(k){
        if (t.includes(k)) score += Math.max(1, Math.floor(k.length/6));
      });
      if (score>top.score) top = {score:score, a:row.a};
    });
    if (top.a) return top.a;
    if (/alum/.test(t) && /search|find|filter/.test(t)) return "Use the top filters on /alumni: name/company, year, branch. Then click Filter. Adjust Show N for more rows.";
    if (/event/.test(t) && /where|how/.test(t)) return "Open Home, choose an item under Upcoming Events, then click its title for the full page and registration link.";
    if (/email/.test(t) && /change|update|switch/.test(t)) return "Open /settings/email, enter your password, confirm OTP sent to the new email.";
    if (/register/.test(t) && /otp|code/.test(t)) return "After submitting the Register form, check college inbox for the OTP. It expires in ~10 minutes.";
    return "I didn’t catch that. Ask about register, login, forgot/reset, change email, profile, alumni filters, events, blogs, or admin pages.";
  }

  function send() {
    var inp = document.getElementById("cc-in");
    var val = inp.value.trim();
    if (!val) return;
    msg(val, true);
    inp.value = "";
    var a = bestAnswer(val);
    msg(a, false);
    speak(a);
  }

  fab.addEventListener("click", function () { win.classList.contains("open") ? closeChat() : openChat(); });
  head.querySelector(".cc-close").addEventListener("click", closeChat);
  input.querySelector("#cc-send").addEventListener("click", send);
  input.querySelector("#cc-in").addEventListener("keydown", function (e) { if (e.key==="Enter") send(); });
  document.addEventListener("keydown", function(e){
    if (e.altKey && e.key === "/") { e.preventDefault(); openChat(); }
    if (e.key === "Escape" && win.classList.contains("open")) { e.preventDefault(); closeChat(); }
  });

  document.body.appendChild(fab);
  document.body.appendChild(win);
})();
