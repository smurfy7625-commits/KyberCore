const $=s=>document.querySelector(s);let APPS=[];let APP_CATALOG_ERRORS=[];let CURRENT='dashboard';
async function api(u,o){let r=await fetch(u,o),t=await r.text(),j;try{j=JSON.parse(t)}catch{j={detail:t}}if(!r.ok)throw Error(typeof j.detail==='string'?j.detail:t);return j}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function showPage(id){CURRENT=id;document.querySelectorAll('.page').forEach(x=>x.hidden=true);$('#'+id).hidden=false;document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.page===id));$('#pageTitle').textContent=id.toUpperCase().replace('DASHBOARD','COMMAND CENTER');refreshPage()}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>showPage(b.dataset.page));
function pct(v){return Math.max(0,Math.min(100,Number(v)||0))}function metric(n,v,p){return `<div class=metric><small>${n}</small><strong>${v}</strong><div class=bar><i style="width:${pct(p)}%"></i></div></div>`}
async function loadDashboard(){
    const safe = async (url, fallback) => {
        try { return await api(url); }
        catch(e) {
            console.error("Dashboard API failure:", url, e);
            return fallback;
        }
    };

    const [st,c,disks,n,a] = await Promise.all([
        safe('/api/status', {}),
        safe('/api/containers', []),
        safe('/api/storage', []),
        safe('/api/notifications', []),
        safe('/api/audit', [])
    ]);

    $('#host').textContent =
        `${st.hostname || 'Server'} • v${st.version || '1.0'}`;

    $('#metrics').innerHTML =
        metric('CPU',
            (st.cpu_percent ?? 0) + '%',
            st.cpu_percent ?? 0) +
        metric('Memory',
            (st.memory_percent ?? 0) + '%',
            st.memory_percent ?? 0) +
        metric('Storage',
            (st.storage_used_gb ?? 0) + ' / ' +
            (st.storage_total_gb ?? 0) + ' GB',
            st.storage_total_gb
                ? st.storage_used_gb / st.storage_total_gb * 100
                : 0) +
        metric('Containers',
            (st.containers_running ?? 0) + '/' +
            (st.containers_total ?? 0),
            st.containers_total
                ? st.containers_running / st.containers_total * 100
                : 0) +
        metric('Uptime',
            Math.floor((st.uptime_seconds ?? 0) / 86400) + ' days',
            60);

    $('#systemStatus').innerHTML =
        `<div class=statusline>
            <span>Docker Engine</span>
            <b>${c.length} containers</b>
            <span class=badge>ONLINE</span>
        </div>
        <div class=statusline>
            <span>Storage</span>
            <b>${st.storage_total_gb ?? 0} GB total</b>
            <span class=badge>ONLINE</span>
        </div>
        <div class=statusline>
            <span>Memory</span>
            <b>${st.memory_used_gb ?? 0}/${st.memory_total_gb ?? 0} GB</b>
            <span class=badge>ONLINE</span>
        </div>
        <div class=statusline>
            <span>System Load</span>
            <b>${Array.isArray(st.load)
                ? st.load.map(x => Number(x).toFixed(2)).join(' / ')
                : 'N/A'}</b>
            <span class=badge>ONLINE</span>
        </div>`;

    $('#recentActivity').innerHTML =
        a.length
        ? a.slice(0,6).map(x =>
            `<div class=statusline>
                <span>${esc(x.action)}</span>
                <span class=muted>${esc(x.detail)}</span>
                <span>${esc(x.ts?.slice(11,19) || '')}</span>
            </div>`
          ).join('')
        : '<span class=muted>No changes recorded yet.</span>';

    $('#storageMini').innerHTML =
        disks.length
        ? disks.slice(0,5).map(x =>
            `<div class=statusline>
                <span>${esc(x.name)}</span>
                <span>${x.used_gb}/${x.total_gb} GB</span>
                <span>${x.percent}%</span>
            </div>`
          ).join('')
        : '<span class=muted>No storage information available.</span>';

    $('#notifications').innerHTML =
        n.length
        ? n.map(x =>
            `<div class=statusline>
                <span class=${x.level === 'warning' ? 'warn' : ''}>
                    ${esc(x.message)}
                </span>
            </div>`
          ).join('')
        : '<span class=muted>No active alerts.</span>';
}
function containerRows(c){
    if(!Array.isArray(c) || !c.length){
        return '<div class="muted">No containers found.</div>';
    }

    return `
        <div class="row container-header">
            <b>CONTAINER</b>
            <b>RESOURCES</b>
            <b>STATUS</b>
            <b>ACTIONS</b>
        </div>
    ` + c.map(x => {
        const running = x.status === 'running';

        const cpu =
            x.stats_updated
            ? `${Number(x.cpu_percent || 0).toFixed(1)}% CPU`
            : 'CPU pending';

        const memory =
            x.stats_updated
            ? `${Number(x.memory_mb || 0).toFixed(1)} MB RAM`
            : 'RAM pending';

        const health =
            x.health
            ? `<span class="badge">${esc(x.health)}</span>`
            : '';

        const ports = Array.isArray(x.ports)
            ? x.ports
                .filter(p => p.host_port)
                .map(p =>
                    `${esc(p.host_port)}→${esc(p.container)}`
                )
                .join(' • ')
            : '';

        const primaryAction =
            running ? 'restart' : 'start';

        const primaryLabel =
            running ? 'RESTART' : 'START';

        const stopButton = running
            ? `<button onclick="act('${esc(x.name)}','stop')">STOP</button>`
            : '';

        return `
            <div class="row container-row">

                <div>
                    <b>${esc(x.name)}</b>

                    <small class="muted">
                        <br>${esc(x.image)}
                    </small>

                    ${ports
                        ? `<small class="muted">
                            <br>Ports: ${ports}
                           </small>`
                        : ''}
                </div>

                <div>
                    <strong>${cpu}</strong>
                    <small class="muted">
                        <br>${memory}
                    </small>
                </div>

                <div>
                    <span class="badge">
                        ${esc(x.status)}
                    </span>

                    ${health}

                    ${x.restart_count
                        ? `<small class="muted">
                            <br>Restarts:
                            ${Number(x.restart_count)}
                           </small>`
                        : ''}
                </div>

                <div class="container-actions">

                    <button onclick="act(
                        '${esc(x.name)}',
                        '${primaryAction}'
                    )">
                        ${primaryLabel}
                    </button>

                    ${stopButton}

                    <button onclick="logs(
                        '${esc(x.name)}'
                    )">
                        LOGS
                    </button>

                    <button onclick="inspectC(
                        '${esc(x.name)}'
                    )">
                        INSPECT
                    </button>

                </div>

            </div>
        `;
    }).join('');
}


async function loadContainers(){
    const target = $('#containerRows');

    target.innerHTML =
        '<span class="muted">Loading containers…</span>';

    try {
        const c = await api('/api/containers');

        target.innerHTML =
            containerRows(c);

    } catch(e) {
        console.error(e);

        target.innerHTML =
            `<span class="warn">
                Unable to load containers:
                ${esc(e.message)}
             </span>`;
    }
}


async function act(n,a){
    if(!confirm(`${a.toUpperCase()} ${n}?`)){
        return;
    }

    try {
        await api(
            `/api/containers/${encodeURIComponent(n)}/${a}`,
            {method:'POST'}
        );

        await loadContainers();

    } catch(e) {
        alert(e.message);
    }
}


async function logs(n){
    try {
        const x = await api(
            `/api/containers/${encodeURIComponent(n)}/logs`
        );

        openModal(`
            <h2>${esc(n)} LOGS</h2>
            <pre>${esc(x.logs)}</pre>
        `);

    } catch(e) {
        alert(e.message);
    }
}


async function inspectC(n){
    try {
        const x = await api(
            `/api/containers/${encodeURIComponent(n)}/inspect`
        );

        openModal(`
            <h2>${esc(n)} INSPECT</h2>
            <pre>${esc(
                JSON.stringify(x,null,2)
            )}</pre>
        `);

    } catch(e) {
        alert(e.message);
    }
}


async function loadApps(refresh=false){
    $('#appgrid').innerHTML =
        '<span class=muted>Loading catalogs…</span>';

    const catalogs = await Promise.allSettled([
        api('/api/apps/linuxserver?refresh=' + refresh),
        api('/api/apps/awesome-selfhosted?refresh=' + refresh)
    ]);

    APP_CATALOG_ERRORS = [];
    APPS = [];

    if(catalogs[0].status === 'fulfilled'){
        APPS.push(...catalogs[0].value.map(item => ({
            ...item,
            source: 'linuxserver',
            source_label: 'LinuxServer'
        })));
    } else {
        APP_CATALOG_ERRORS.push(
            'LinuxServer: ' + catalogs[0].reason.message
        );
    }

    if(catalogs[1].status === 'fulfilled'){
        APPS.push(...catalogs[1].value.map(item => ({
            ...item,
            source: 'awesome-selfhosted',
            source_label: 'Awesome Selfhosted'
        })));
    } else {
        APP_CATALOG_ERRORS.push(
            'Awesome Selfhosted: ' + catalogs[1].reason.message
        );
    }

    renderApps();
}

function renderApps(){
    const query = ($('#appSearch').value || '')
        .trim()
        .toLowerCase();
    const source = $('#appSource').value;

    const matches = APPS.filter(item => {
        if(source !== 'all' && item.source !== source){
            return false;
        }

        const text = [
            item.name,
            item.description,
            item.category,
            ...(item.platforms || []),
            ...(item.licenses || [])
        ].join(' ').toLowerCase();

        return !query || text.includes(query);
    });

    const limit = query ? 500 : 250;
    const visible = matches.slice(0, limit);
    const countText =
        `${matches.length} application${matches.length === 1 ? '' : 's'}` +
        (matches.length > visible.length
            ? ` • showing first ${visible.length}; search to narrow results`
            : '') +
        (APP_CATALOG_ERRORS.length
            ? ` • ${APP_CATALOG_ERRORS.join(' • ')}`
            : '');

    $('#appCount').textContent = countText;

    $('#appgrid').innerHTML = visible.length
        ? visible.map(item => {
            const sourceBadge =
                `<span class=badge>${esc(item.source_label)}</span>`;
            const metadata = item.source === 'awesome-selfhosted'
                ? [
                    item.category,
                    (item.platforms || []).join(' / '),
                    (item.licenses || []).join(' / ')
                  ].filter(Boolean).join(' • ')
                : (item.version || '');

            let actions = '';

            if(item.source === 'linuxserver'){
                actions = item.installed
                    ? '<span class=badge>INSTALLED</span>'
                    : `<button onclick="appDetails('${esc(item.slug)}')">INSTALL</button>`;
                actions += ` <a href="${esc(item.docs)}" target=_blank rel="noopener noreferrer">Docs ↗</a>`;
            } else {
                if(item.installed){
                    actions += '<span class=badge>INSTALLED</span> ';
                }

                actions += `<a href="${esc(item.website)}" target=_blank rel="noopener noreferrer">Project ↗</a>`;

                if(item.source_code && item.source_code !== item.website){
                    actions += ` <a href="${esc(item.source_code)}" target=_blank rel="noopener noreferrer">Source ↗</a>`;
                }
            }

            return `<div class=app>
                <h3>${esc(item.name)}</h3>
                ${sourceBadge}
                <p class=muted>${esc(item.description)}</p>
                <small>${esc(metadata)}</small>
                <div class=buttons>${actions}</div>
            </div>`;
        }).join('')
        : '<span class=muted>No matching applications.</span>';
}
async function appDetails(s){let x=await api('/api/apps/linuxserver/'+s),cfg=x.config||{},ports=Array.isArray(cfg.ports)?cfg.ports:[],paths=Array.isArray(cfg.volumes)?cfg.volumes:[];let h=`<h2>Install ${esc(x.name)}</h2><p>${esc(x.description)}</p><p class=muted>${esc(x.image)}</p>`;h+=ports.map(p=>{let i=String(p.internal||'').trim(),e=String(p.external||i).trim();return i?`<div class=field><label>Host port → ${i}</label><input class=port data-port="${i}" type=number value="${e}"></div>`:''}).join('');h+=paths.map(p=>{let t=String(p.path||'').trim();if(!t.startsWith('/'))return'';let d=t==='/config'?`/Compose/${s}/config`:'';return `<div class=field><label>Host path → ${esc(t)}</label><input class=path data-path="${esc(t)}" value="${d}" placeholder="/srv/..."></div>`}).join('');h+=`<button onclick="installApp('${s}')">CONFIRM INSTALL</button>`;openModal(h)}async function installApp(s){
    let host_ports={};
    let paths={};

    document.querySelectorAll('.port').forEach(x=>{
        host_ports[x.dataset.port]=Number(x.value);
    });

    document.querySelectorAll('.path').forEach(x=>{
        paths[x.dataset.path]=x.value;
    });

    if(!confirm(`Install ${s}?`))return;

    const progress=(percent,title,detail)=>{
        const bar=document.getElementById('installProgressBar');
        const pct=document.getElementById('installProgressPercent');
        const status=document.getElementById('installProgressStatus');
        const info=document.getElementById('installProgressDetail');

        if(bar)bar.style.width=percent+'%';
        if(pct)pct.textContent=percent+'%';
        if(status)status.textContent=title;
        if(info)info.textContent=detail||'';
    };

    const h=`
        <h2>Installing ${esc(s)}</h2>

        <p id="installProgressStatus">
            Preparing installation...
        </p>

        <div style="
            width:100%;
            height:18px;
            border:1px solid rgba(120,220,255,.35);
            border-radius:9px;
            overflow:hidden;
            margin:18px 0 8px 0;
        ">
            <div
                id="installProgressBar"
                style="
                    width:10%;
                    height:100%;
                    background:currentColor;
                    transition:width .4s ease;
                ">
            </div>
        </div>

        <div
            id="installProgressPercent"
            class="muted"
            style="text-align:right">
            10%
        </div>

        <p
            id="installProgressDetail"
            class="muted">
            Checking installation settings.
        </p>

        <div id="installProgressSteps">
            <p>● Preparing installation</p>
            <p id="stepDeploy">○ Creating and starting container</p>
            <p id="stepVerify">○ Verifying installation</p>
        </div>
    `;

    openModal(h);

    try{
        progress(
            20,
            'Validating configuration...',
            'Checking paths, ports and application settings.'
        );

        await new Promise(r=>setTimeout(r,250));

        progress(
            40,
            'Installing application...',
            'Creating the Compose stack and pulling the Docker image. This can take several minutes.'
        );

        const deployStep=document.getElementById('stepDeploy');
        if(deployStep){
            deployStep.textContent='● Creating and starting container';
        }

        await api(
            `/api/apps/linuxserver/${s}/install`,
            {
                method:'POST',
                headers:{
                    'Content-Type':'application/json'
                },
                body:JSON.stringify({
                    host_ports,
                    paths,
                    env:{}
                })
            }
        );

        if(deployStep){
            deployStep.textContent='✓ Container deployment completed';
        }

        progress(
            85,
            'Verifying installation...',
            'Checking the resulting container.'
        );

        const verifyStep=document.getElementById('stepVerify');
        if(verifyStep){
            verifyStep.textContent='● Verifying installation';
        }

        await new Promise(r=>setTimeout(r,1500));

        let containers=[];

        try{
            containers=await api('/api/containers');
        }catch(e){
            containers=[];
        }

        const installed=containers.find(
            x=>x.name===s
        );

        if(installed && installed.status==='running'){
            if(verifyStep){
                verifyStep.textContent='✓ Container is running';
            }

            progress(
                100,
                'Installation complete',
                `${s} is running successfully.`
            );
        }else if(installed){
            if(verifyStep){
                verifyStep.textContent=
                    `⚠ Container status: ${installed.status}`;
            }

            progress(
                100,
                'Installation completed',
                `${s} was created. Current status: ${installed.status}.`
            );
        }else{
            if(verifyStep){
                verifyStep.textContent='✓ Installation request completed';
            }

            progress(
                100,
                'Installation complete',
                'The installation request completed successfully.'
            );
        }

        const steps=document.getElementById(
            'installProgressSteps'
        );

        if(steps){
            steps.insertAdjacentHTML(
                'afterend',
                `<p style="margin-top:18px">
                    <button onclick="modal.hidden=true;loadApps()">
                        CLOSE
                    </button>
                </p>`
            );
        }

    }catch(e){
        const deployStep=document.getElementById('stepDeploy');

        if(deployStep){
            deployStep.textContent='✕ Installation failed';
        }

        progress(
            100,
            'Installation failed',
            e.message || 'Unknown installation error'
        );

        const steps=document.getElementById(
            'installProgressSteps'
        );

        if(steps){
            steps.insertAdjacentHTML(
                'afterend',
                `<p style="margin-top:18px">
                    <button onclick="modal.hidden=true">
                        CHANGE SETTINGS
                    </button>
                </p>`
            );
        }
    }
}
async function loadCompose(){
    const target = $('#composeRows');

    target.innerHTML =
        '<span class="muted">Loading Compose projects…</span>';

    try {
        const projects = await api('/api/compose');

        target.innerHTML = projects.map(x => {

            const status = x.status || 'unknown';

            const running =
                Number(x.containers_running || 0);

            const total =
                Number(x.containers_total || 0);

            const services =
                Array.isArray(x.containers)
                ? x.containers.map(c =>
                    `${esc(c.service || c.name)}: ` +
                    `${esc(c.status || 'unknown')}`
                  ).join('<br>')
                : '';

            return `
                <div class="tile">

                    <div class="panelhead">
                        <h3>${esc(x.name)}</h3>

                        <span class="badge">
                            ${esc(status)}
                        </span>
                    </div>

                    <p class="muted">
                        ${esc(x.file)}
                    </p>

                    <p>
                        <b>${running}/${total}</b>
                        containers running
                    </p>

                    ${
                        services
                        ? `<small class="muted">
                               ${services}
                           </small>`
                        : `<small class="muted">
                               No active containers
                           </small>`
                    }

                    <div class="buttons"
                         style="margin-top:14px">

                        <button
                            onclick="editCompose('${esc(x.name)}')">
                            EDIT
                        </button>

                        <button
                            onclick="composeAct('${esc(x.name)}','up')">
                            UP
                        </button>

                        <button
                            onclick="composeAct('${esc(x.name)}','restart')">
                            RESTART
                        </button>

                        <button
                            onclick="composeAct('${esc(x.name)}','pull')">
                            PULL
                        </button>

                        <button
                            onclick="composeAct('${esc(x.name)}','down')">
                            DOWN
                        </button>

                    </div>
                </div>
            `;

        }).join('') ||
        '<span class="muted">No Compose projects found.</span>';

    } catch(e) {
        console.error(e);

        target.innerHTML =
            `<span class="warn">
                Unable to load Compose projects:
                ${esc(e.message)}
             </span>`;
    }
}


async function editCompose(n){
    try {
        const x =
            await api(
                '/api/compose/' +
                encodeURIComponent(n)
            );

        openModal(`
            <h2>${esc(n)}</h2>

            <textarea
                id="composeEditor"
                style="min-height:55vh"
            >${esc(x.content)}</textarea>

            <div class="buttons">

                <button
                    onclick="saveCompose('${esc(n)}',false)">
                    SAVE
                </button>

                <button
                    onclick="saveCompose('${esc(n)}',true)">
                    SAVE & DEPLOY
                </button>

            </div>
        `);

    } catch(e) {
        alert(e.message);
    }
}


async function saveCompose(n,deploy){

    const content =
        $('#composeEditor').value;

    try {

        await api(
            `/api/compose/${encodeURIComponent(n)}/validate`,
            {
                method:'POST',

                headers:{
                    'Content-Type':
                        'application/json'
                },

                body:JSON.stringify({
                    content,
                    deploy:false
                })
            }
        );

        if(
            deploy &&
            !confirm(
                'Deploy this validated Compose file?'
            )
        ){
            return;
        }

        await api(
            `/api/compose/${encodeURIComponent(n)}`,
            {
                method:'PUT',

                headers:{
                    'Content-Type':
                        'application/json'
                },

                body:JSON.stringify({
                    content,
                    deploy
                })
            }
        );

        alert(
            deploy
            ? 'Saved and deployed.'
            : 'Saved.'
        );

        modal.hidden = true;

        await loadCompose();

    } catch(e) {
        alert(e.message);
    }
}


async function composeAct(n,a){

    let message =
        `${a.toUpperCase()} Compose project "${n}"?`;

    if(a === 'down'){
        message =
            `DOWN will stop and remove the containers ` +
            `for "${n}". Volumes are not removed. Continue?`;
    }

    if(!confirm(message)){
        return;
    }

    try {

        const result =
            await api(
                `/api/compose/${encodeURIComponent(n)}/${a}`,
                {
                    method:'POST'
                }
            );

        alert(
            result.output
            ? `Complete\n\n${result.output}`
            : 'Complete'
        );

        /*
         * Give the backend inventory cache a moment
         * to observe Docker changes.
         */
        await new Promise(
            resolve =>
                setTimeout(resolve,1500)
        );

        await loadCompose();

    } catch(e) {
        alert(e.message);
    }
}


async function loadStorage(){let a=await api('/api/storage');$('#storageRows').innerHTML=a.map(x=>`<div class=tile><h3>${esc(x.name)}</h3><strong>${x.used_gb} / ${x.total_gb} GB</strong><p>${x.percent}% used • ${x.free_gb} GB free</p><div class=bar><i style="width:${x.percent}%"></i></div><small class=muted>${esc(x.path)}</small></div>`).join('')}async function loadSmart(){let x=await api('/api/storage/smart');$('#smartOutput').textContent=x.available?(x.devices.map(d=>d.device+'\n'+d.output).join('\n')):('SMART unavailable: '+x.detail)}
async function loadNetwork(){let x=await api('/api/network');let h='<div class=twocol><div class=panel><h2>Interfaces</h2>';for(let [k,v] of Object.entries(x.interfaces))h+=`<div class=statusline><b>${esc(k)}</b><span>${esc(v.map(a=>a.address).join(', '))}</span></div>`;h+='</div><div class=panel><h2>Docker Networks</h2>'+x.docker_networks.map(n=>`<div class=statusline><b>${esc(n.name)}</b><span>${esc(n.driver)}</span><span>${n.containers.length} containers</span></div>`).join('')+'</div></div><div class=panel><h2>Listening Ports</h2>'+x.listeners.map(l=>`<div class=statusline><span>${esc(l.ip)}</span><b>${l.port}</b><span>PID ${l.pid??'-'}</span></div>`).join('')+'</div>';$('#networkBody').innerHTML=h}
async function loadFiles(){let p=$('#filePath').value,x=await api('/api/files?path='+encodeURIComponent(p));$('#filePath').value=x.path;$('#fileRows').innerHTML=`<div class=row><b>..</b><span></span><span></span><span><button onclick="fileUp()">UP</button></span></div>`+x.items.map(i=>`<div class=row><b>${i.dir?'▣':'▤'} ${esc(i.name)}</b><span>${i.dir?'Directory':Math.round(i.size/1024)+' KB'}</span><span></span><span><button onclick="${i.dir?`openDir('${esc(i.path)}')`:`editFile('${esc(i.path)}')`}">${i.dir?'OPEN':'EDIT'}</button></span></div>`).join('')}function openDir(p){$('#filePath').value=p;loadFiles()}function fileUp(){let p=$('#filePath').value.split('/').filter(Boolean);p.pop();$('#filePath').value='/'+p.join('/');loadFiles()}async function editFile(p){try{let x=await api('/api/file?path='+encodeURIComponent(p));openModal(`<h2>${esc(p)}</h2><textarea id=fileEditor style="min-height:55vh">${esc(x.content)}</textarea><button onclick="saveFile('${esc(p)}')">SAVE WITH BACKUP</button>`)}catch(e){alert(e.message)}}async function saveFile(p){if(!confirm('Save this file? A timestamped backup will be created first.'))return;await api('/api/file',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:p,content:$('#fileEditor').value})});modal.hidden=true}
async function loadBackups(){
    const [backups,targets] = await Promise.all([
        api('/api/backups'),
        api('/api/backups/targets')
    ]);

    const select = $('#backupContainer');

    if(select){
        const previous = select.value;

        select.innerHTML = targets.map(item =>
            `<option value="${esc(item.container)}">` +
            `${esc(item.container)} — ${esc(item.project)} ` +
            `(${item.config_mounts} config mount${item.config_mounts===1?'':'s'})` +
            `</option>`
        ).join('');

        if(
            previous &&
            targets.some(
                item => item.container === previous
            )
        ){
            select.value = previous;
        }
    }

    $('#backupRows').innerHTML = backups.map(item =>
        `<div class=row>` +
        `<b>${esc(item.container)}</b>` +
        `<span>` +
            `${Math.round(item.size/1024)} KB` +
            `<small class=muted>${new Date(item.modified*1000).toLocaleString()}</small>` +
        `</span>` +
        `<span>` +
            `${item.compose_files} config file${item.compose_files===1?'':'s'} • ` +
            `${item.config_mounts} config mount${item.config_mounts===1?'':'s'}` +
        `</span>` +
        `<span>` +
            `<button onclick="restoreBackup('${esc(item.name)}','${esc(item.container)}')">RESTORE</button> ` +
            `<button onclick="deleteBackup('${esc(item.name)}')">DELETE</button>` +
        `</span>` +
        `</div>`
    ).join('') || '<span class=muted>No container backups yet.</span>';
}

async function makeBackup(){
    const select = $('#backupContainer');

    if(!select || !select.value){
        alert('Select a Compose-managed container first.');
        return;
    }

    const container = select.value;

    if(!confirm(
        `Back up ${container}?\n\n` +
        'This is a CONTAINER CONFIGURATION backup only.\n\n' +
        'Kyber Core will briefly stop the container while copying ' +
        'its Compose/env files and mapped config folders, then start it again.\n\n' +
        'Media libraries, downloads, and general storage are NOT included.'
    )){
        return;
    }

    try{
        const result = await api(
            '/api/backups',
            {
                method:'POST',
                headers:{
                    'Content-Type':'application/json'
                },
                body:JSON.stringify({
                    container
                })
            }
        );

        alert(
            `Container backup created:\n${result.name}`
        );

        await loadBackups();

    }catch(e){
        alert(e.message);
    }
}

async function restoreBackup(name,container){
    if(!confirm(
        `Restore ${container} from this container backup?\n\n` +
        `${name}\n\n` +
        'Kyber Core will create a safety backup of the current ' +
        'container configuration first, stop the container, restore ' +
        'the saved configuration, and run Docker Compose.\n\n' +
        'Extra files that were created after the backup are NOT deleted.'
    )){
        return;
    }

    try{
        const result = await api(
            '/api/backups/' +
            encodeURIComponent(name) +
            '/restore',
            {
                method:'POST'
            }
        );

        alert(
            `Restore completed for ${container}.` +
            (
                result.safety_backup
                ? `\n\nSafety backup:\n${result.safety_backup}`
                : ''
            )
        );

        await loadBackups();

    }catch(e){
        alert(e.message);
    }
}

async function deleteBackup(name){
    if(!confirm(
        `Delete container backup?\n\n${name}`
    )){
        return;
    }

    try{
        await api(
            '/api/backups/' +
            encodeURIComponent(name),
            {
                method:'DELETE'
            }
        );

        await loadBackups();

    }catch(e){
        alert(e.message);
    }
}

async function loadUpdates(){
    const rows = await api('/api/updates');

    $('#updateRows').innerHTML = rows.map(item => {
        const target = item.project && item.service
            ? `${item.project} / ${item.service}`
            : 'No managed Compose target';
        const action = item.updatable
            ? `<button onclick="updateContainer('${esc(item.container)}',this)">UPDATE</button>`
            : `<button disabled title="${esc(item.reason)}">UNAVAILABLE</button>`;

        return `<div class=row>
            <b>${esc(item.container)}</b>
            <span>
                ${esc(item.image)}
                <small class=muted>${esc(
                    item.updatable
                        ? target
                        : item.reason
                )}</small>
            </span>
            <span class=badge>${esc(item.status)}</span>
            <span>${action}</span>
        </div>`;
    }).join('');
}

async function updateContainer(name, button){
    const confirmed = confirm(
        `Update ${name}?\n\n` +
        'Kyber Core will pull the configured image and run Compose ' +
        'up for only this service. If a newer image exists, this ' +
        'container will be recreated and may briefly be unavailable.'
    );

    if(!confirmed){
        return;
    }

    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = 'UPDATING…';

    try {
        const result = await api(
            `/api/containers/${encodeURIComponent(name)}/update`,
            {method: 'POST'}
        );
        alert(
            result.output
                ? `${result.note}\n\n${result.output}`
                : result.note
        );
        await loadUpdates();

    } catch(e) {
        alert(e.message);
        button.disabled = false;
        button.textContent = originalText;
    }
}
async function loadSecurity(){let x=await api('/api/security');$('#securityBody').innerHTML=`<div class=metrics>${metric('Exposed Ports',x.exposed_ports.length,x.exposed_ports.length?60:10)}${metric('Docker Socket',x.docker_socket_mounted?'Privileged':'No',x.docker_socket_mounted?80:10)}</div><div class=panel><h2>Externally Bound Ports</h2>${x.exposed_ports.map(p=>`<div class=statusline><b>${esc(p.container)}</b><span>${esc(p.host_ip)}:${esc(p.host_port)}</span><span>→ ${esc(p.container_port)}</span></div>`).join('')||'None'}</div><div class=panel><p class=warn>${esc(x.note)}</p></div>`}async function loadAudit(){let a=await api('/api/audit');$('#auditRows').innerHTML=a.map(x=>`<div class=row><b>${esc(x.action)}</b><span>${esc(x.detail)}</span><span>${esc(x.ts)}</span><span></span></div>`).join('')||'<span class=muted>No audit events yet.</span>'}
async function askAI(){let p=$('#aiPrompt').value;if(!p)return;$('#aiOutput').textContent='Analyzing…';try{let x=await api('/api/ai',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:p})});$('#aiOutput').textContent=x.response}catch(e){$('#aiOutput').textContent=e.message}}
async function loadSettings(){let x=await api('/api/settings');$('#serverName').value=x.server_name||'Kyber Core';$('#theme').value=x.theme||'cosmic'}async function saveSettings(){await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({server_name:$('#serverName').value,theme:$('#theme').value,setup_complete:true})});alert('Settings saved')}function completeSetup(){saveSettings()}
function openModal(h){$('#modalbody').innerHTML=h;modal.hidden=false}async function refreshPage(){let f={dashboard:loadDashboard,apps:()=>loadApps(false),containers:loadContainers,compose:loadCompose,storage:loadStorage,network:loadNetwork,files:loadFiles,backups:loadBackups,updates:loadUpdates,security:loadSecurity,logs:loadAudit,settings:loadSettings};if(f[CURRENT])try{await f[CURRENT]()}catch(e){console.error(e);alert(e.message)}}
loadDashboard();setInterval(()=>{if(CURRENT==='dashboard')loadDashboard()},15000);


async function logoutKyber(){
    try{
        await fetch(
            '/api/auth/logout',
            {
                method:'POST',
                credentials:'same-origin'
            }
        );
    }finally{
        window.location.href='/';
    }
}
