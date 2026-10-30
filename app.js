const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }
const $ = id => document.getElementById(id);
const API_BASE = new URLSearchParams(location.search).get('api') || '';
const MAX_ENERGY = 500;
const REFILL_MS = 60_000;
const DAILY_BONUS = 25;
const LAGOS = 'Africa/Lagos';
const clock = () => {
  const now = new Date();
  $('clock').textContent = new Intl.DateTimeFormat('en-NG',{timeZone:LAGOS,hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(now);
  $('clock-date').textContent = new Intl.DateTimeFormat('en-NG',{timeZone:LAGOS,weekday:'long',day:'numeric',month:'short',year:'numeric'}).format(now);
};
clock(); setInterval(clock,1000);
function lagosDay(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA',{timeZone:LAGOS,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
  const get = type => parts.find(part => part.type === type)?.value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}
function previousDay(day) {
  const [year, month, date] = day.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, date - 1)).toISOString().slice(0,10);
}
function identity() {
  let id = '';
  try {
    const user = JSON.parse(new URLSearchParams(tg?.initData || '').get('user') || '{}');
    if (user.id != null) id = `tg-${user.id}`;
  } catch {}
  if (!id) {
    id = localStorage.getItem('oriontap-device-id') || '';
    if (!id) {
      id = `device-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
      localStorage.setItem('oriontap-device-id', id);
    }
  }
  return id;
}
const storageKey = `oriontap-player-${identity()}`;
const queueKey = `${storageKey}-sync-queue`;
const defaultPlayer = () => ({points:0, energy:MAX_ENERGY, energyUpdatedAt:Date.now(), streak:0, lastDailyDate:null, tapPower:1});
function readPlayer() {
  try { return {...defaultPlayer(), ...JSON.parse(localStorage.getItem(storageKey) || '{}')}; }
  catch { return defaultPlayer(); }
}
let player = readPlayer();
function save() { localStorage.setItem(storageKey, JSON.stringify(player)); }
function regenerate() {
  const now = Date.now();
  const elapsed = Math.max(0, now - Number(player.energyUpdatedAt || now));
  const gained = Math.floor(elapsed / REFILL_MS);
  if (gained > 0) {
    player.energy = Math.min(MAX_ENERGY, Number(player.energy) + gained);
    player.energyUpdatedAt = player.energy >= MAX_ENERGY ? now : Number(player.energyUpdatedAt) + gained * REFILL_MS;
  }
  if (Number(player.energy) >= MAX_ENERGY) player.energyUpdatedAt = now;
}
function upgradeCost() { return 100 * Number(player.tapPower || 1); }
function render() {
  regenerate();
  $('points').textContent = Number(player.points).toLocaleString();
  $('energy').textContent = Math.floor(player.energy);
  $('energy-fill').style.width = `${Math.max(0, Math.min(100,player.energy / 5))}%`;
  $('streak').textContent = Number(player.streak || 0);
  $('tap').disabled = player.energy < 1;
  $('daily').disabled = player.lastDailyDate === lagosDay();
  if ($('upgrade')) {
    $('upgrade').disabled = player.points < upgradeCost();
    $('upgrade').textContent = `Upgrade tap · ${upgradeCost()} points`;
    $('tap-power').textContent = `${player.tapPower} point${player.tapPower === 1 ? '' : 's'} per tap`;
  }
  save();
}
function queueSync(path) {
  try {
    const queue = JSON.parse(localStorage.getItem(queueKey) || '[]');
    queue.push({path, at:Date.now()});
    localStorage.setItem(queueKey, JSON.stringify(queue.slice(-1000)));
  } catch {}
  retrySync();
}
async function callApi(path, method='GET') {
  const response = await fetch(`${API_BASE}${path}`,{method,headers:{'Content-Type':'application/json','X-Telegram-Init-Data':tg?.initData || ''}});
  let data; try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) throw new Error(data.error || 'Sync unavailable');
  return data;
}
let syncBusy = false;
async function retrySync() {
  if (syncBusy || !navigator.onLine) return;
  syncBusy = true;
  try {
    let queue = JSON.parse(localStorage.getItem(queueKey) || '[]');
    while (queue.length && navigator.onLine) {
      try { await callApi(queue[0].path, 'POST'); }
      catch { break; }
      queue.shift();
      localStorage.setItem(queueKey, JSON.stringify(queue));
    }
  } catch {} finally { syncBusy = false; }
}
async function loadInvite() {
  try {
    const data = await callApi('/api/me');
    if (data.referral_link) $('ref-link').textContent = data.referral_link;
  } catch {}
}
$('tap').addEventListener('click', () => {
  regenerate();
  if (player.energy < 1) { render(); return; }
  player.energy -= 1;
  player.points += Number(player.tapPower || 1);
  save(); render();
  $('notice').textContent = `+${player.tapPower} point${player.tapPower === 1 ? '' : 's'} · saved on this device`;
  queueSync('/api/tap');
});
$('daily').addEventListener('click', () => {
  const today = lagosDay();
  if (player.lastDailyDate === today) { render(); return; }
  player.streak = player.lastDailyDate === previousDay(today) ? Number(player.streak || 0) + 1 : 1;
  player.lastDailyDate = today;
  player.points += DAILY_BONUS;
  save(); render();
  $('notice').textContent = `Daily bonus claimed: +${DAILY_BONUS} points`;
  queueSync('/api/daily');
});
if ($('upgrade')) $('upgrade').addEventListener('click', () => {
  const cost = upgradeCost();
  if (player.points < cost) return;
  player.points -= cost;
  player.tapPower = Number(player.tapPower || 1) + 1;
  save(); render();
  $('notice').textContent = `Tap upgraded: ${player.tapPower} points per tap`;
});
$('share').addEventListener('click',async()=>{
  const link=$('ref-link').textContent;
  if (!link.startsWith('https://t.me/')) { $('notice').textContent='Personal invite link is unavailable while server sync is offline.'; return; }
  const shareUrl=`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent('join me on OrionTap and mine free points')}`;
  if (tg?.openTelegramLink) tg.openTelegramLink(shareUrl);
  else if (navigator.share) { try { await navigator.share({title:'Join OrionTap',text:'Mine free OrionTap points with me',url:link}); } catch {} }
  else { try { await navigator.clipboard.writeText(link); $('notice').textContent='Invite link copied.'; } catch { $('notice').textContent=link; } }
});
window.addEventListener('online', retrySync);
setInterval(() => { render(); retrySync(); }, 5000);
render();
$('notice').textContent = 'Ready to mine. Points save on this device; server sync retries in the background.';
loadInvite();
retrySync();
