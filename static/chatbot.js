const t=document.getElementById("cc-toggle");const p=document.getElementById("cc-panel");const m=document.getElementById("cc-messages");const i=document.getElementById("cc-input");const s=document.getElementById("cc-send");
function addMsg(text,who){const d=document.createElement("div");d.className="cc-msg "+(who==="user"?"cc-user":"cc-bot");d.innerText=text;m.appendChild(d);m.scrollTop=m.scrollHeight}
t.onclick=()=>{p.style.display=p.style.display==="block"?"none":"block"}
s.onclick=async()=>{const q=i.value.trim();if(!q)return;addMsg(q,"user");i.value="";try{const r=await fetch("/api/chatbot",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({q})});const j=await r.json();addMsg(j.answer||"", "bot")}catch(e){addMsg("Service unavailable.","bot")}}
i.addEventListener("keydown",e=>{if(e.key==="Enter"){s.click()}})
