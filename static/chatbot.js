(function () {
  var css = `
#cc-fab{position:fixed;bottom:24px;right:24px;width:56px;height:56px;border-radius:50%;background:#0d6efd;color:#fff;display:grid;place-items:center;box-shadow:0 8px 24px rgba(0,0,0,.35);cursor:pointer;z-index:2147483647}
#cc-fab:active{transform:scale(.98)}
#cc-chat{position:fixed;bottom:92px;right:24px;width:360px;max-width:92vw;background:#0f1b2a;border:1px solid #203247;border-radius:14px;box-shadow:0 16px 40px rgba(0,0,0,.45);display:none;color:#e9f2ff;z-index:2147483646}
#cc-chat.open{display:block}
#cc-chat .cc-head{padding:10px 12px;border-bottom:1px solid #203247;display:flex;gap:10px;align-items:center;justify-content:space-between}
#cc-chat .cc-title{font-weight:600}
#cc-chat .cc-close{background:transparent;border:0;color:#e9f2ff;font-size:20px;line-height:1;padding:0 6px;cursor:pointer}
#cc-chat .cc-body{height:260px;overflow:auto;padding:12px}
#cc-chat .cc-msg{background:#132134;border:1px solid #203247;border-radius:10px;padding:8px 10px;font-size:14px;margin-bottom:8px;max-width:88%}
#cc-chat .cc-msg.me{background:#0d6efd;border-color:#0d6efd;color:#fff;margin-left:auto}
#cc-chat .cc-quick{display:flex;flex-wrap:wrap;gap:8px;padding:0 12px 10px 12px;border-top:1px solid #203247}
#cc-chat .cc-chip{background:#132134;border:1px solid #203247;color:#e9f2ff;border-radius:999px;padding:6px 10px;font-size:12px;cursor:pointer}
#cc-chat .cc-chip:hover{border-color:#35507a}
#cc-chat .cc-input{border-top:1px solid #203247;padding:10px;display:flex;gap:8px}
#cc-chat .cc-input input{flex:1;min-height:40px;background:#0b1729;border:1px solid #203247;color:#e9f2ff;border-radius:8px;padding:8px 10px}
#cc-chat .cc-input button{background:#0d6efd;border:0;color:#fff;border-radius:8px;padding:0 14px;min-height:40px;cursor:pointer}
#cc-chat .cc-msg a{color:#9ecbff;text-decoration:underline}
input[placeholder*="Ask about events"], input[placeholder*="alumni, register"]{display:none!important}
`;
  var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  function el(tag, attrs, children){var e=document.createElement(tag);if(attrs)Object.keys(attrs).forEach(function(k){if(k==="class")e.className=attrs[k];else if(k==="text")e.textContent=attrs[k];else e.setAttribute(k,attrs[k]);});(children||[]).forEach(function(c){e.appendChild(c)});return e}
  function esc(s){return s.replace(/[&<>"']/g,function(c){return({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])})}
  function linkify(t){var safe=esc(t);return safe.replace(/\/[a-zA-Z0-9][a-zA-Z0-9/_-]*/g,function(m){return '<a href="'+m+'">'+m+"</a>"})}

  var fab=el("button",{id:"cc-fab","aria-label":"Open help","aria-keyshortcuts":"Alt+/"},
    [el("span",{text:"✦"})]);
  var head=el("div",{class:"cc-head"},[
    el("div",{class:"cc-title",id:"cc-title",text:"Campus Circle Help"}),
    el("button",{class:"cc-close","aria-label":"Close"},[el("span",{text:"×"})])
  ]);
  var body=el("div",{class:"cc-body",id:"cc-body"},[
    el("div",{class:"cc-msg",text:"Hi! Quick topics below, or ask about register, login, forgot/reset, change email, profile, alumni, events, blogs, or contact."})
  ]);
  var quick=el("div",{class:"cc-quick",id:"cc-quick"},[]);
  var input=el("div",{class:"cc-input"},[
    el("input",{id:"cc-in",type:"text",placeholder:"Type a question…"}),
    el("button",{id:"cc-send",type:"button",text:"Send"})
  ]);
  var win=el("div",{id:"cc-chat",role:"dialog","aria-modal":"true","aria-labelledby":"cc-title"},[head,body,quick,input]);

  function msg(text,me,html){var m=el("div",{class:"cc-msg"+(me?" me":"")}); if(html){m.innerHTML=html}else{m.textContent=text} body.appendChild(m); body.scrollTop=body.scrollHeight}
  function openChat(){win.classList.add("open"); setTimeout(function(){document.getElementById("cc-in").focus()},0)}
  function closeChat(){win.classList.remove("open"); fab.focus()}
  function normalize(s){return (s||"").toLowerCase().trim()}
  function tokens(s){return normalize(s).split(/[^a-z0-9]+/).filter(Boolean)}
  function hasKey(set,phrase){var w=phrase.toLowerCase().split(/\s+/).filter(Boolean);return w.every(function(x){return set.has(x)})}

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
    {id:"where",keys:["where is","how to find","navigate"],text:"Top nav: Home, Alumni, Blog, About, Contact, and Account menu (Profile, Logout)."}
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
    "Forgot password":"forgot",
    "Change email":"email",
    "Home":"where",
    "Register":"register",
    "Login":"login",
    "Alumni":"alumni",
    "Events":"events",
    "Blog":"blogs",
    "Profile":"profile",
    "Contact":"contact"
  };

  function setQuick(list){
    quick.innerHTML="";
    (list||SUGGEST.home).forEach(function(label){
      var b=el("button",{class:"cc-chip",type:"button",text:label});
      b.addEventListener("click",function(){sendLabel(label)});
      quick.appendChild(b);
    });
  }

  function best(q){
    var t=normalize(q);
    var set=new Set(tokens(t));
    var top={score:0,row:null};
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
    var inp=document.getElementById("cc-in");
    var val=inp.value.trim();
    if(!val) return;
    msg(val,true,false);
    inp.value="";
    var row=best(val);
    if(row){
      msg("",false,linkify(row.text));
      setQuick(SUGGEST[row.id]||SUGGEST.home);
    }else{
      msg("I didn’t catch that. Try the buttons below or ask about register, login, forgot/reset, change email, profile, alumni, events, blogs, or contact.",false,false);
      setQuick(SUGGEST.home);
    }
  }

  function sendLabel(label){
    var key=ALIASES[label]||label.toLowerCase();
    var row=KB.find(r=>r.id===key);
    msg(label,true,false);
    if(row){
      msg("",false,linkify(row.text));
      setQuick(SUGGEST[row.id]||SUGGEST.home);
    }else{
      setQuick(SUGGEST.home);
    }
  }

  fab.addEventListener("click",function(){win.classList.contains("open")?closeChat():openChat()});
  head.querySelector(".cc-close").addEventListener("click",closeChat);
  input.querySelector("#cc-send").addEventListener("click",send);
  input.querySelector("#cc-in").addEventListener("keydown",function(e){if(e.key==="Enter")send()});
  document.addEventListener("keydown",function(e){if(e.altKey&&e.key==="/"){e.preventDefault();openChat()}if(e.key==="Escape"&&win.classList.contains("open")){e.preventDefault();closeChat()}});

  document.body.appendChild(fab);
  document.body.appendChild(win);
  setQuick(SUGGEST.home);
})();
