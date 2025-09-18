// static/chatbot.js — lightweight site-help bot (no TTS)
(function () {
  // --- injected styles (scoped to the widget) ---
  var css = `
#cc-fab{position:fixed;bottom:24px;right:24px;width:56px;height:56px;border-radius:50%;background:#0d6efd;color:#fff;display:grid;place-items:center;box-shadow:0 8px 24px rgba(0,0,0,.35);cursor:pointer;z-index:2147483647}
#cc-fab:active{transform:scale(.98)}
#cc-chat{position:fixed;bottom:92px;right:24px;width:360px;max-width:92vw;background:#0f1b2a;border:1px solid #203247;border-radius:14px;box-shadow:0 16px 40px rgba(0,0,0,.45);display:none;color:#e9f2ff;z-index:2147483646}
#cc-chat.open{display:block}
#cc-chat .cc-head{padding:10px 12px;border-bottom:1px solid #203247;display:flex;gap:10px;align-items:center;justify-content:space-between}
#cc-chat .cc-title{font-weight:600}
#cc-chat .cc-close{background:transparent;border:0;color:#e9f2ff;font-size:20px;line-height:1;padding:0 6px;cursor:pointer}
#cc-chat .cc-body{height:280px;overflow:auto;padding:12px}
#cc-chat .cc-msg{background:#132134;border:1px solid #203247;border-radius:10px;padding:8px 10px;font-size:14px;margin-bottom:8px;max-width:88%}
#cc-chat .cc-msg.me{background:#0d6efd;border-color:#0d6efd;color:#fff;margin-left:auto}
#cc-chat .cc-input{border-top:1px solid #203247;padding:10px;display:flex;gap:8px}
#cc-chat .cc-input input{flex:1;min-height:40px;background:#0b1729;border:1px solid #203247;color:#e9f2ff;border-radius:8px;padding:8px 10px}
#cc-chat .cc-input button{background:#0d6efd;border:0;color:#fff;border-radius:8px;padding:0 14px;min-height:40px;cursor:pointer}
/* hide any legacy bottom chat bars the old script may have left behind */
input[placeholder*="Ask about events"], input[placeholder*="alumni, register"]{display:none!important}
`;
  var s = document.createElement("style");
  s.textContent = css;
  document.head.appendChild(s);

  // --- tiny DOM helpers ---
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

  // --- widget skeleton ---
  var fab = el("button", { id: "cc-fab", "aria-label": "Open help", "aria-keyshortcuts": "Alt+/" }, [el("span",{text:"✦"})]);
  var head = el("div", { class: "cc-head" }, [
    el("div", { class: "cc-title", id: "cc-title", text: "Campus Circle Help" }),
    el("button", { class: "cc-close", "aria-label": "Close" }, [el("span", { text: "×" })])
  ]);
  var body = el("div", { class: "cc-body", id: "cc-body" }, [
    el("div", { class: "cc-msg", text: "Hi! Ask about register, login, forgot/reset, change email, profile, alumni filters, events, blogs, or admin pages." })
  ]);
  var input = el("div", { class: "cc-input" }, [
    el("input", { id: "cc-in", type: "text", placeholder: "Type a question…" }),
    el("button", { id: "cc-send", type: "button", text: "Send" })
  ]);
  var win = el("div", { id: "cc-chat", role: "dialog", "aria-modal": "true", "aria-labelledby": "cc-title" }, [head, body, input]);

  // --- utilities ---
  function msg(text, me) {
    var m = el("div", { class: "cc-msg" + (me ? " me" : "") });
    m.textContent = text;
    body.appendChild(m);
    body.scrollTop = body.scrollHeight;
  }
  function openChat() { win.classList.add("open"); setTimeout(function(){ document.getElementById("cc-in").focus(); }, 0); }
  function closeChat() { win.classList.remove("open"); fab.focus(); }

  function normalize(s){ return (s||"").toLowerCase().trim(); }
  function tokenize(s){ return normalize(s).split(/[^a-z0-9]+/).filter(Boolean); }
  function hasKey(tokensSet, keyPhrase){
    // treat multi-word keys as AND across words, single words as whole-word matches
    var words = keyPhrase.toLowerCase().split(/\s+/).filter(Boolean);
    return words.every(function(w){ return tokensSet.has(w); });
  }

  // --- knowledge base (expanded "forgot" synonyms) ---
  var KB = [
    { id:"register", keys:["register","sign up","create account","registration"], a:"Go to /register. Enter college email, personal email and a password. We send OTP to the college email. Verify it, then complete your profile." },
    { id:"login", keys:["login","sign in"], a:"Use your personal email to log in at /login. College email is only for initial verification." },
    { id:"forgot", keys:["forgot","forget","forgotten","reset","reset password","forgot password","password reset"], a:"Click ‘Forgot password?’ on /login. Step 1: enter your email to get an OTP. Step 2: verify OTP. Step 3: set a new password." },
    { id:"verify", keys:["otp","code","resend","verify"], a:"OTP lifetime is ~10 minutes. Resend is throttled (~60s). Check spam if it’s missing." },
    { id:"email change", keys:["change email","update email","new email","switch email"], a:"Open /settings/email. Enter your current password, we’ll send an OTP to the NEW address; verify to update." },
    { id:"profile", keys:["profile","edit profile","update details"], a:"Edit name, company, branch, year, phone and LinkedIn at /profile. Save after valid entries." },
    { id:"alumni", keys:["alumni","directory","people"], a:"/alumni has filters: name/company, year, branch, plus pagination Show 10/25/50. Public view hides phone." },
    { id:"events", keys:["events","event","upcoming"], a:"Home shows Upcoming and Latest. Click an event for details and its registration link. Past ones show ‘Past Event’." },
    { id:"blogs", keys:["blog","blogs","announcements"], a:"Blog is at /blog. Admins can create/publish; published items also appear on Home under Latest Announcements." },
    { id:"admin login", keys:["admin login","/admin/login"], a:"Admin login is only at /admin/login. No create account/forgot there." },
    { id:"admin events", keys:["admin events","publish event","create event"], a:"Admin → Events: /admin/events. Create, toggle publish, delete, or open to edit. Includes search." },
    { id:"admin blogs", keys:["admin blogs","publish blog","create blog"], a:"Admin → Blogs: /admin/blogs. Create, search, toggle publish, delete." },
    { id:"admin alumni", keys:["admin alumni","delete alumni","manage alumni"], a:"Admin → Alumni: /admin/alumni. Search, paginate, delete entries." },
    { id:"where", keys:["where is","how to find","navigate"], a:"Top nav: Home, Alumni, Blog, About, Contact, Account menu (Profile/Logout). Admin is hidden; visit /admin/login directly." }
  ];

  function bestAnswer(q){
    var text = normalize(q);
    var tokens = tokenize(text);
    var set = new Set(tokens);

    // score KB rows by matched keys
    var top = {score:0, a:null};
    KB.forEach(function(row){
      var rowScore = 0;
      row.keys.forEach(function(k){
        if (hasKey(set, k)) {
          // weight longer keys slightly higher
          rowScore += Math.max(1, Math.floor(k.length/6));
        } else {
          // simple substring fallback for phrases (covers "where is alumni")
          if (text.includes(k)) rowScore += 1; // String.includes per MDN. :contentReference[oaicite:0]{index=0}
        }
      });
      if (rowScore > top.score) top = {score: rowScore, a: row.a};
    });

    if (top.a) return top.a;

    // smart fallbacks for common wording
    if (/forget|forgot|forgotten/.test(text)) return KB.find(r=>r.id==="forgot").a; // RegExp.test per MDN. :contentReference[oaicite:1]{index=1}
    if (/reset/.test(text) && /pass/.test(text)) return KB.find(r=>r.id==="forgot").a;

    return "I didn’t catch that. Ask about register, login, forgot/reset, change email, profile, alumni filters, events, blogs, or admin pages.";
  }

  function send(){
    var inp = document.getElementById("cc-in");
    var val = inp.value.trim();
    if (!val) return;
    msg(val, true);
    inp.value = "";
    var a = bestAnswer(val);
    msg(a, false);
  }

  // open/close & keyboard
  fab.addEventListener("click", function(){ win.classList.contains("open") ? closeChat() : openChat(); });
  head.querySelector(".cc-close").addEventListener("click", closeChat);
  input.querySelector("#cc-send").addEventListener("click", send);
  input.querySelector("#cc-in").addEventListener("keydown", function (e) { if (e.key==="Enter") send(); });
  document.addEventListener("keydown", function(e){
    if (e.altKey && e.key === "/") { e.preventDefault(); openChat(); }
    if (e.key === "Escape" && win.classList.contains("open")) { e.preventDefault(); closeChat(); }
  });

  // mount
  document.body.appendChild(fab);
  document.body.appendChild(win);
})();
