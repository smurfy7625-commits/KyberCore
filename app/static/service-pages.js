const KYBER_SERVICE_GROUPS = {
  media_servers: ['plex','jellyfin','emby','navidrome','airsonic','audiobookshelf','komga','calibre-web','kavita'],
  media_automation: ['sonarr','radarr','lidarr','bazarr','readarr','whisparr','prowlarr','recyclarr','kometa','tdarr','fileflows'],
  media_discovery: ['seerr','overseerr','jellyseerr','ombi','tautulli'],
  downloads: ['transmission','qbittorrent','qbit','deluge','sabnzbd','nzbget','rtorrent','aria2','pyload','jdownloader'],
  infrastructure: ['gluetun','cloudflare','cloudflared','traefik','nginx','nginx-proxy-manager','portainer','watchtower','docker-socket-proxy'],
  home: ['homeassistant','home-assistant','homarr','homepage','heimdall','aura'],
  ai: ['ollama','open-webui','n8n']
};

let KYBER_SERVICE_CACHE = [];

function kyberServiceKey(row){
  return ((row.name || '') + ' ' + (row.image || '')).toLowerCase();
}

function matchesAnyService(row, names){
  const key = kyberServiceKey(row);
  return names.some(name => key.includes(name));
}

function serviceCategory(row){
  for(const [group,names] of Object.entries(KYBER_SERVICE_GROUPS)){
    if(matchesAnyService(row,names)) return group;
  }
  return 'other';
}

function serviceWebPort(row){
  const ports = Array.isArray(row.ports) ? row.ports : [];
  const preferred = [80,443,3000,32400,8096,5055,8989,7878,8686,6767,9696,9091,8080,8112,8085,7575,8123,11434];

  for(const cp of preferred){
    const hit = ports.find(p => Number(String(p.container || '').split('/')[0]) === cp && p.host_port);
    if(hit) return String(hit.host_port);
  }

  const first = ports.find(p => p.host_port);
  return first ? String(first.host_port) : '';
}

function serviceOpenUrl(row){
  const port = serviceWebPort(row);
  if(!port) return '';
  return window.location.protocol + '//' + window.location.hostname + ':' + port;
}

function serviceCard(row){
  const running = row.status === 'running';
  const openUrl = serviceOpenUrl(row);
  const cpu = row.stats_updated ? Number(row.cpu_percent || 0).toFixed(1) + '% CPU' : 'CPU pending';
  const memory = row.stats_updated ? Number(row.memory_mb || 0).toFixed(1) + ' MB RAM' : 'RAM pending';

  return '<article class="service-card">' +
    '<div class="service-card-top"><div><h3>' + esc(row.name) + '</h3><small>' + esc(row.image || '') + '</small></div>' +
    '<span class="service-state ' + (running ? 'running' : 'stopped') + '">' + esc(row.status || 'unknown') + '</span></div>' +
    '<div class="service-stats"><span>' + esc(cpu) + '</span><span>' + esc(memory) + '</span>' +
    (serviceWebPort(row) ? '<span>Web port ' + esc(serviceWebPort(row)) + '</span>' : '<span>No published web port</span>') +
    '</div><div class="service-actions">' +
    (openUrl ? '<button onclick="window.open(\'' + esc(openUrl) + '\',\'_blank\',\'noopener,noreferrer\')">OPEN</button>' : '') +
    '<button onclick="act(\'' + esc(row.name) + '\',\'' + (running ? 'restart' : 'start') + '\')">' + (running ? 'RESTART' : 'START') + '</button>' +
    (running ? '<button onclick="act(\'' + esc(row.name) + '\',\'stop\')">STOP</button>' : '') +
    '<button onclick="logs(\'' + esc(row.name) + '\')">LOGS</button>' +
    '<button onclick="inspectC(\'' + esc(row.name) + '\')">INSPECT</button>' +
    '</div></article>';
}

function serviceSection(title, subtitle, rows, targetId){
  const target = document.querySelector('#' + targetId);
  if(!target) return;

  target.innerHTML =
    '<div class="service-section-head"><div><h2>' + esc(title) + '</h2><p>' + esc(subtitle) + '</p></div><span>' + rows.length + ' detected</span></div>' +
    (rows.length
      ? '<div class="service-grid">' + rows.map(serviceCard).join('') + '</div>'
      : '<div class="panel muted">No matching services detected.</div>');
}

function summaryCards(rows, targetId){
  const target = document.querySelector('#' + targetId);
  if(!target) return;
  const running = rows.filter(x => x.status === 'running').length;
  const stopped = rows.length - running;
  const withWeb = rows.filter(x => serviceWebPort(x)).length;

  target.innerHTML =
    '<div class="service-summary-card"><small>DETECTED</small><strong>' + rows.length + '</strong></div>' +
    '<div class="service-summary-card"><small>RUNNING</small><strong>' + running + '</strong></div>' +
    '<div class="service-summary-card"><small>STOPPED</small><strong>' + stopped + '</strong></div>' +
    '<div class="service-summary-card"><small>WEB UIs</small><strong>' + withWeb + '</strong></div>';
}

async function loadKyberServiceCache(){
  KYBER_SERVICE_CACHE = await api('/api/containers');
  return KYBER_SERVICE_CACHE;
}

async function loadMedia(){
  const rows = await loadKyberServiceCache();
  const servers = rows.filter(x => serviceCategory(x) === 'media_servers');
  const automation = rows.filter(x => serviceCategory(x) === 'media_automation');
  const discovery = rows.filter(x => serviceCategory(x) === 'media_discovery');
  const all = [...servers, ...automation, ...discovery];

  summaryCards(all, 'mediaSummary');
  serviceSection('Media Servers','Playback and library front ends such as Plex, Jellyfin, Emby, Navidrome, and similar services.',servers,'mediaServers');
  serviceSection('Library Automation','Automation and organization tools such as Sonarr, Radarr, Lidarr, Bazarr, Prowlarr, Kometa, and similar services.',automation,'mediaAutomation');
  serviceSection('Requests & Discovery','Request, discovery, and analytics tools such as Seerr, Jellyseerr, Overseerr, Ombi, and Tautulli.',discovery,'mediaDiscovery');
}

async function loadDownloads(){
  const rows = await loadKyberServiceCache();
  const downloads = rows.filter(x => serviceCategory(x) === 'downloads');
  summaryCards(downloads, 'downloadSummary');
  serviceSection('Download Clients','Torrent and Usenet clients detected from the Docker container inventory.',downloads,'downloadClients');
}

function serviceGroupTitle(group){
  return ({
    media_servers:'Media Servers',
    media_automation:'Media Automation',
    media_discovery:'Requests & Discovery',
    downloads:'Downloads',
    infrastructure:'Infrastructure',
    home:'Home & Dashboards',
    ai:'Automation & AI',
    other:'Other Services'
  })[group] || group;
}

function renderAllServices(){
  const q = (document.querySelector('#serviceSearch')?.value || '').trim().toLowerCase();
  const rows = KYBER_SERVICE_CACHE.filter(row => !q || kyberServiceKey(row).includes(q));
  summaryCards(rows, 'serviceSummary');

  const groups = {};
  for(const row of rows){
    const category = serviceCategory(row);
    (groups[category] ||= []).push(row);
  }

  const order = ['media_servers','media_automation','media_discovery','downloads','infrastructure','home','ai','other'];
  const target = document.querySelector('#serviceGroups');
  target.innerHTML = order
    .filter(group => groups[group]?.length)
    .map(group =>
      '<section class="service-group"><div class="service-section-head"><div><h2>' +
      esc(serviceGroupTitle(group)) + '</h2></div><span>' + groups[group].length + ' services</span></div>' +
      '<div class="service-grid">' + groups[group].map(serviceCard).join('') + '</div></section>'
    ).join('') || '<div class="panel muted">No services match your search.</div>';
}

async function loadServices(){
  await loadKyberServiceCache();
  renderAllServices();
}

const kyberOriginalRefreshPage = window.refreshPage;
window.refreshPage = async function(){
  if(CURRENT === 'media'){
    try { await loadMedia(); } catch(e){ console.error(e); alert(e.message); }
    return;
  }
  if(CURRENT === 'downloads'){
    try { await loadDownloads(); } catch(e){ console.error(e); alert(e.message); }
    return;
  }
  if(CURRENT === 'services'){
    try { await loadServices(); } catch(e){ console.error(e); alert(e.message); }
    return;
  }
  return kyberOriginalRefreshPage();
};
