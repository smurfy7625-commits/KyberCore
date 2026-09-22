from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import docker, os, shutil, psutil, time, json, httpx, yaml, re, socket, tarfile, subprocess, threading, hashlib, hmac, base64, secrets


def omv_bridge_request(method, path, payload=None, timeout=30):
    """Call the local Kyber OMV bridge over its Unix domain socket."""
    import http.client
    import socket

    socket_path = os.getenv(
        "OMV_BRIDGE_SOCKET",
        "/run/kyber-omv/bridge.sock"
    )

    class UnixHTTPConnection(http.client.HTTPConnection):
        def __init__(self, unix_path, timeout=30):
            super().__init__("localhost", timeout=timeout)
            self.unix_path = unix_path

        def connect(self):
            self.sock = socket.socket(
                socket.AF_UNIX,
                socket.SOCK_STREAM
            )
            self.sock.settimeout(self.timeout)
            self.sock.connect(self.unix_path)

    body = None
    headers = {}

    if payload is not None:
        body = json.dumps(payload)
        headers["Content-Type"] = "application/json"

    conn = UnixHTTPConnection(
        socket_path,
        timeout=timeout
    )

    try:
        conn.request(
            method,
            path,
            body=body,
            headers=headers,
        )

        response = conn.getresponse()
        raw = response.read().decode(
            "utf-8",
            errors="replace"
        )

        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {"raw": raw}

        return response.status, data, raw

    finally:
        conn.close()


app=FastAPI(title="Kyber Core",version="1.0.0")
BASE=Path('/app'); CONFIG=BASE/'config'; CONFIG.mkdir(exist_ok=True)
COMPOSE_ROOT=Path(os.getenv('COMPOSE_ROOT','/host/Compose')).resolve(); STORAGE_ROOT=Path(os.getenv('STORAGE_ROOT','/host/srv')).resolve()
BACKUP_ROOT=Path(os.getenv('BACKUP_ROOT','/app/config/backups')).resolve(); BACKUP_ROOT.mkdir(parents=True,exist_ok=True)
PUID=os.getenv('PUID','1000'); PGID=os.getenv('PGID','100'); TZ=os.getenv('TZ','UTC'); OLLAMA_URL=os.getenv('OLLAMA_URL','').rstrip('/'); OLLAMA_MODEL=os.getenv('OLLAMA_MODEL','qwen3:4b')
CACHE=CONFIG/'linuxserver-api-cache.json'; LSAPI='https://api.linuxserver.io/api/v1/images'; SETTINGS=CONFIG/'settings.json'; AUDIT=CONFIG/'audit.jsonl'; HISTORY=CONFIG/'history.jsonl'
AWESOME_CACHE=CONFIG/'awesome-selfhosted-cache.json'
AWESOME_README='https://raw.githubusercontent.com/awesome-selfhosted/awesome-selfhosted/master/README.md'
AWESOME_CATALOG='https://github.com/awesome-selfhosted/awesome-selfhosted'
AWESOME_LICENSE='https://creativecommons.org/licenses/by-sa/3.0/'
client=docker.from_env(); app.mount('/static',StaticFiles(directory=BASE/'app/static'),name='static')

# ============================================================
# KYBER CORE AUTHENTICATION
# ============================================================

AUTH_FILE = CONFIG / 'auth.json'
AUTH_COOKIE = 'kyber_session'

AUTH_SESSION_SECONDS = int(
    os.getenv(
        'AUTH_SESSION_SECONDS',
        '43200'
    )
)

AUTH_COOKIE_SECURE = (
    os.getenv(
        'AUTH_COOKIE_SECURE',
        'false'
    ).lower()
    in ('1', 'true', 'yes', 'on')
)

AUTH_SESSIONS = {}
AUTH_SESSION_LOCK = threading.Lock()

AUTH_FAILURES = {}
AUTH_FAILURE_LOCK = threading.Lock()

AUTH_FAILURE_WINDOW = 300
AUTH_FAILURE_LIMIT = 5


class AuthSetupReq(BaseModel):
    username: str
    password: str
    password_confirm: str


class AuthLoginReq(BaseModel):
    username: str
    password: str


def omv_required_status():
    socket_path = os.getenv(
        'OMV_BRIDGE_SOCKET',
        '/run/kyber-omv/bridge.sock'
    )

    if not os.path.exists(socket_path):
        return {
            'ready': False,
            'detail':
                'OpenMediaVault bridge socket is not available'
        }

    try:
        status, data, raw = omv_bridge_request(
            'GET',
            '/health',
            timeout=5,
        )

        if status != 200:
            return {
                'ready': False,
                'detail':
                    f'OpenMediaVault bridge returned HTTP {status}'
            }

        return {
            'ready': True,
            'detail': 'OpenMediaVault connected'
        }

    except Exception as exc:
        return {
            'ready': False,
            'detail':
                f'OpenMediaVault bridge unavailable: {exc}'
        }


def auth_account():
    if not AUTH_FILE.exists():
        return None

    try:
        data = json.loads(
            AUTH_FILE.read_text(
                encoding='utf-8'
            )
        )

        if not isinstance(data, dict):
            return None

        if not data.get('username'):
            return None

        if not data.get('password_hash'):
            return None

        if not data.get('salt'):
            return None

        return data

    except Exception:
        return None


def auth_write_account(data):
    temp = AUTH_FILE.with_suffix('.tmp')

    temp.write_text(
        json.dumps(
            data,
            indent=2
        ),
        encoding='utf-8'
    )

    os.chmod(
        temp,
        0o600
    )

    temp.replace(
        AUTH_FILE
    )

    os.chmod(
        AUTH_FILE,
        0o600
    )


def auth_hash_password(
    password,
    salt=None,
):
    if salt is None:
        salt = os.urandom(16)

    digest = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        600000,
    )

    return (
        base64.b64encode(
            salt
        ).decode('ascii'),
        base64.b64encode(
            digest
        ).decode('ascii'),
    )


def auth_verify_password(
    password,
    account,
):
    try:
        salt = base64.b64decode(
            account['salt']
        )

        expected = base64.b64decode(
            account['password_hash']
        )

        actual = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            600000,
        )

        return hmac.compare_digest(
            expected,
            actual,
        )

    except Exception:
        return False


def auth_new_session(username):
    token = secrets.token_urlsafe(48)

    expires = (
        time.time()
        + AUTH_SESSION_SECONDS
    )

    with AUTH_SESSION_LOCK:
        # Remove expired sessions while we are here.
        now = time.time()

        expired = [
            key
            for key, value
            in AUTH_SESSIONS.items()
            if value.get('expires', 0) <= now
        ]

        for key in expired:
            AUTH_SESSIONS.pop(
                key,
                None
            )

        AUTH_SESSIONS[token] = {
            'username': username,
            'expires': expires,
        }

    return token


def auth_session(request):
    token = request.cookies.get(
        AUTH_COOKIE
    )

    if not token:
        return None

    with AUTH_SESSION_LOCK:
        session = AUTH_SESSIONS.get(
            token
        )

        if not session:
            return None

        if session.get(
            'expires',
            0
        ) <= time.time():

            AUTH_SESSIONS.pop(
                token,
                None
            )

            return None

        return {
            'token': token,
            'username':
                session.get('username'),
        }


def auth_client_key(request):
    try:
        return request.client.host or 'unknown'
    except Exception:
        return 'unknown'


def auth_login_blocked(request):
    key = auth_client_key(
        request
    )

    now = time.time()

    with AUTH_FAILURE_LOCK:
        recent = [
            ts
            for ts in AUTH_FAILURES.get(
                key,
                []
            )
            if (
                now - ts
                < AUTH_FAILURE_WINDOW
            )
        ]

        AUTH_FAILURES[key] = recent

        if len(recent) >= AUTH_FAILURE_LIMIT:
            wait = int(
                AUTH_FAILURE_WINDOW
                - (
                    now
                    - recent[0]
                )
            )

            return max(
                wait,
                1
            )

    return 0


def auth_record_failure(request):
    key = auth_client_key(
        request
    )

    now = time.time()

    with AUTH_FAILURE_LOCK:
        recent = [
            ts
            for ts in AUTH_FAILURES.get(
                key,
                []
            )
            if (
                now - ts
                < AUTH_FAILURE_WINDOW
            )
        ]

        recent.append(now)

        AUTH_FAILURES[key] = recent


def auth_clear_failures(request):
    key = auth_client_key(
        request
    )

    with AUTH_FAILURE_LOCK:
        AUTH_FAILURES.pop(
            key,
            None
        )


def auth_set_cookie(response, token):
    response.set_cookie(
        key=AUTH_COOKIE,
        value=token,
        max_age=AUTH_SESSION_SECONDS,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite='strict',
        path='/',
    )


@app.middleware('http')
async def kyber_auth_middleware(
    request,
    call_next,
):
    path = request.url.path

    public_paths = {
        '/',
        '/favicon.ico',
        '/api/auth/status',
        '/api/auth/setup',
        '/api/auth/login',
        '/api/auth/logout',
    }

    if path in public_paths:
        return await call_next(
            request
        )

    # CSS/JS needed by both the login screen
    # and authenticated dashboard remain public.
    # Direct access to the dashboard HTML does not.
    if path.startswith('/static/'):
        if path == '/static/index.html':
            if not auth_session(request):
                return JSONResponse(
                    {
                        'detail':
                            'Authentication required'
                    },
                    status_code=401,
                )

        return await call_next(
            request
        )

    protected = (
        path.startswith('/api/')
        or path == '/docs'
        or path == '/redoc'
        or path == '/openapi.json'
    )

    if protected:
        session = auth_session(
            request
        )

        if not session:
            return JSONResponse(
                {
                    'detail':
                        'Authentication required'
                },
                status_code=401,
            )

    return await call_next(
        request
    )


@app.get('/api/auth/status')
def auth_status(request: Request):
    account = auth_account()

    session = auth_session(
        request
    )

    omv = omv_required_status()

    return {
        'account_exists':
            account is not None,

        'authenticated':
            session is not None,

        'username':
            (
                session.get('username')
                if session
                else None
            ),

        'omv_ready':
            omv['ready'],

        'omv_detail':
            omv['detail'],

        'platform':
            'openmediavault',
    }


@app.post('/api/auth/setup')
def auth_setup(
    req: AuthSetupReq,
    request: Request,
):
    omv = omv_required_status()

    if not omv['ready']:
        raise HTTPException(
            503,
            'Kyber Core requires OpenMediaVault. '
            + omv['detail']
        )

    if auth_account() is not None:
        raise HTTPException(
            409,
            'Administrator account '
            'already exists'
        )

    username = req.username.strip()

    if not re.fullmatch(
        r'[A-Za-z0-9._-]{3,32}',
        username
    ):
        raise HTTPException(
            400,
            'Username must be 3-32 characters '
            'and contain only letters, numbers, '
            'periods, underscores, or hyphens'
        )

    if len(req.password) < 10:
        raise HTTPException(
            400,
            'Password must contain at least '
            '10 characters'
        )

    if len(req.password) > 256:
        raise HTTPException(
            400,
            'Password is too long'
        )

    if (
        req.password
        != req.password_confirm
    ):
        raise HTTPException(
            400,
            'Passwords do not match'
        )

    salt, password_hash = (
        auth_hash_password(
            req.password
        )
    )

    account = {
        'username': username,
        'salt': salt,
        'password_hash':
            password_hash,
        'created':
            datetime.now().isoformat(
                timespec='seconds'
            ),
    }

    auth_write_account(
        account
    )

    token = auth_new_session(
        username
    )

    response = JSONResponse({
        'ok': True,
        'username': username,
    })

    auth_set_cookie(
        response,
        token,
    )

    audit(
        'auth',
        f'administrator account '
        f'created: {username}'
    )

    return response


@app.post('/api/auth/login')
def auth_login(
    req: AuthLoginReq,
    request: Request,
):
    wait = auth_login_blocked(
        request
    )

    if wait:
        raise HTTPException(
            429,
            f'Too many failed login attempts. '
            f'Try again in about {wait} seconds.'
        )

    account = auth_account()

    if account is None:
        raise HTTPException(
            409,
            'Administrator account '
            'has not been created yet'
        )

    username_ok = (
        hmac.compare_digest(
            req.username.strip(),
            str(
                account.get(
                    'username',
                    ''
                )
            ),
        )
    )

    password_ok = (
        auth_verify_password(
            req.password,
            account,
        )
    )

    if not (
        username_ok
        and password_ok
    ):
        auth_record_failure(
            request
        )

        time.sleep(0.35)

        raise HTTPException(
            401,
            'Invalid username or password'
        )

    auth_clear_failures(
        request
    )

    token = auth_new_session(
        account['username']
    )

    response = JSONResponse({
        'ok': True,
        'username':
            account['username'],
    })

    auth_set_cookie(
        response,
        token,
    )

    audit(
        'auth',
        f'login: {account["username"]}'
    )

    return response


@app.post('/api/auth/logout')
def auth_logout(
    request: Request,
):
    token = request.cookies.get(
        AUTH_COOKIE
    )

    if token:
        with AUTH_SESSION_LOCK:
            AUTH_SESSIONS.pop(
                token,
                None
            )

    response = JSONResponse({
        'ok': True
    })

    response.delete_cookie(
        AUTH_COOKIE,
        path='/',
    )

    return response



CONTAINER_STATS = {}
CONTAINER_STATS_LOCK = threading.Lock()

CONTAINER_INVENTORY = []
CONTAINER_INVENTORY_LOCK = threading.Lock()
CONTAINER_INVENTORY_UPDATED = 0

CONTAINER_INVENTORY_STALE_SECONDS = 30
CONTAINER_STATS_STALE_SECONDS = 120


def build_container_inventory():
    """Build Docker inventory away from HTTP requests."""

    rows = []

    try:
        items = client.containers.list(all=True)
    except Exception:
        return None

    for c in items:
        try:
            attrs = c.attrs or {}
            state = attrs.get('State', {})
            network = attrs.get(
                'NetworkSettings', {}
            )
            config = attrs.get('Config', {})

            image = (
                config.get('Image')
                or (
                    c.image.tags[0]
                    if c.image.tags
                    else c.image.short_id
                )
            )

            ports = []

            for container_port, bindings in (
                network.get('Ports') or {}
            ).items():

                if bindings:
                    for binding in bindings:
                        ports.append({
                            'container':
                                container_port,

                            'host_ip':
                                binding.get(
                                    'HostIp', ''
                                ),

                            'host_port':
                                binding.get(
                                    'HostPort', ''
                                )
                        })

                else:
                    ports.append({
                        'container':
                            container_port,
                        'host_ip': '',
                        'host_port': ''
                    })

            labels = config.get(
                'Labels'
            ) or {}

            rows.append({
                'name':
                    c.name,

                'id':
                    c.short_id,

                'image':
                    image,

                'status':
                    state.get(
                        'Status',
                        c.status
                    ),

                'health':
                    (
                        state.get(
                            'Health', {}
                        ).get('Status')
                        if state.get('Health')
                        else None
                    ),

                'created':
                    attrs.get('Created'),

                'restart_count':
                    attrs.get(
                        'RestartCount', 0
                    ),

                'ports':
                    ports,

                'compose_project':
                    labels.get(
                        'com.docker.compose.project'
                    ),

                'compose_service':
                    labels.get(
                        'com.docker.compose.service'
                    ),

                'compose_config_files':
                    labels.get(
                        'com.docker.compose.project.config_files'
                    ),

                'compose_working_dir':
                    labels.get(
                        'com.docker.compose.project.working_dir'
                    ),

                'compose_environment_file':
                    labels.get(
                        'com.docker.compose.project.environment_file'
                    ),
            })

        except Exception as exc:
            rows.append({
                'name':
                    getattr(
                        c,
                        'name',
                        'unknown'
                    ),

                'id':
                    getattr(
                        c,
                        'short_id',
                        ''
                    ),

                'image':
                    'unknown',

                'status':
                    getattr(
                        c,
                        'status',
                        'unknown'
                    ),

                'health':
                    None,

                'ports':
                    [],

                'compose_project':
                    None,

                'compose_service':
                    None,

                'compose_config_files':
                    None,

                'compose_working_dir':
                    None,

                'compose_environment_file':
                    None,

                'error':
                    str(exc),
            })

    return sorted(
        rows,
        key=lambda x:
            x['name'].lower()
    )


def refresh_container_inventory():
    global CONTAINER_INVENTORY
    global CONTAINER_INVENTORY_UPDATED

    rows = build_container_inventory()

    if rows is None:
        return

    with CONTAINER_INVENTORY_LOCK:
        CONTAINER_INVENTORY = rows
        CONTAINER_INVENTORY_UPDATED = int(
            time.time()
        )


def container_inventory_snapshot(refresh_if_empty=False):
    """Return a copy of the cached Docker inventory and its timestamp."""

    with CONTAINER_INVENTORY_LOCK:
        inventory = [
            dict(x)
            for x in CONTAINER_INVENTORY
        ]
        updated = CONTAINER_INVENTORY_UPDATED

    # Preserve accurate first-request behavior while keeping normal HTTP
    # requests off the Docker API once the background cache is populated.
    if refresh_if_empty and not inventory:
        refresh_container_inventory()

        with CONTAINER_INVENTORY_LOCK:
            inventory = [
                dict(x)
                for x in CONTAINER_INVENTORY
            ]
            updated = CONTAINER_INVENTORY_UPDATED

    return inventory, updated


def container_stats_snapshot():
    """Return a copy of the background container-statistics cache."""

    with CONTAINER_STATS_LOCK:
        return {
            name: dict(values)
            for name, values
            in CONTAINER_STATS.items()
        }


def container_cache_health(inventory, inventory_updated, stats_cache):
    """Summarize cache freshness for running containers."""

    now = int(time.time())
    running_names = [
        row.get('name')
        for row in inventory
        if row.get('status') == 'running'
        and row.get('name')
    ]

    stats_fresh = 0
    stats_stale = 0
    stats_errors = 0

    for name in running_names:
        stats = stats_cache.get(name)
        updated = stats.get('updated') if stats else None

        if stats and stats.get('error'):
            stats_errors += 1

        if (
            updated
            and now - updated <= CONTAINER_STATS_STALE_SECONDS
        ):
            stats_fresh += 1
        else:
            stats_stale += 1

    return {
        'inventory_updated': inventory_updated or None,
        'inventory_stale': (
            not inventory_updated
            or now - inventory_updated
            > CONTAINER_INVENTORY_STALE_SECONDS
        ),
        'stats_fresh': stats_fresh,
        'stats_stale': stats_stale,
        'stats_errors': stats_errors,
    }


def container_inventory_worker():
    while True:

        try:
            refresh_container_inventory()

        except Exception:
            pass

        time.sleep(10)


def calculate_container_stats(stats):
    try:
        memory = stats.get('memory_stats', {})
        memory_usage = memory.get('usage', 0)

        # Docker memory usage often includes cache.
        cache = (
            memory.get('stats', {}).get('inactive_file', 0)
            or memory.get('stats', {}).get('cache', 0)
        )

        memory_usage = max(
            0,
            memory_usage - cache
        )

        memory_mb = round(
            memory_usage / 1024**2,
            1
        )

        cpu = stats.get('cpu_stats', {})
        precpu = stats.get('precpu_stats', {})

        cpu_total = (
            cpu.get('cpu_usage', {})
            .get('total_usage', 0)
        )

        precpu_total = (
            precpu.get('cpu_usage', {})
            .get('total_usage', 0)
        )

        system_total = cpu.get(
            'system_cpu_usage', 0
        )

        presystem_total = precpu.get(
            'system_cpu_usage', 0
        )

        cpu_delta = cpu_total - precpu_total
        system_delta = system_total - presystem_total

        online_cpus = (
            cpu.get('online_cpus')
            or len(
                cpu.get('cpu_usage', {})
                .get('percpu_usage', [])
            )
            or 1
        )

        cpu_percent = 0.0

        if cpu_delta > 0 and system_delta > 0:
            cpu_percent = (
                cpu_delta /
                system_delta *
                online_cpus *
                100.0
            )

        return {
            'memory_mb': memory_mb,
            'cpu_percent': round(cpu_percent, 1),
            'updated': int(time.time()),
        }

    except Exception:
        return {
            'memory_mb': 0,
            'cpu_percent': 0,
            'updated': int(time.time()),
        }


def fetch_container_stats(container_id, container_name):
    """
    Fetch one container's Docker statistics.

    A separate Docker client is used so a problematic
    request does not interfere with the main API client.
    """

    stats_client = None

    try:
        stats_client = docker.from_env(
            timeout=5
        )

        container = stats_client.containers.get(
            container_id
        )

        stats = container.stats(
            stream=False,
            decode=False
        )

        result = calculate_container_stats(
            stats
        )

        result['error'] = None

        return container_name, result

    except Exception as exc:

        return container_name, {
            'memory_mb': 0,
            'cpu_percent': 0,
            'updated': int(time.time()),
            'error': str(exc),
        }

    finally:
        if stats_client is not None:
            try:
                stats_client.close()
            except Exception:
                pass


def container_stats_worker():
    """
    Refresh running-container statistics concurrently.

    The web API never waits for this worker.
    """

    while True:

        started = time.time()

        try:
            items = client.containers.list(
                filters={
                    'status': 'running'
                }
            )

            targets = [
                (c.id, c.name)
                for c in items
            ]

            # Limit concurrency so a large Docker host
            # does not get hammered by stats requests.
            workers = min(
                8,
                max(1, len(targets))
            )

            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix='nexus-stats'
            ) as executor:

                futures = [
                    executor.submit(
                        fetch_container_stats,
                        container_id,
                        container_name
                    )
                    for container_id, container_name
                    in targets
                ]

                for future in as_completed(futures):

                    try:
                        name, result = (
                            future.result()
                        )

                    except Exception:
                        continue

                    with CONTAINER_STATS_LOCK:
                        CONTAINER_STATS[name] = (
                            result
                        )

        except Exception as exc:
            print(
                f"[Kyber Core] Stats worker error: {exc}",
                flush=True
            )

        # Aim for roughly one complete collection
        # cycle every 15 seconds.
        elapsed = time.time() - started

        time.sleep(
            max(
                1,
                15 - elapsed
            )
        )


@app.on_event('startup')
def start_container_monitor():
    thread = threading.Thread(
        target=container_stats_worker,
        name='nexus-container-monitor',
        daemon=True
    )

    thread.start()

    inventory_thread = threading.Thread(
        target=container_inventory_worker,
        name='nexus-container-inventory',
        daemon=True
    )

    inventory_thread.start()


class InstallReq(BaseModel): host_ports:dict[str,int]={}; paths:dict[str,str]={}; env:dict[str,str]={}
class ComposeReq(BaseModel): content:str; deploy:bool=False
class FileReq(BaseModel): path:str; content:str=''
class BackupReq(BaseModel): name:str='manual'
class SettingsReq(BaseModel): server_name:str='Kyber Core'; setup_complete:bool=True; theme:str='cosmic'
class AIReq(BaseModel): prompt:str

def audit(action,detail=''):
    with AUDIT.open('a') as f:f.write(json.dumps({'ts':datetime.now().isoformat(timespec='seconds'),'action':action,'detail':detail})+'\n')
def safe_name(s):
    if not re.fullmatch(r'[A-Za-z0-9._-]+',s): raise HTTPException(400,'Invalid name')
    return s
def within(path,roots):
    p=Path(path).resolve()
    if not any(p==r or r in p.parents for r in roots): raise HTTPException(403,'Path outside allowed roots')
    return p
def settings():
    try:return json.loads(SETTINGS.read_text())
    except:return {'server_name':'Kyber Core','setup_complete':False,'theme':'cosmic'}

@app.get('/')
def home(request: Request):
    if auth_session(request):
        return FileResponse(
            BASE/'app/static/index.html'
        )

    return FileResponse(
        BASE/'app/static/auth.html'
    )
@app.get('/api/settings')
def get_settings(): return settings()
@app.post('/api/settings')
def set_settings(req:SettingsReq): SETTINGS.write_text(req.model_dump_json(indent=2)); audit('settings','updated'); return {'ok':True}

def storage_rows():
    rows = []

    if not STORAGE_ROOT.exists():
        return rows

    seen = set()

    for p in STORAGE_ROOT.iterdir():
        if not p.is_dir():
            continue

        try:
            d = shutil.disk_usage(p)

            # Prevent the same filesystem from being counted twice.
            key = (d.total, d.free)

            if key in seen:
                continue

            seen.add(key)

            total = d.total
            free = d.free
            used = total - free

            rows.append({
                'name': p.name,
                'path': str(p),
                'total_gb': round(total / 1024**3, 1),
                'used_gb': round(used / 1024**3, 1),
                'free_gb': round(free / 1024**3, 1),
                'percent': round(
                    used / total * 100, 1
                ) if total else 0
            })

        except Exception:
            pass

    return rows


@app.get('/api/status')
def status():
    vm = psutil.virtual_memory()
    inventory, inventory_updated = (
        container_inventory_snapshot(
            refresh_if_empty=True
        )
    )
    stats_cache = container_stats_snapshot()
    cache_health = container_cache_health(
        inventory,
        inventory_updated,
        stats_cache
    )

    disks = storage_rows()

    storage_total = sum(
        x['total_gb'] for x in disks
    )

    storage_used = sum(
        x['used_gb'] for x in disks
    )

    temps = {}

    try:
        temps = {
            k: [
                round(x.current, 1)
                for x in v
            ]
            for k, v in
            psutil.sensors_temperatures().items()
        }
    except Exception:
        pass

    return {
        'version': '1.0.0',
        'hostname': socket.gethostname(),

        'cpu_percent':
            psutil.cpu_percent(.1),

        'memory_percent':
            vm.percent,

        'memory_used_gb':
            round(vm.used / 1024**3, 1),

        'memory_total_gb':
            round(vm.total / 1024**3, 1),

        'storage_used_gb':
            round(storage_used, 1),

        'storage_total_gb':
            round(storage_total, 1),

        'storage_percent':
            round(
                storage_used /
                max(storage_total, .1) * 100,
                1
            ),

        'storage_devices':
            len(disks),

        'containers_total':
            len(inventory),

        'containers_running':
            sum(
                row.get('status') == 'running'
                for row in inventory
            ),

        'container_inventory_updated':
            cache_health['inventory_updated'],

        'container_inventory_stale':
            cache_health['inventory_stale'],

        'container_stats_fresh':
            cache_health['stats_fresh'],

        'container_stats_stale':
            cache_health['stats_stale'],

        'container_stats_errors':
            cache_health['stats_errors'],

        'uptime_seconds':
            int(
                time.time() -
                psutil.boot_time()
            ),

        'load':
            list(os.getloadavg()),

        'temps':
            temps
    }


@app.get('/api/history')
def history():
    rows=[]
    if HISTORY.exists():
        for line in HISTORY.read_text().splitlines()[-120:]:
            try: rows.append(json.loads(line))
            except: pass
    return rows
@app.post('/api/history/sample')
def sample_history():
    s=status(); row={'ts':int(time.time()),'cpu':s['cpu_percent'],'memory':s['memory_percent'],'storage':round(s['storage_used_gb']/max(s['storage_total_gb'],.1)*100,1)}
    with HISTORY.open('a') as f:f.write(json.dumps(row)+'\n'); return row

@app.get('/api/containers')
def containers():

    # Never perform expensive Docker inspection
    # during a browser request.

    inventory, _ = container_inventory_snapshot(
        refresh_if_empty=True
    )
    stats_cache = container_stats_snapshot()

    now = int(time.time())

    for row in inventory:

        stats = stats_cache.get(
            row['name']
        )

        if stats:
            updated = stats.get(
                'updated'
            )

            row['memory_mb'] = stats.get(
                'memory_mb', 0
            )

            row['cpu_percent'] = stats.get(
                'cpu_percent', 0
            )

            row['stats_updated'] = updated

            row['stats_stale'] = (
                not updated
                or now - updated
                > CONTAINER_STATS_STALE_SECONDS
            )

            if stats.get('error'):
                row['stats_error'] = (
                    stats['error']
                )

        else:
            row['memory_mb'] = 0
            row['cpu_percent'] = 0
            row['stats_updated'] = None
            row['stats_stale'] = True

    return inventory


@app.post('/api/containers/{name}/{action}')
def container_action(name:str, action:str):

    # FastAPI resolves routes in declaration order, so the generic
    # ``/{action}`` route receives ``/update`` before the dedicated
    # update route declared below. Forward it to the safe Compose-aware
    # updater instead of rejecting it as an unsupported container action.
    if action == 'update':
        return update_container(name)

    if action not in {
        'start',
        'stop',
        'restart',
        'pause',
        'unpause'
    }:
        raise HTTPException(
            400,
            'Unsupported action'
        )

    try:
        c = client.containers.get(name)

        getattr(c, action)()

        audit(
            'container',
            f'{action} {name}'
        )

        # Refresh asynchronously so the action
        # response isn't delayed.
        threading.Thread(
            target=refresh_container_inventory,
            daemon=True
        ).start()

        return {
            'ok': True,
            'container': name,
            'action': action
        }

    except docker.errors.NotFound:
        raise HTTPException(
            404,
            'Container not found'
        )

    except Exception as exc:
        raise HTTPException(
            500,
            f'Container action failed: {exc}'
        )


@app.get('/api/containers/{name}/logs')
def logs(name:str,tail:int=300): return {'logs':client.containers.get(name).logs(tail=min(tail,2000),timestamps=True).decode('utf-8','replace')}
@app.get('/api/containers/{name}/inspect')
def inspect(name:str): return client.containers.get(name).attrs
@app.post('/api/containers/{name}/update')
def update_container(name:str):
    safe_name(name)

    try:
        container = client.containers.get(name)
    except docker.errors.NotFound:
        raise HTTPException(404, 'Container not found')

    attrs = container.attrs or {}
    config = attrs.get('Config', {})
    labels = config.get('Labels') or {}
    metadata = {
        'name': container.name,
        'id': container.short_id,
        'image': config.get('Image'),
        'status': attrs.get('State', {}).get(
            'Status',
            container.status
        ),
        'compose_project': labels.get(
            'com.docker.compose.project'
        ),
        'compose_service': labels.get(
            'com.docker.compose.service'
        ),
        'compose_config_files': labels.get(
            'com.docker.compose.project.config_files'
        ),
        'compose_environment_file': labels.get(
            'com.docker.compose.project.environment_file'
        ),
    }
    target = container_update_target(metadata)

    if not target['updatable']:
        raise HTTPException(
            409,
            target['reason']
        )

    before_container_id = container.id
    before_image_id = container.image.id
    pull_output = run_compose(
        target['files'],
        ['pull', target['service']],
        timeout=900,
        environment_files=target['environment_files']
    )
    up_output = run_compose(
        target['files'],
        [
            'up',
            '-d',
            '--no-deps',
            target['service']
        ],
        timeout=300,
        environment_files=target['environment_files']
    )

    updated_container = client.containers.get(name)
    recreated = (
        updated_container.id
        != before_container_id
    )
    image_changed = (
        updated_container.image.id
        != before_image_id
    )
    outcome = (
        'updated and recreated'
        if image_changed or recreated
        else 'already current'
    )

    audit(
        'update',
        f'{outcome} {name} via '
        f"{target['project']}/{target['service']}"
    )

    threading.Thread(
        target=refresh_container_inventory,
        daemon=True
    ).start()

    return {
        'ok': True,
        'container': name,
        'image': target['image'],
        'project': target['project'],
        'service': target['service'],
        'recreated': recreated,
        'image_changed': image_changed,
        'note': (
            f'{name} was updated and recreated.'
            if image_changed or recreated
            else f'{name} is already using the current image.'
        ),
        'output': '\n'.join(
            part
            for part in (pull_output, up_output)
            if part
        )[-6000:]
    }

def find_compose_file(name):
    safe_name(name)

    directory = COMPOSE_ROOT / name

    if not directory.exists():
        return None

    for filename in (
        'docker-compose.yml',
        'docker-compose.yaml',
        'compose.yml',
        'compose.yaml',
        f'{directory.name}.yml',
        f'{directory.name}.yaml',
    ):
        candidate = directory / filename

        if candidate.exists():
            return candidate

    return None


def map_compose_label_path(value):
    """Map a host Compose label path into the mounted Compose root."""

    if not value:
        return None

    raw_path = Path(str(value).strip())
    candidates = []

    if raw_path.is_absolute():
        parts = raw_path.parts

        for index, part in enumerate(parts):
            if part.lower() == COMPOSE_ROOT.name.lower():
                candidates.append(
                    COMPOSE_ROOT.joinpath(
                        *parts[index + 1:]
                    )
                )
                break

    candidates.append(
        COMPOSE_ROOT / raw_path.name
    )

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(COMPOSE_ROOT)
        except (OSError, ValueError):
            continue

        if resolved.exists():
            return resolved

    return None


def compose_label_paths(value):
    paths = []

    for item in str(value or '').split(','):
        mapped = map_compose_label_path(item)

        if mapped and mapped not in paths:
            paths.append(mapped)

    return paths


def compose_service_definition(files, service):
    definition = {}

    for file_path in files:
        try:
            document = yaml.safe_load(
                file_path.read_text()
            ) or {}
            service_definition = (
                document.get('services', {})
                .get(service)
            )

            if isinstance(service_definition, dict):
                definition.update(
                    service_definition
                )

        except Exception:
            continue

    return definition


def container_update_target(container):
    project = container.get('compose_project')
    service = container.get('compose_service')
    status = container.get('status')

    result = {
        'updatable': False,
        'reason': '',
        'project': project,
        'service': service,
        'image': container.get('image'),
        'files': [],
        'environment_files': [],
    }

    if status not in {'running', 'restarting'}:
        result['reason'] = (
            'Stopped or paused containers are not automatically '
            'started by the updater.'
        )
        return result

    if not project or not service:
        result['reason'] = (
            'No Docker Compose ownership metadata was found.'
        )
        return result

    if not re.fullmatch(r'[A-Za-z0-9._-]+', project):
        result['reason'] = 'Compose project name is not safe.'
        return result

    if not re.fullmatch(r'[A-Za-z0-9._-]+', service):
        result['reason'] = 'Compose service name is not safe.'
        return result

    files = compose_label_paths(
        container.get('compose_config_files')
    )

    if not files:
        fallback = find_compose_file(project)

        if fallback:
            files = [fallback]

    if not files:
        result['reason'] = (
            'The Compose configuration could not be resolved '
            'inside the configured Compose root.'
        )
        return result

    definition = compose_service_definition(
        files,
        service
    )

    if not definition:
        result['reason'] = (
            f'Compose service {service} was not found in its '
            'configuration files.'
        )
        return result

    if definition.get('build') and not definition.get('image'):
        result['reason'] = (
            'This service is built locally and has no pullable '
            'image. Rebuild its Compose project instead.'
        )
        return result

    image = definition.get('image') or container.get('image')

    if not image:
        result['reason'] = 'No pullable image is configured.'
        return result

    result.update({
        'updatable': True,
        'reason': '',
        'image': str(image),
        'files': files,
        'environment_files': compose_label_paths(
            container.get('compose_environment_file')
        ),
    })

    return result


def run_compose(
    file_path,
    args,
    timeout=300,
    environment_files=None
):
    file_paths = (
        list(file_path)
        if isinstance(file_path, (list, tuple))
        else [file_path]
    )
    command = (
        compose_cli(
            file_paths,
            environment_files=environment_files
        )
        + list(args)
    )

    try:
        result = subprocess.run(
            command,
            cwd=str(Path(file_paths[0]).parent),
            capture_output=True,
            text=True,
            timeout=timeout
        )

    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            504,
            'Docker Compose operation timed out.'
        )

    except Exception as exc:
        raise HTTPException(
            500,
            f'Unable to execute Docker Compose: {exc}'
        )

    output = (
        (result.stdout or '')
        + (result.stderr or '')
    ).strip()

    if result.returncode != 0:
        raise HTTPException(
            500,
            output[-6000:]
            or (
                'Docker Compose failed with '
                f'exit code {result.returncode}'
            )
        )

    return output[-6000:]


@app.get('/api/compose')
def compose_list():
    out = []

    # Get Compose ownership from our fast inventory cache.
    with CONTAINER_INVENTORY_LOCK:
        inventory = [
            dict(x)
            for x in CONTAINER_INVENTORY
        ]

    projects = {}

    for container in inventory:
        project = container.get(
            'compose_project'
        )

        if not project:
            continue

        projects.setdefault(
            project,
            []
        ).append(container)

    if not COMPOSE_ROOT.exists():
        return out

    for directory in sorted(
        COMPOSE_ROOT.iterdir(),
        key=lambda x: x.name.lower()
    ):
        if not directory.is_dir():
            continue

        # Ignore directories whose names cannot safely
        # be addressed through the Compose API.
        if not re.fullmatch(
            r'[A-Za-z0-9._-]+',
            directory.name
        ):
            continue

        file_path = find_compose_file(
            directory.name
        )

        if not file_path:
            continue

        containers_for_project = projects.get(
            directory.name,
            []
        )

        total = len(
            containers_for_project
        )

        running = sum(
            c.get('status') == 'running'
            for c in containers_for_project
        )

        if not total:
            runtime_status = 'inactive'

        elif running == total:
            runtime_status = 'running'

        elif running:
            runtime_status = 'partial'

        else:
            runtime_status = 'stopped'

        out.append({
            'name':
                directory.name,

            'file':
                str(file_path),

            'modified':
                int(
                    file_path.stat().st_mtime
                ),

            'status':
                runtime_status,

            'containers_total':
                total,

            'containers_running':
                running,

            'containers': [
                {
                    'name':
                        c.get('name'),

                    'service':
                        c.get(
                            'compose_service'
                        ),

                    'status':
                        c.get('status')
                }
                for c in containers_for_project
            ]
        })

    return out


@app.get('/api/compose/{name}')
def compose_get(name:str):

    file_path = find_compose_file(name)

    if not file_path:
        raise HTTPException(
            404,
            'Compose file not found'
        )

    return {
        'name': name,
        'file': str(file_path),
        'content': file_path.read_text()
    }


@app.post('/api/compose/{name}/validate')
def compose_validate(name:str,req:ComposeReq):
    try: obj=yaml.safe_load(req.content); assert isinstance(obj,dict) and 'services' in obj
    except Exception as e: raise HTTPException(400,f'Invalid Compose YAML: {e}')
    return {'ok':True,'services':list((obj.get('services') or {}).keys())}
@app.put('/api/compose/{name}')
def compose_save(name:str, req:ComposeReq):

    safe_name(name)

    compose_validate(
        name,
        req
    )

    directory = COMPOSE_ROOT / name

    directory.mkdir(
        parents=True,
        exist_ok=True
    )

    existing = find_compose_file(name)

    file_path = (
        existing
        if existing
        else directory / 'docker-compose.yml'
    )

    if file_path.exists():

        backup = file_path.with_name(
            file_path.name
            + f'.bak-{int(time.time())}'
        )

        shutil.copy2(
            file_path,
            backup
        )

    file_path.write_text(
        req.content
    )

    audit(
        'compose',
        f'saved {name}'
    )

    output = ''

    if req.deploy:

        output = run_compose(
            file_path,
            ['up', '-d'],
            timeout=300
        )

        audit(
            'compose',
            f'deployed {name}'
        )

        threading.Thread(
            target=refresh_container_inventory,
            daemon=True
        ).start()

    return {
        'ok': True,
        'deployed': req.deploy,
        'file': str(file_path),
        'output': output
    }


@app.post('/api/compose/{name}/{action}')
def compose_action(name:str, action:str):

    allowed = {
        'up':
            ['up', '-d'],

        'down':
            ['down'],

        'restart':
            ['restart'],

        'pull':
            ['pull'],
    }

    command = allowed.get(action)

    if command is None:
        raise HTTPException(
            400,
            'Unsupported action'
        )

    file_path = find_compose_file(name)

    if not file_path:
        raise HTTPException(
            404,
            'Compose file not found'
        )

    # Pulling images may take considerably longer.
    timeout = (
        900
        if action == 'pull'
        else 300
    )

    output = run_compose(
        file_path,
        command,
        timeout=timeout
    )

    audit(
        'compose',
        f'{action} {name}'
    )

    # Docker inventory may have changed.
    threading.Thread(
        target=refresh_container_inventory,
        daemon=True
    ).start()

    return {
        'ok': True,
        'project': name,
        'action': action,
        'output': output
    }


@app.get('/api/storage')
def storage():
    return storage_rows()


@app.get('/api/storage/smart')
def smart():
    try:
        p=subprocess.run(['smartctl','--scan-open'],capture_output=True,text=True,timeout=10)
        devs=[]
        for line in p.stdout.splitlines():
            dev=line.split()[0]; q=subprocess.run(['smartctl','-H','-A',dev],capture_output=True,text=True,timeout=15); devs.append({'device':dev,'output':q.stdout[-8000:]})
        return {'available':True,'devices':devs}
    except Exception as e:return {'available':False,'devices':[],'detail':str(e)}

@app.get('/api/network')
def network():
    addrs={};
    for k,v in psutil.net_if_addrs().items(): addrs[k]=[{'address':x.address,'family':str(x.family)} for x in v]
    nets=[]
    for n in client.networks.list():
        a=n.attrs; nets.append({'name':n.name,'driver':a.get('Driver'),'scope':a.get('Scope'),'containers':[x.get('Name') for x in (a.get('Containers') or {}).values()]})
    conns=[]
    try:
        for c in psutil.net_connections(kind='inet'):
            if c.status=='LISTEN' and c.laddr: conns.append({'ip':c.laddr.ip,'port':c.laddr.port,'pid':c.pid})
    except: pass
    return {'interfaces':addrs,'docker_networks':nets,'listeners':sorted(conns,key=lambda x:x['port'])[:300]}

@app.get('/api/files')
def files(path:str=''):
    p=within(path or STORAGE_ROOT,[STORAGE_ROOT,COMPOSE_ROOT]);
    if not p.exists() or not p.is_dir(): raise HTTPException(404,'Directory not found')
    out=[]
    for x in sorted(p.iterdir(),key=lambda z:(not z.is_dir(),z.name.lower()))[:500]:
        try: out.append({'name':x.name,'path':str(x),'dir':x.is_dir(),'size':0 if x.is_dir() else x.stat().st_size,'modified':int(x.stat().st_mtime)})
        except: pass
    return {'path':str(p),'items':out}
@app.get('/api/file')
def file_read(path:str):
    p=within(path,[STORAGE_ROOT,COMPOSE_ROOT]);
    if p.stat().st_size>2_000_000: raise HTTPException(413,'File too large for editor')
    return {'path':str(p),'content':p.read_text(errors='replace')}
@app.put('/api/file')
def file_write(req:FileReq):
    p=within(req.path,[STORAGE_ROOT,COMPOSE_ROOT]);
    if p.exists(): shutil.copy2(p,p.with_name(p.name+f'.bak-{int(time.time())}'))
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(req.content); audit('file',f'edited {p}'); return {'ok':True}

class ContainerBackupReq(BaseModel):
    container: str


def _backup_path_within(path, root):
    try:
        Path(path).resolve().relative_to(
            Path(root).resolve()
        )
        return True
    except Exception:
        return False


def _container_config_destination(path):
    path = str(path or '').rstrip('/')

    return (
        path == '/config'
        or path.startswith('/config/')
        or path.endswith('/config')
    )


def _host_source_to_local(source, must_exist=True):
    source_path = Path(str(source))

    host_compose = Path(
        os.getenv(
            'HOST_COMPOSE_ROOT',
            '/opt/compose'
        )
    )

    host_storage = Path(
        os.getenv(
            'HOST_STORAGE_ROOT',
            '/srv'
        )
    )

    mappings = [
        (host_compose, COMPOSE_ROOT),
        (host_storage, STORAGE_ROOT),

        # Compatibility with the common OMV host paths.
        (Path('/Compose'), COMPOSE_ROOT),
        (Path('/host/Compose'), COMPOSE_ROOT),
        (Path('/srv'), STORAGE_ROOT),
        (Path('/host/srv'), STORAGE_ROOT),
    ]

    for host_root, local_root in mappings:
        try:
            relative = source_path.relative_to(
                host_root
            )
        except Exception:
            continue

        candidate = (
            Path(local_root) / relative
        ).resolve()

        if not _backup_path_within(
            candidate,
            local_root
        ):
            continue

        if must_exist and not candidate.exists():
            continue

        return candidate

    # A path may already be directly visible inside Kyber.
    try:
        candidate = source_path.resolve()

        for root in (
            COMPOSE_ROOT,
            STORAGE_ROOT,
        ):
            if _backup_path_within(
                candidate,
                root
            ):
                if (
                    not must_exist
                    or candidate.exists()
                ):
                    return candidate

    except Exception:
        pass

    return None


def _container_backup_info(container_name):
    safe_name(container_name)

    try:
        container = client.containers.get(
            container_name
        )
        container.reload()

    except docker.errors.NotFound:
        raise HTTPException(
            404,
            f'Container {container_name} '
            'was not found'
        )

    labels = (
        container.attrs
        .get('Config', {})
        .get('Labels', {})
        or {}
    )

    project = str(
        labels.get(
            'com.docker.compose.project',
            ''
        )
    ).strip()

    if not project:
        raise HTTPException(
            400,
            f'Container {container_name} '
            'is not managed by Docker Compose'
        )

    safe_name(project)

    project_dir = (
        COMPOSE_ROOT / project
    ).resolve()

    if not _backup_path_within(
        project_dir,
        COMPOSE_ROOT
    ):
        raise HTTPException(
            400,
            'Compose project path is outside '
            'the configured Compose root'
        )

    if not project_dir.exists():
        raise HTTPException(
            404,
            f'Compose project directory '
            f'{project_dir} is not available'
        )

    compose_files = []

    for file_path in project_dir.iterdir():
        if not file_path.is_file():
            continue

        name = file_path.name.lower()

        if (
            name.endswith('.yml')
            or name.endswith('.yaml')
            or name == '.env'
            or name.endswith('.env')
        ):
            compose_files.append(
                file_path.resolve()
            )

    compose_files = sorted(
        set(compose_files),
        key=lambda item: item.name,
    )

    if not compose_files:
        raise HTTPException(
            400,
            f'No Compose/configuration files '
            f'were found for {container_name}'
        )

    config_mounts = []

    for mount in (
        container.attrs.get('Mounts', [])
        or []
    ):
        if mount.get('Type') != 'bind':
            continue

        destination = str(
            mount.get('Destination') or ''
        )

        # Stage 1 intentionally backs up only
        # config-style mounts. Media/data mounts
        # are deliberately excluded.
        if not _container_config_destination(
            destination
        ):
            continue

        source = str(
            mount.get('Source') or ''
        )

        if not source:
            continue

        local_path = _host_source_to_local(
            source,
            must_exist=True,
        )

        if local_path is None:
            continue

        config_mounts.append({
            'source': source,
            'destination': destination,
            'local_path': local_path,
        })

    return {
        'container_obj': container,
        'container': container.name,
        'project': project,
        'project_dir': project_dir,
        'compose_files': compose_files,
        'config_mounts': config_mounts,
    }


def _container_tar_filter(info):
    # Container Backups intentionally contain only
    # regular files and directories.
    if info.isfile() or info.isdir():
        return info

    return None


def _create_container_backup(
    container_name,
    filename_prefix=None,
):
    import io

    info = _container_backup_info(
        container_name
    )

    container = info['container_obj']

    container.reload()

    was_running = (
        container.status == 'running'
    )

    prefix = (
        filename_prefix
        or info['container']
    )

    prefix = re.sub(
        r'[^A-Za-z0-9._-]',
        '-',
        prefix,
    )[:80]

    out = BACKUP_ROOT / (
        f'{prefix}-'
        f'{datetime.now().strftime("%Y%m%d-%H%M%S")}'
        '.tar.gz'
    )

    manifest = {
        'format': 'kyber-container-backup-v1',
        'scope': 'container-config-only',
        'container': info['container'],
        'project': info['project'],
        'created': datetime.now().isoformat(
            timespec='seconds'
        ),
        'compose_files': [
            file_path.name
            for file_path
            in info['compose_files']
        ],
        'config_mounts': [
            {
                'archive': f'config/{index}',
                'source': mount['source'],
                'destination':
                    mount['destination'],
            }
            for index, mount in enumerate(
                info['config_mounts']
            )
        ],
        'excludes': [
            'media libraries',
            'downloads',
            'general storage mounts',
            'container filesystem layers',
            'whole-server data',
        ],
    }

    stopped_for_backup = False

    try:
        if was_running:
            container.stop(timeout=30)
            stopped_for_backup = True

        with tarfile.open(
            out,
            'w:gz'
        ) as archive:

            archive.dereference = True

            manifest_bytes = json.dumps(
                manifest,
                indent=2,
            ).encode('utf-8')

            manifest_info = tarfile.TarInfo(
                'manifest.json'
            )

            manifest_info.size = len(
                manifest_bytes
            )

            manifest_info.mtime = int(
                time.time()
            )

            archive.addfile(
                manifest_info,
                io.BytesIO(manifest_bytes),
            )

            for compose_file in (
                info['compose_files']
            ):
                archive.add(
                    compose_file,
                    arcname=(
                        'compose/'
                        + compose_file.name
                    ),
                    recursive=False,
                    filter=_container_tar_filter,
                )

            for index, mount in enumerate(
                info['config_mounts']
            ):
                archive.add(
                    mount['local_path'],
                    arcname=f'config/{index}',
                    recursive=True,
                    filter=_container_tar_filter,
                )

    except Exception:
        try:
            if out.exists():
                out.unlink()
        except Exception:
            pass

        raise

    finally:
        if stopped_for_backup:
            try:
                container.start()
            except Exception as exc:
                audit(
                    'backup',
                    f'WARNING: backup completed '
                    f'but {container_name} '
                    f'could not be restarted: '
                    f'{exc}'
                )

    audit(
        'backup',
        f'container backup '
        f'{container_name}: {out.name}'
    )

    return {
        'ok': True,
        'name': out.name,
        'container': info['container'],
        'project': info['project'],
        'size': out.stat().st_size,
        'compose_files': len(
            info['compose_files']
        ),
        'config_mounts': len(
            info['config_mounts']
        ),
    }


def _read_container_backup_manifest(path):
    try:
        with tarfile.open(
            path,
            'r:gz'
        ) as archive:

            first = archive.next()

            if (
                first is None
                or first.name != 'manifest.json'
                or not first.isfile()
            ):
                return None

            stream = archive.extractfile(first)

            if stream is None:
                return None

            manifest = json.loads(
                stream.read().decode(
                    'utf-8'
                )
            )

            if (
                manifest.get('format')
                != 'kyber-container-backup-v1'
            ):
                return None

            return manifest

    except Exception:
        return None


def _restore_archive_member(
    archive,
    member,
    base,
    prefix,
):
    base = Path(base).resolve()

    if member.name == prefix:
        relative = Path('.')

    elif member.name.startswith(
        prefix + '/'
    ):
        relative = Path(
            member.name[
                len(prefix) + 1:
            ]
        )

    else:
        return False

    target = (
        base / relative
    ).resolve()

    if not _backup_path_within(
        target,
        base
    ):
        raise ValueError(
            f'Unsafe archive path: '
            f'{member.name}'
        )

    if member.isdir():
        target.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            os.chmod(
                target,
                member.mode & 0o777,
            )
        except Exception:
            pass

        return True

    if not member.isfile():
        raise ValueError(
            f'Unsupported archive member: '
            f'{member.name}'
        )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    source = archive.extractfile(
        member
    )

    if source is None:
        raise ValueError(
            f'Could not read archive member: '
            f'{member.name}'
        )

    with source, open(
        target,
        'wb'
    ) as output:
        shutil.copyfileobj(
            source,
            output
        )

    try:
        os.chmod(
            target,
            member.mode & 0o777,
        )
    except Exception:
        pass

    try:
        os.chown(
            target,
            member.uid,
            member.gid,
        )
    except Exception:
        pass

    try:
        os.utime(
            target,
            (
                member.mtime,
                member.mtime,
            )
        )
    except Exception:
        pass

    return True


@app.get('/api/backups/targets')
def backup_targets():
    targets = []

    for container in client.containers.list(
        all=True
    ):
        labels = (
            container.attrs
            .get('Config', {})
            .get('Labels', {})
            or {}
        )

        project = labels.get(
            'com.docker.compose.project'
        )

        if not project:
            continue

        try:
            info = _container_backup_info(
                container.name
            )

        except Exception:
            continue

        targets.append({
            'container': container.name,
            'project': info['project'],
            'status': container.status,
            'config_mounts': len(
                info['config_mounts']
            ),
        })

    return sorted(
        targets,
        key=lambda item:
            item['container'].lower()
    )


@app.get('/api/backups')
def backups():
    output = []

    for path in sorted(
        BACKUP_ROOT.glob('*.tar.gz'),
        reverse=True,
    ):
        manifest = (
            _read_container_backup_manifest(
                path
            )
        )

        # Old general-purpose archives remain on disk
        # but are intentionally hidden from the new
        # Container Backups interface.
        if not manifest:
            continue

        output.append({
            'name': path.name,
            'size': path.stat().st_size,
            'modified': int(
                path.stat().st_mtime
            ),
            'container':
                manifest.get('container'),
            'project':
                manifest.get('project'),
            'compose_files': len(
                manifest.get(
                    'compose_files',
                    []
                )
            ),
            'config_mounts': len(
                manifest.get(
                    'config_mounts',
                    []
                )
            ),
            'scope': 'container-config-only',
        })

    return output


@app.post('/api/backups')
def backup(req: ContainerBackupReq):
    return _create_container_backup(
        req.container
    )


@app.post('/api/backups/{name}/restore')
def backup_restore(name: str):
    name = safe_name(name)

    path = BACKUP_ROOT / name

    if not path.exists():
        raise HTTPException(
            404,
            'Container backup not found'
        )

    manifest = (
        _read_container_backup_manifest(
            path
        )
    )

    if not manifest:
        raise HTTPException(
            400,
            'This archive is not a '
            'Kyber Core container backup'
        )

    container_name = str(
        manifest.get('container') or ''
    ).strip()

    project = str(
        manifest.get('project') or ''
    ).strip()

    safe_name(container_name)
    safe_name(project)

    project_dir = (
        COMPOSE_ROOT / project
    ).resolve()

    if not _backup_path_within(
        project_dir,
        COMPOSE_ROOT
    ):
        raise HTTPException(
            400,
            'Unsafe Compose project path'
        )

    safety_backup = None
    existing_container = None
    was_running = False

    try:
        existing_container = (
            client.containers.get(
                container_name
            )
        )

        existing_container.reload()

        was_running = (
            existing_container.status
            == 'running'
        )

        # Always create a current-state safety
        # backup before overwriting anything.
        safety_backup = (
            _create_container_backup(
                container_name,
                filename_prefix=(
                    f'{container_name}'
                    '-pre-restore'
                ),
            )
        )

        existing_container = (
            client.containers.get(
                container_name
            )
        )

        existing_container.reload()

        if (
            existing_container.status
            == 'running'
        ):
            existing_container.stop(
                timeout=30
            )

    except docker.errors.NotFound:
        existing_container = None

    project_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    restored_compose = []

    try:
        with tarfile.open(
            path,
            'r:gz'
        ) as archive:

            members = archive.getmembers()

            # Restore Compose/env files.
            for member in members:
                if not member.name.startswith(
                    'compose/'
                ):
                    continue

                _restore_archive_member(
                    archive,
                    member,
                    project_dir,
                    'compose',
                )

                if member.isfile():
                    restored_compose.append(
                        project_dir
                        / member.name[
                            len('compose/'):
                        ]
                    )

            # Restore only the config mounts recorded
            # by the trusted Kyber backup manifest.
            for mount in manifest.get(
                'config_mounts',
                []
            ):
                destination = str(
                    mount.get(
                        'destination',
                        ''
                    )
                )

                if not (
                    _container_config_destination(
                        destination
                    )
                ):
                    raise ValueError(
                        'Backup contains a '
                        'non-config mount'
                    )

                source = str(
                    mount.get(
                        'source',
                        ''
                    )
                )

                archive_prefix = str(
                    mount.get(
                        'archive',
                        ''
                    )
                )

                local_target = (
                    _host_source_to_local(
                        source,
                        must_exist=False,
                    )
                )

                if local_target is None:
                    raise ValueError(
                        f'Cannot safely map '
                        f'config path {source}'
                    )

                local_target.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                for member in members:
                    _restore_archive_member(
                        archive,
                        member,
                        local_target,
                        archive_prefix,
                    )

    except Exception as exc:
        if (
            existing_container is not None
            and was_running
        ):
            try:
                existing_container.start()
            except Exception:
                pass

        raise HTTPException(
            500,
            f'Restore failed: {exc}. '
            f'Safety backup: '
            f'{safety_backup["name"] if safety_backup else "none"}'
        )

    compose_candidates = [
        file_path
        for file_path in restored_compose
        if file_path.suffix.lower()
        in ('.yml', '.yaml')
    ]

    if not compose_candidates:
        raise HTTPException(
            500,
            'Restore completed files but '
            'no Compose YAML was available '
            'to start the container'
        )

    # Prefer the project's primary Compose file and never
    # accidentally deploy an override file by itself.
    preferred_names = [
        f'{project}.yml',
        f'{project}.yaml',
        'docker-compose.yml',
        'docker-compose.yaml',
        'compose.yml',
        'compose.yaml',
    ]

    compose_by_name = {
        item.name: item
        for item in compose_candidates
    }

    compose_file = next(
        (
            compose_by_name[name]
            for name in preferred_names
            if name in compose_by_name
        ),
        None,
    )

    if compose_file is None:
        compose_file = next(
            (
                item
                for item in compose_candidates
                if '.override.' not in item.name.lower()
            ),
            None,
        )

    if compose_file is None:
        raise HTTPException(
            500,
            'Restore found only Compose override files; '
            'a primary Compose file is required'
        )

    deploy = subprocess.run(
        compose_cli(
            str(compose_file)
        ) + ['up', '-d'],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if deploy.returncode:
        raise HTTPException(
            500,
            'Files were restored but '
            'Docker Compose could not start '
            f'the container: '
            f'{(deploy.stderr or deploy.stdout)[-1800:]}. '
            f'Safety backup: '
            f'{safety_backup["name"] if safety_backup else "none"}'
        )

    refresh_container_inventory()

    audit(
        'backup',
        f'restored {container_name} '
        f'from {name}'
    )

    return {
        'ok': True,
        'container': container_name,
        'backup': name,
        'safety_backup': (
            safety_backup['name']
            if safety_backup
            else None
        ),
    }


@app.delete('/api/backups/{name}')
def backup_delete(name: str):
    path = (
        BACKUP_ROOT
        / safe_name(name)
    )

    if not path.exists():
        raise HTTPException(
            404,
            'Not found'
        )

    manifest = (
        _read_container_backup_manifest(
            path
        )
    )

    if not manifest:
        raise HTTPException(
            400,
            'Only Kyber Core container '
            'backups can be deleted here'
        )

    path.unlink()

    audit(
        'backup',
        f'deleted container backup {name}'
    )

    return {'ok': True}


@app.get('/api/updates')
def updates():
    inventory, _ = container_inventory_snapshot(
        refresh_if_empty=True
    )
    output = []

    for container in inventory:
        target = container_update_target(
            container
        )
        output.append({
            'container': container.get('name'),
            'image': target.get('image') or 'unknown',
            'status': container.get('status'),
            'project': target.get('project'),
            'service': target.get('service'),
            'updatable': target.get('updatable', False),
            'reason': target.get('reason', ''),
            'compose_files': [
                str(path)
                for path in target.get('files', [])
            ],
        })

    return sorted(
        output,
        key=lambda item: item['container'].lower()
    )

@app.get('/api/security')
def security():
    exposed=[]
    for c in client.containers.list(all=True):
        for cp,bs in (c.attrs.get('NetworkSettings',{}).get('Ports',{}) or {}).items():
            for b in bs or []:
                if b.get('HostIp') in ('0.0.0.0','::',''): exposed.append({'container':c.name,'container_port':cp,'host_port':b.get('HostPort'),'host_ip':b.get('HostIp')})
    return {'docker_socket_mounted':True,'exposed_ports':exposed,'allowed_file_roots':[str(COMPOSE_ROOT),str(STORAGE_ROOT)],'note':'Docker socket access is privileged. Keep this dashboard on a trusted local network.'}
@app.get('/api/audit')
def audit_log():
    rows=[]
    if AUDIT.exists():
        for x in AUDIT.read_text().splitlines()[-300:]:
            try: rows.append(json.loads(x))
            except: pass
    return rows[::-1]

@app.get('/api/notifications')
def notifications():
    n = []
    disks = storage_rows()
    storage_total = sum(
        row['total_gb'] for row in disks
    )
    storage_used = sum(
        row['used_gb'] for row in disks
    )

    if storage_total and storage_used / storage_total > .85:
        n.append({
            'level': 'warning',
            'message': 'Storage usage is above 85%.'
        })

    inventory, inventory_updated = (
        container_inventory_snapshot(
            refresh_if_empty=True
        )
    )
    stats_cache = container_stats_snapshot()
    cache_health = container_cache_health(
        inventory,
        inventory_updated,
        stats_cache
    )

    stopped = [
        row.get('name', 'unknown')
        for row in inventory
        if row.get('status') != 'running'
    ]

    if stopped:
        n.append({
            'level': 'info',
            'message': (
                f'{len(stopped)} container(s) are not running: '
                + ', '.join(stopped[:8])
            )
        })

    if cache_health['inventory_stale']:
        n.append({
            'level': 'warning',
            'message': 'Container inventory cache is stale.'
        })

    if cache_health['stats_errors']:
        n.append({
            'level': 'warning',
            'message': (
                f"Statistics collection has errors for "
                f"{cache_health['stats_errors']} running container(s)."
            )
        })

    if cache_health['stats_stale']:
        n.append({
            'level': 'info',
            'message': (
                f"Statistics are stale for "
                f"{cache_health['stats_stale']} running container(s)."
            )
        })

    return n

def compose_cli(f, environment_files=None):
    files = (
        list(f)
        if isinstance(f, (list, tuple))
        else [f]
    )

    if shutil.which('docker'):
        q=subprocess.run(['docker','compose','version'],capture_output=True)
        if q.returncode==0:
            command = ['docker', 'compose']

            for environment_file in environment_files or []:
                command.extend([
                    '--env-file',
                    str(environment_file)
                ])

            for file_path in files:
                command.extend([
                    '-f',
                    str(file_path)
                ])

            return command

    if shutil.which('docker-compose'):
        command = ['docker-compose']

        for environment_file in environment_files or []:
            command.extend([
                '--env-file',
                str(environment_file)
            ])

        for file_path in files:
            command.extend([
                '-f',
                str(file_path)
            ])

        return command

    raise HTTPException(500,'Docker Compose CLI is not installed in the Kyber Core container')

@app.post('/api/ai')
async def ai(req:AIReq):
    context={'status':status(),'containers':containers(),'storage':storage()}
    if not OLLAMA_URL: return {'configured':False,'response':'Local AI is not configured. Set OLLAMA_URL and OLLAMA_MODEL to enable diagnostics.','context':context}
    prompt='You are a cautious homelab diagnostic assistant. Never claim a change was applied. Explain evidence and propose reversible steps.\nSYSTEM:\n'+json.dumps(context,default=str)[:18000]+'\nUSER:\n'+req.prompt
    try:
        async with httpx.AsyncClient(timeout=120) as h:r=await h.post(OLLAMA_URL+'/api/generate',json={'model':OLLAMA_MODEL,'prompt':prompt,'stream':False}); r.raise_for_status(); data=r.json()
        return {'configured':True,'model':OLLAMA_MODEL,'response':data.get('response','')}
    except Exception as e: raise HTTPException(502,f'AI request failed: {e}')

# Awesome Selfhosted discovery catalog

def parse_awesome_selfhosted(readme):
    """Parse the published Awesome Selfhosted Markdown catalog."""

    apps = []
    category = ''
    in_software = False

    for line in readme.splitlines():
        if line == '## Software':
            in_software = True
            continue

        if in_software and line.startswith('## '):
            break

        if not in_software:
            continue

        if line.startswith('### '):
            category = line[4:].strip()
            continue

        match = re.match(
            r'^- \[([^\]]+)\]\((https?://[^)]+)\)'
            r'(?: `⚠`)?(?: - (.*))?$',
            line
        )

        if not match:
            continue

        name, website, remainder = match.groups()
        remainder = remainder or ''

        source_match = re.search(
            r'\[Source Code\]\((https?://[^)]+)\)',
            remainder
        )
        demo_match = re.search(
            r'\[Demo\]\((https?://[^)]+)\)',
            remainder
        )

        description = remainder.split(' ([', 1)[0]
        description = description.split(' `', 1)[0].strip()

        metadata = [
            value
            for value in re.findall(r'`([^`]+)`', remainder)
            if value != '⚠'
        ]
        licenses = (
            metadata[-2].split('/')
            if len(metadata) >= 2
            else []
        )
        platforms = (
            metadata[-1].split('/')
            if metadata
            else []
        )

        slug = re.sub(
            r'[^a-z0-9]+',
            '-',
            name.lower()
        ).strip('-')

        apps.append({
            'slug': slug,
            'name': name,
            'description': description,
            'category': category,
            'website': website,
            'source_code': (
                source_match.group(1)
                if source_match
                else website
            ),
            'demo': (
                demo_match.group(1)
                if demo_match
                else None
            ),
            'licenses': licenses,
            'platforms': platforms,
            'docker': any(
                item.lower() == 'docker'
                for item in platforms
            ),
            'catalog': AWESOME_CATALOG,
            'license_url': AWESOME_LICENSE,
            'source': 'awesome-selfhosted',
            'installable': False,
        })

    if len(apps) < 100:
        raise ValueError(
            'Awesome Selfhosted catalog format was not recognized'
        )

    return apps


def awesome_selfhosted_data(refresh=False):
    if not refresh and AWESOME_CACHE.exists():
        try:
            cached = json.loads(
                AWESOME_CACHE.read_text()
            )

            if time.time() - cached['saved'] < 21600:
                return cached['apps']

        except Exception:
            pass

    try:
        response = httpx.get(
            AWESOME_README,
            headers={
                'User-Agent': 'NexusCore/1.0'
            },
            timeout=30,
            follow_redirects=True
        )
        response.raise_for_status()
        apps = parse_awesome_selfhosted(
            response.text
        )

        AWESOME_CACHE.write_text(
            json.dumps({
                'saved': time.time(),
                'source': AWESOME_CATALOG,
                'license': 'CC BY-SA 3.0',
                'apps': apps,
            })
        )

        return apps

    except Exception as exc:
        if AWESOME_CACHE.exists():
            try:
                return json.loads(
                    AWESOME_CACHE.read_text()
                )['apps']
            except Exception:
                pass

        raise HTTPException(
            502,
            f'Awesome Selfhosted catalog unavailable: {exc}'
        )


@app.get('/api/apps/awesome-selfhosted')
def awesome_selfhosted_apps(refresh:bool=False):
    inventory, _ = container_inventory_snapshot(
        refresh_if_empty=True
    )
    installed = {
        row.get('name', '').lower()
        for row in inventory
    }
    output = []

    for item in awesome_selfhosted_data(refresh):
        app_item = dict(item)
        app_item['installed'] = (
            app_item['slug'].lower()
            in installed
        )
        output.append(app_item)

    return sorted(
        output,
        key=lambda value: value['name'].lower()
    )


# LinuxServer.io app store

def lsdata(refresh=False):
    if not refresh and CACHE.exists():
        try:
            c=json.loads(CACHE.read_text())
            if time.time()-c['saved']<21600:return c['payload']
        except:pass
    try:
        r=httpx.get(LSAPI,params={'include_config':'true','include_deprecated':'false'},headers={'User-Agent':'NexusCore/1.0'},timeout=25); r.raise_for_status(); payload=r.json(); CACHE.write_text(json.dumps({'saved':time.time(),'payload':payload})); return payload
    except Exception as e:
        if CACHE.exists():
            try:return json.loads(CACHE.read_text())['payload']
            except:pass
        raise HTTPException(502,f'LinuxServer API unavailable: {e}')
def repos(payload):
    data=payload.get('data',payload); r=data.get('repositories',{}) if isinstance(data,dict) else {}; arr=r.get('linuxserver',[]) if isinstance(r,dict) else []; return arr if isinstance(arr,list) else []
def normalize(x):
    name=x.get('name') or x.get('repo') or ''; cfg=x.get('config') or x.get('configuration') or {}; return {'slug':name,'name':x.get('display_name') or name.replace('-',' ').title(),'description':x.get('description') or 'LinuxServer.io container','version':x.get('version',''),'image':f'lscr.io/linuxserver/{name}:latest','docs':f'https://docs.linuxserver.io/images/docker-{name}/','config':cfg,'raw':x}
@app.get('/api/apps/linuxserver')
def apps(refresh:bool=False):
    inventory, _ = container_inventory_snapshot(
        refresh_if_empty=True
    )
    ins = {
        row.get('name')
        for row in inventory
    }
    out=[]
    for x in repos(lsdata(refresh)):
        a=normalize(x); a['installed']=a['slug'] in ins; a.pop('raw',None); out.append(a)
    return sorted(out,key=lambda z:z['name'].lower())
@app.get('/api/apps/linuxserver/{slug}')
def detail(slug:str):
    safe_name(slug)
    for x in repos(lsdata(False)):
        if x.get('name')==slug:
            inventory, _ = container_inventory_snapshot(
                refresh_if_empty=True
            )
            a=normalize(x); a['installed']=slug in {row.get('name') for row in inventory}; return a
    raise HTTPException(404,'LinuxServer image not found')
def extract_config(raw):
    cfg=raw.get('config') or {}; env={'PUID':PUID,'PGID':PGID,'TZ':TZ}; ports={}; volumes={}
    for p in cfg.get('ports',[]) or []:
        i=str(p.get('internal') or '').strip(); e=str(p.get('external') or i).strip()
        if i.isdigit() and e.isdigit():ports[i]=int(e)
    for v in cfg.get('volumes',[]) or []:
        t=str(v.get('path') or '').strip()
        if t.startswith('/'):volumes[t]={'host_path':f'/Compose/{{slug}}/config' if t=='/config' else '','optional':bool(v.get('optional',False))}
    volumes.setdefault('/config',{'host_path':'/Compose/{slug}/config','optional':False}); return env,ports,volumes
def port_busy(port):
    for c in client.containers.list(all=True):
        for vals in (c.attrs.get('HostConfig',{}).get('PortBindings',{}) or {}).values():
            for b in vals or []:
                if str(b.get('HostPort'))==str(port):return c.name
@app.post('/api/apps/linuxserver/{slug}/install')
def install(slug:str,req:InstallReq):
    safe_name(slug)
    try: client.containers.get(slug); raise HTTPException(409,f'Container {slug} already exists')
    except docker.errors.NotFound: pass
    d=detail(slug); env,ports,vols=extract_config(d['raw']); env.update(req.env); env['PUID']=PUID; env['PGID']=PGID; env.setdefault('TZ',TZ); project=COMPOSE_ROOT/slug; svc={'image':d['image'],'container_name':slug,'environment':[f'{k}={v}' for k,v in env.items()],'volumes':[],'restart':'unless-stopped'}
    for target,meta in vols.items():
        hp=(req.paths.get(target) or str(meta.get('host_path') or '').replace('{slug}',slug)).strip()
        if not hp:
            if meta.get('optional'):continue
            raise HTTPException(400,f'Required host path for {target} was not selected')
        if not (hp.startswith('/Compose/') or hp.startswith('/srv/')):raise HTTPException(400,'Host paths must be under /Compose or /srv')
        svc['volumes'].append(f'{hp}:{target}')
    svc['ports']=[]
    selected_host_ports = set()

    for cp,default in ports.items():
        hp = int(req.host_ports.get(cp, default))

        if hp < 1 or hp > 65535:
            raise HTTPException(
                400,
                f'Invalid host port {hp} for container port {cp}'
            )

        if hp in selected_host_ports:
            raise HTTPException(
                409,
                f'Host port {hp} was selected more than once. '
                f'Choose a different host port for container port {cp}.'
            )

        used = port_busy(hp)

        if used:
            raise HTTPException(
                409,
                f'Host port {hp} is used by {used}'
            )

        selected_host_ports.add(hp)
        svc['ports'].append(f'{hp}:{cp}')

    if not svc['ports']:
        svc.pop('ports')

    # Generate the Compose body, but let OMV own the actual Compose file.
    compose_body = yaml.safe_dump(
        {'services': {slug: svc}},
        sort_keys=False
    )

    # Preflight OMV before creating/registering anything.
    try:
        check_status, check_data, check_raw = omv_bridge_request(
            'GET',
            '/compose/files',
            timeout=15,
        )
    except Exception as exc:
        raise HTTPException(
            502,
            f'Could not contact OMV Compose bridge: {exc}'
        )

    if check_status >= 400:
        raise HTTPException(
            502,
            f'Could not check OMV Compose registrations: '
            f'{check_raw[-1500:]}'
        )

    existing_entries = []

    if isinstance(check_data, dict):
        existing_entries = (
            check_data.get('data')
            or check_data.get('items')
            or []
        )
    elif isinstance(check_data, list):
        existing_entries = check_data

    for entry in existing_entries:
        if (
            isinstance(entry, dict)
            and str(entry.get('name', '')).strip() == slug
        ):
            raise HTTPException(
                409,
                f'OMV Compose project {slug} already exists'
            )

    # All path and port validation has already succeeded.
    # Do not create anything before this point.
    if project.exists():
        try:
            project_has_content = any(project.iterdir())
        except Exception:
            project_has_content = True

        if project_has_content:
            raise HTTPException(
                409,
                f'Project directory {project} already exists '
                'and is not empty'
            )

    try:
        bridge_status, omv_entry, bridge_raw = omv_bridge_request(
            'POST',
            '/compose/register',
            {
                'name': slug,
                'description': f'Installed by Kyber Core: {d["name"]}',
                'body': compose_body,
                'showenv': False,
                'env': '',
                'showoverride': False,
                'override': '',
            },
            timeout=30,
        )
    except Exception as exc:
        raise HTTPException(
            502,
            f'Could not contact OMV Compose bridge: {exc}'
        )

    if bridge_status >= 400:
        raise HTTPException(
            502,
            f'OMV registration failed: {bridge_raw[-2000:]}'
        )

    if not isinstance(omv_entry, dict):
        raise HTTPException(
            502,
            'OMV registration returned invalid JSON'
        )

    omv_uuid = omv_entry.get('uuid')

    if not omv_uuid:
        raise HTTPException(
            502,
            'OMV registration did not return a UUID'
        )

    # OMV creates <project>/<project>.yml.
    f = project / f'{slug}.yml'

    def rollback_new_install(reason):
        # This UUID came from the registration performed by THIS request.
        # Never remove config/data manually. OMV deleteFile removes only its
        # generated Compose files and registration, and performs compose down.
        rollback_error = None

        try:
            rollback_status, rollback_data, rollback_raw = omv_bridge_request(
                'POST',
                '/compose/delete',
                {'uuid': omv_uuid},
                timeout=30,
            )

            if rollback_status >= 400:
                rollback_error = rollback_raw[-1500:]

        except Exception as exc:
            rollback_error = str(exc)

        refresh_container_inventory()

        if rollback_error:
            audit(
                'app',
                f'rollback failed for {slug} uuid={omv_uuid}: '
                f'{rollback_error}'
            )

            raise HTTPException(
                500,
                f'{reason} Automatic rollback also failed. '
                f'OMV entry {omv_uuid} may require manual cleanup. '
                f'Rollback error: {rollback_error}'
            )

        audit(
            'app',
            f'rolled back failed install {slug} uuid={omv_uuid}'
        )

        raise HTTPException(
            500,
            f'{reason} The new OMV registration was rolled back. '
            'Application configuration/data was preserved.'
        )

    # Give OMV a moment to finish writing the generated file.
    deadline = time.time() + 10

    while time.time() < deadline and not f.exists():
        time.sleep(0.25)

    if not f.exists():
        rollback_new_install(
            f'OMV registered {slug}, but {f} was not created.'
        )

    try:
        deploy = subprocess.run(
            compose_cli(str(f)) + ['up', '-d'],
            capture_output=True,
            text=True,
            timeout=300,
        )

    except subprocess.TimeoutExpired:
        rollback_new_install(
            f'Deployment of {slug} timed out.'
        )

    if deploy.returncode:
        error_text = (
            deploy.stderr or
            deploy.stdout or
            'Unknown Docker Compose error'
        )

        rollback_new_install(
            f'Deployment of {slug} failed: '
            f'{error_text[-1800:]}'
        )

    # Docker Compose returning zero is not enough.
    # Allow slower applications time to reach the running state.
    installed_container = None
    last_status = 'not-created'
    startup_deadline = time.time() + 30

    while time.time() < startup_deadline:
        try:
            installed_container = client.containers.get(slug)
            installed_container.reload()
            last_status = installed_container.status or 'unknown'

            if last_status == 'running':
                break

            if last_status in ('dead', 'removing'):
                break

        except docker.errors.NotFound:
            last_status = 'not-created'

        except Exception as exc:
            last_status = f'verification-error: {exc}'

        time.sleep(1)

    if installed_container is None or last_status == 'not-created':
        rollback_new_install(
            f'Deployment completed but container {slug} '
            'was not created within 30 seconds.'
        )

    if last_status != 'running':
        log_tail = ''

        try:
            raw_logs = installed_container.logs(
                tail=40,
                timestamps=False,
            )

            if isinstance(raw_logs, bytes):
                log_tail = raw_logs.decode(
                    'utf-8',
                    errors='replace',
                )
            else:
                log_tail = str(raw_logs)

            log_tail = log_tail[-1500:]

        except Exception:
            pass

        reason = (
            f'Container {slug} did not reach the running state '
            f'within 30 seconds. Last state: {last_status!r}.'
        )

        if log_tail:
            reason += ' Recent container output: ' + log_tail

        rollback_new_install(reason)

    refresh_container_inventory()

    audit(
        'app',
        f'installed {slug} through OMV uuid={omv_uuid}'
    )

    return {
        'ok': True,
        'compose': str(f),
        'omv_uuid': omv_uuid,
        'managed_by': 'openmediavault',
        'container_status': installed_container.status,
    }
