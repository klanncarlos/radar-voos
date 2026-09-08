
const $=x=>document.getElementById(x);
const money=(n,c)=>new Intl.NumberFormat("pt-BR",{style:"currency",currency:c||"BRL"}).format(n);
async function load(){
 const s=await chrome.storage.local.get("feedUrl");$("url").value=s.feedUrl||"";
 if(!s.feedUrl){$("deals").innerHTML="";return;}
 try{const r=await fetch(s.feedUrl+"?t="+Date.now());const d=await r.json();
 $("updated").textContent=d.updated_at?"Atualizado "+new Date(d.updated_at).toLocaleString("pt-BR"):"Sem consultas ainda";
 $("deals").innerHTML=(d.deals||[]).slice(0,15).map(x=>`<div class="deal"><div><b>${x.origin} → ${x.destination}</b><div class="muted">${x.departure} a ${x.return}</div></div><div class="price">${money(x.price,x.currency)}</div></div>`).join("")||'<div class="muted">Nenhuma oferta.</div>';
 }catch(e){$("updated").textContent="Erro ao carregar o feed.";}
}
$("save").onclick=async()=>{await chrome.storage.local.set({feedUrl:$("url").value.trim()});load();};
$("refresh").onclick=load;load();
