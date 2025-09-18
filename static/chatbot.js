// static/chatbot.js — compact site-help bot with better UI + a11y
(function () {
  /* ----------------------- styles ----------------------- */
  var css = `
#cc-fab{
  position:fixed;bottom:24px;right:24px;width:56px;height:56px;border-radius:50%;
  background:#0d6efd;color:#fff;display:grid;place-items:center;
  box-shadow:0 10px 30px rgba(0,0,0,.45);cursor:pointer;z-index:2147483647;
  transition:transform .18s ease, box-shadow .18s ease
}
#cc-fab:hover{transform:translateY(-1px);box-shadow:0 14px 36px rgba(0,0,0,.5)}
#cc-fab:active{transform:scale(.98)}
#cc-chat{
  position:fixed;bottom:92px;right:24px;width:380px;max-width:94vw;
  background:rgba(12,19,32,.92);backdrop-filter:saturate(140%) blur(10px);
  border:1px solid rgba(255,255,255,.06);border-radius:16px;
  box-shadow:0 24px 60px rgba(0,0,0,.6);display:none;color:#eaf1ff;z-index:2147483646;
  transform:translateY(8px) scale(.98);opacity:0;transition:transform .2s ease, opacity .2s ease
}
#cc-chat.open{display:block;transform:none;opacity:1}
#cc-chat .cc-head{
  padding:12px 14px;border-bottom:1px solid rgba(255,255,255,.05);display:flex;
  gap:10px;align-items:center;justify-content:space-between;
  background:linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,0))
}
#cc-chat .cc-title{font-weight:650;letter-spacing:.2px}
#cc-chat .cc-close{background:transparent;border:0;color:#eaf1ff;font-size:20px;line-height:1;padding:0 6px;cursor:pointer}
#cc-chat .cc-body{height:300px;overflow:auto;padding:12px}
#cc-chat .cc-msg{
  background:#121d2e;border:1px solid rgba(255,255,255,.06);
  border-radius:12px;padding:10px 12px;font-size:14px;margin-bottom:10px;max-width:88%;
}
#cc-chat .cc-msg.me{
  background:#0d6efd;border-color:#0d6efd;color:#fff;margin-left:auto;
}
#cc-chat .cc-msg a{color:#a9d0ff;text-decoration:underline}
#cc-chat .cc-quick{
  display:flex;gap:8px;overflow-x:auto;padding:10px 12px;border-top:1px solid rgba(255,255,255,.05)
}
#cc-chat .cc-quick::-webkit-scrollbar{height:6px}
#cc-chat .cc-quick::-webkit-scrollbar-thumb{background:#1e2b41;border-radius:4px}
#cc-chat .cc-chip{
  white-space:nowrap;background:#121d2e;border:1px solid rgba(255,255,255,.08);
  color:#eaf1ff;border-radius:999px;padding:7px 12px;font-size:12px;cursor:pointer;
  transition:background .15s ease,border-color .15s ease
}
#cc-chat .cc-chip:hover{background:#16243a;border-color:#2f4b7a}
#cc-chat .cc-input{border-top:1px solid rgba(255,255,255,.05);padding:10px;display:flex;gap:8px}
#cc-chat .cc-input input{
  flex:1;min-height:42px;background:#0b1627;border:1px solid rgba(255,255,255,.08);
  color:#eaf1ff;border-radius:10px;padding:10px 12px
}
#cc-chat .cc-input button{
  background:#0d6efd;border:0;color:#fff;border-radius:10px;padding:0 16px;min-height:42px;cursor:pointer
}
/* hide legacy bottom bars from older script */
input[placeholder*="Ask about events"], input[placeholder*="alumni, register"]{display:none!important}
`;
  var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  /* ----------------------- helpers ----------------------- */
  function el(tag, attrs, children){var e=document.createElement(tag);if(attrs)Object.keys(attrs).forEach(function(k){if(k==="class")e.className=attrs[k];else if(k==="text")e.textContent=attrs[k];else e.setAttribute(k,attrs[k]);});(children||[]).forEach(function(c){e.appendChild(c)});return e}
  function esc(s){return s.replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]))}
  function linkify(t){
    var s=esc(t);
    // http(s) links
    s=s.replace(/\bhttps?:\/\/[^\s)]+/g,m=>`<a href="${m}" target="_self" rel="noopener">${m}</a>`);
    // site paths
    s=s.replace(/(?:^|\s)(\/[a-zA-Z0-9][\w\/\-\._]*)/g,(m,p)=>` <a href="${p}" target="_self" rel="noopener">${p}</a>`);
    return s;
  }
  function msg(text,me,html){var m=el("div",{class:"cc-msg"+(me?" me":"")}); if(html){m.innerHTML=html}else{m.textContent=text} body.appendChild(m); body.scrollTop=body.scrollHeight}
  const FOCUSABLE = 'a,button,input,textarea,select,[tabindex]:not([tabindex="-1"])';

  /* ----------------------- structure ----------------------- */
  var fab = el("button",{id:"cc-fab","aria-label":"Open help","aria-keyshortcuts":"Alt+/"},[el("span",{text:"✦"})]);
  var head=el("div",{class:"cc-head"},[
    el("div",{class:"cc-title",id:"cc-title",text:"Campus Circle Help"}),
    el("button",{class:"cc-close","aria-label":"Close"},[el("span",{text:"×"})])
  ]);
  var body=el("div",{class:"cc-body",id:"cc-body"},[
    el("div",{class:"cc-msg",text:"Hi! Use the chips or ask about register, login, forgot/reset, change email, profile, alumni, events, blogs, or contact."})
  ]);
  var quick=el("div",{class:"cc-quick",id:"cc-quick"},[]);
  var input=el("div",{class:"cc-input"},[
    el("input",{id:"cc-in",type:"text",placeholder:"Type a question…"}),
    el("button",{id:"cc-send",type:"button",text:"Send"})
  ]);
  var win=el("div",{id:"cc-chat",role:"dialog","aria-modal":"true","aria-labelledby":"cc-title"},[head,body,quick,input]);

  /* ----------------------- knowledge base ----------------------- */
  function norm(s){return (s||"").toLowerCase().trim()}
  function toks(s){return norm(s).split(/[^a-z0-9]+/).filter(Boolean)}
  function hasKey(set,phrase){var w=phrase.toLowerCase().split(/\s+/).filter(Boolean);return w.every(x=>set.has(x))}

  // user-facing topics ONLY
  var KB=[
    {id:"register",keys:["register","sign up","create account","registration"],text:"Go to /register. Enter college email, personal email, and a password. We send an OTP to the college email. Verify it, then complete your profile."},
    {id:"login",keys:["login","sign in"],text:"Use your personal email to log in at /login. College email is only used during registration."},
    {id:"forgot",keys:["forgot","forget","forgotten","reset","reset password","forgot password","password reset"],text:"Click ‘Forgot password?’ on /login. Step 1: enter your email to get OTP. Step 2: verify OTP. Step 3: set a new password."},
    {id:"verify",keys:["otp","code","resend","verify"],text:"OTP lifetime is ~10 minutes. Resend is throttled (~60s). Check spam if it’s missing."},
    {id:"email",keys:["change email","update email","new email","switch email"],text:"Open /settings/email. Enter your password, we’ll send an OTP to the NEW address; verify to update."},
    {id:"profile",keys:["profile","edit profile","update details"],text:"Edit your details at /profile. Fields include name, year, branch, company, phone, LinkedIn."},
    {id:"alumni",keys:["alumni","directory","people"],text:"See /alumni. Filter by name/company, year, branch, and use the ‘Show N’ selector for pagination."},
    {id:"events",keys:["events","event","upcoming"],text:"Home shows Upcoming and Latest. Click an event for details and its registration link. Past ones show ‘Past Event’."},
    {id:"blogs",keys:["blog","blogs","announcements"],text:"Browse posts at /blog. Published items also appear on Home under Latest Announcements."},
    {id:"contact",keys:["contact","support","help"],text:"Use /contact to reach us. Share your personal email and any error message for faster help."},
    {id:"where",keys:["where is","how to find","navigate"],text:"Top nav: Home, Alumni, Blog, About, Contact, and the Account menu (Profile, Logout)."}
  ];

  var SUGGEST={
    home:["Register","Login","Forgot password","Alumni","Events","Blog","Profile","Change email","Contact"],
    register:["Login","Forgot password","Profile","Alumni"],
    login:["Forgot password","Register","Change email"],
    forgot:["Login","Register","Contact"],
    email:["Profile","Login","Contact"],
    profile:["Alumni","Events","Blog"],
    alumni:["Events","Blog","Home"],
    events:["Alumni","Blog","Home"],
    blogs:["Home","Alumni","Events"],
    contact:["Home","Login","Register"],
    verify:["Forgot password","Login","Contact"],
    where:["Home","Alumni","Blog","Contact"]
  };
  var ALIASES={
    "Forgot password":"forgot","Change email":"email","Home":"where","Register":"register","Login":"login",
    "Alumni":"alumni","Events":"events","Blog":"blogs","Profile":"profile","Contact":"contact"
  };

  function setQuick(list){
    quick.innerHTML="";
    (list||SUGGEST.home).forEach(function(label){
      var b=el("button",{class:"cc-chip",type:"button",text:label});
      b.addEventListener("click",function(){sendLabel(label)});
      quick.appendChild(b);
    });
    quick.scrollLeft=0;
  }

  function best(q){
    var t=norm(q), set=new Set(toks(t)), top={score:0,row:null};
    KB.forEach(function(r){
      var s=0;
      r.keys.forEach(function(k){
        if(hasKey(set,k)) s+=Math.max(1,Math.floor(k.length/6));
        else if(t.includes(k)) s+=1;
      });
      if(s>top.score) top={score:s,row:r};
    });
    if(!top.row){
      if(/forget|forgot|forgotten/.test(t)) top.row=KB.find(r=>r.id==="forgot");
      else if(/reset/.test(t)&&/pass/.test(t)) top.row=KB.find(r=>r.id==="forgot");
    }
    return top.row;
  }

  function send(){
    var inp=document.getElementById("cc-in"); var val=inp.value.trim(); if(!val) return;
    msg(val,true,false); inp.value="";
    var row=best(val);
    if(row){ msg("",false,linkify(row.text)); setQuick(SUGGEST[row.id]||SUGGEST.home); }
    else{ msg("I didn’t catch that. Try the buttons below or ask about register, login, forgot/reset, change email, profile, alumni, events, blogs, or contact.",false,false); setQuick(SUGGEST.home); }
  }
  function sendLabel(label){
    var key=ALIASES[label]||label.toLowerCase(); var row=KB.find(r=>r.id===key);
    msg(label,true,false);
    if(row){ msg("",false,linkify(row.text)); setQuick(SUGGEST[row.id]||SUGGEST.home); }
    else setQuick(SUGGEST.home);
  }

  /* ----------------------- focus trap & open/close ----------------------- */
  var lastFocused = null;
  function trapKey(e){
    if(!win.classList.contains("open")) return;
    if(e.key==="Tab"){
      var nodes=win.querySelectorAll(FOCUSABLE);
      if(!nodes.length) return;
      var first=nodes[0], last=nodes[nodes.length-1];
      if(e.shiftKey && document.activeElement===first){ last.focus(); e.preventDefault(); }
      else if(!e.shiftKey && document.activeElement===last){ first.focus(); e.preventDefault(); }
    }
    if(e.key==="Escape"){ e.preventDefault(); closeChat(); }
  }
  function openChat(){
    lastFocused = document.activeElement;
    win.classList.add("open");
    setTimeout(function(){ (win.querySelector("#cc-in")||win.querySelector(FOCUSABLE)).focus(); }, 0);
    document.addEventListener("keydown", trapKey); // keep focus inside modal. WAI-ARIA dialog guidance. 
  }
  function closeChat(){
    win.classList.remove("open");
    document.removeEventListener("keydown", trapKey);
    (lastFocused||fab).focus();
  }

  /* ----------------------- wires ----------------------- */
  fab.addEventListener("click",()=>win.classList.contains("open")?closeChat():openChat());
  head.querySelector(".cc-close").addEventListener("click",closeChat);
  input.querySelector("#cc-send").addEventListener("click",send);
  input.querySelector("#cc-in").addEventListener("keydown",e=>{ if(e.key==="Enter") send(); });
  document.addEventListener("keydown",e=>{
    if(e.altKey && e.key==="/"){ e.preventDefault(); openChat(); } // expose shortcut to AT via aria-keyshortcuts
  });

  document.body.appendChild(fab);
  document.body.appendChild(win);
  setQuick(SUGGEST.home);
})();
