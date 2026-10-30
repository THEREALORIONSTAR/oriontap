const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }
const $ = id => document.getElementById(id);
const API_BASE = new URLSearchParams(location.search).get('api') || '';
const clock = () => {
  const now = new Date();
  $('clock').textContent = new Intl.DateTimeFormat('en-NG',{timeZone:'Africa/Lagos',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(now);
  $('clock-date').textContent = new Intl.DateTimeFormat('en-NG',{timeZone:'Africa/Lagos',weekday:'long',day:'numeric',month:'short',year:'numeric'}).format(now);
};
if (!tg?.initData) {
  $('tap').disabled=true;
  $('daily').disabled=true;
}
clock(); setInterval(clock,1000);
let player = null;
function render(p) {
  player = p;
  $('points').textContent = Number(p.points).toLocaleString();
  $('energy').textContent = p.energy;
  $('energy-fill').style.width = `${Math.max(0, Math.min(100,p.energy/5))}%`;
  $('streak').textContent = p.streak;
  $('tap').disabled = p.energy < 1;
}
async function callApi(path, method='GET') {
  const initData = tg?.initData || '';
  const response = await fetch(`${API_BASE}${path}`,{method,headers:{'Content-Type':'application/json','X-Telegram-Init-Data':initData}});
  let data; try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) throw new Error(data.error || 'Could not sync with OrionTap.');
  return data;
}
async function load() {
  if (!tg?.initData) { $('notice').textContent='Open this page from Telegram after the bot is configured to sync points.'; return; }
  try {
    const data = await callApi('/api/me'); render(data.player);
    if (data.referral_link) $('ref-link').textContent=data.referral_link;
    $('notice').textContent='Your Telegram account is connected.';
  } catch(e) { $('notice').textContent=e.message; }
}
$('tap').addEventListener('click',async()=>{
  if (!tg?.initData) { $('notice').textContent='Telegram sign-in is needed before points can be saved.'; return; }
  $('tap').disabled=true;
  try { const data=await callApi('/api/tap','POST'); render(data.player); $('notice').textContent=`+1 point · ${data.player.points.toLocaleString()} total`; }
  catch(e){ $('notice').textContent=e.message; await load(); }
});
$('daily').addEventListener('click',async()=>{
  if (!tg?.initData) { $('notice').textContent='Open through Telegram to claim your streak bonus.'; return; }
  $('daily').disabled=true;
  try { const data=await callApi('/api/daily','POST'); render(data.player); $('notice').textContent=data.claimed?`Daily bonus claimed: +${data.bonus} points`:'Daily bonus already claimed today'; }
  catch(e){ $('notice').textContent=e.message; }
  finally { $('daily').disabled=false; }
});
$('share').addEventListener('click',async()=>{
  if (!tg?.initData) { $('notice').textContent='Open this page through Telegram to use your personal invite link.'; return; }
  const link=$('ref-link').textContent;
  if (!link.startsWith('https://t.me/')) { $('notice').textContent='Your personal invite link appears after opening in Telegram.'; return; }
  const shareUrl=`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent('join me on OrionTap and mine free points')}`;
  if (tg?.openTelegramLink) tg.openTelegramLink(shareUrl);
  else if (navigator.share) { try { await navigator.share({title:'Join OrionTap',text:'Mine free OrionTap points with me',url:link}); } catch {} }
  else { try { await navigator.clipboard.writeText(link); $('notice').textContent='Invite link copied.'; } catch { $('notice').textContent=link; } }
});
load();
