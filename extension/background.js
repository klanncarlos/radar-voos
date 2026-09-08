
chrome.runtime.onInstalled.addListener(()=>chrome.alarms.create("refresh",{periodInMinutes:60}));
chrome.alarms.onAlarm.addListener(async a=>{
 if(a.name!=="refresh")return;
 const s=await chrome.storage.local.get(["feedUrl","lastSeenBest"]);if(!s.feedUrl)return;
 try{
  const r=await fetch(s.feedUrl+"?t="+Date.now()),d=await r.json(),best=d.deals?.[0];
  if(!best)return;
  const key=`${best.origin}-${best.destination}-${best.departure}-${best.price}`;
  if(s.lastSeenBest!==key){
   await chrome.storage.local.set({lastSeenBest:key});
   chrome.notifications.create("cloud-deal",{type:"basic",iconUrl:"icons/icon128.png",title:"✈ Radar de Voos",message:`Melhor tarifa atual: ${best.origin} → ${best.destination} por ${best.currency} ${best.price.toFixed(2)}`});
  }
 }catch(e){}
});
