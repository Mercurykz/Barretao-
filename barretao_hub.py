import os
import sys
import importlib
import pathlib
import socket
import datetime
import ipaddress
import subprocess
import threading
import queue
import time
import re
import shutil
import asyncio
import asyncio.proactor_events
from contextlib import asynccontextmanager
from typing import Optional

# ── Suppress harmless WinError 10054 (browser closed connection) ──────────────
if sys.platform == "win32":
    _orig_call_connection_lost = asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost

    def _patched_call_connection_lost(self, exc):
        try:
            _orig_call_connection_lost(self, exc)
        except ConnectionResetError:
            pass  # client closed the connection abruptly — normal, ignore

    asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost = _patched_call_connection_lost
# ─────────────────────────────────────────────────────────────────────────────

import barretao_auth as auth

# Fix emoji output on Windows terminals
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from personal_ai_agent import PersonalAIAgent

try:
    fastapi_module = importlib.import_module("fastapi")
    pydantic_module = importlib.import_module("pydantic")
    starlette_responses = importlib.import_module("starlette.responses")
    starlette_staticfiles = importlib.import_module("starlette.staticfiles")
except ModuleNotFoundError as e:
    raise SystemExit(
        "Dependência ausente (fastapi/pydantic/aiofiles). Rode com o Python da .venv311:\n"
        "  .\\.venv311\\Scripts\\python.exe barretao_hub.py\n"
        "ou ative a .venv311 antes de executar."
    ) from e

FastAPI = fastapi_module.FastAPI
Header = fastapi_module.Header
HTTPException = fastapi_module.HTTPException
RedirectResponse = starlette_responses.RedirectResponse
FileResponse = starlette_responses.FileResponse
StaticFiles = starlette_staticfiles.StaticFiles
BaseModel = pydantic_module.BaseModel

WEBAPP_DIR = pathlib.Path(__file__).parent / "webapp"
CERTS_DIR  = pathlib.Path(__file__).parent / "certs"


# ── SSL helpers ────────────────────────────────────────────────────────────

def _get_lan_ip() -> str:
    """Returns best LAN IP (192.168/10/172), not VPN."""
    try:
        import subprocess as _sp
        out = _sp.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetIPAddress -AddressFamily IPv4 | Select-Object -ExpandProperty IPAddress"],
            text=True, timeout=5,
        )
        for line in out.splitlines():
            ip = line.strip()
            if ip.startswith(("192.168.", "10.", "172.")):
                return ip
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _ensure_ssl_cert(local_ip: str) -> tuple[str, str] | tuple[None, None]:
    """Generate self-signed cert valid for localhost + local_ip. Returns (cert, key) paths."""
    cert_file = CERTS_DIR / "cert.pem"
    key_file  = CERTS_DIR / "key.pem"

    # Reuse existing cert if present
    if cert_file.exists() and key_file.exists():
        return str(cert_file), str(key_file)

    try:
        x509 = importlib.import_module("cryptography.x509")
        NameOID = importlib.import_module("cryptography.x509.oid").NameOID
        hashes = importlib.import_module("cryptography.hazmat.primitives.hashes")
        serialization = importlib.import_module("cryptography.hazmat.primitives.serialization")
        rsa = importlib.import_module("cryptography.hazmat.primitives.asymmetric.rsa")

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "barretao-local"),
        ])

        san_list = [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]
        try:
            san_list.append(x509.IPAddress(ipaddress.IPv4Address(local_ip)))
        except Exception:
            pass

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
            .sign(key, hashes.SHA256())
        )

        CERTS_DIR.mkdir(exist_ok=True)
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
        return str(cert_file), str(key_file)

    except Exception as e:
        print(f"⚠️  SSL não disponível ({e}). Rodando em HTTP (microfone desabilitado no celular).")
        return None, None


def _start_cloudflare_tunnel(origin_url: str) -> tuple[subprocess.Popen | None, str | None, str | None]:
    """Starts cloudflared quick tunnel and returns (process, public_url, error)."""
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        winget_link = pathlib.Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe"
        if winget_link.exists():
            cloudflared = str(winget_link)
    if not cloudflared:
        return None, None, "cloudflared não encontrado no PATH. Instale para usar acesso externo automático."

    cmd = [
        cloudflared,
        "tunnel",
        "--url",
        origin_url,
        "--no-autoupdate",
    ]
    if origin_url.startswith("https://"):
        cmd.append("--no-tls-verify")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
        )
    except Exception as e:
        return None, None, f"Falha ao iniciar cloudflared: {e}"

    lines: queue.Queue[str] = queue.Queue()

    def _reader() -> None:
        if not proc.stdout:
            return
        for ln in proc.stdout:
            lines.put(ln.strip())

    threading.Thread(target=_reader, daemon=True).start()

    public_url: str | None = None
    pattern = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")
    deadline = time.time() + 20

    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            ln = lines.get(timeout=0.8)
        except queue.Empty:
            continue
        found = pattern.search(ln)
        if found:
            public_url = found.group(0)
            break

    if public_url:
        return proc, public_url, None

    if proc.poll() is not None:
        return None, None, "cloudflared encerrou antes de fornecer URL pública."

    return proc, None, "túnel iniciado, mas URL pública não foi detectada automaticamente."


# ── Autonomous agent loop ────────────────────────────────────────────────────
_auto_enabled:  bool                     = os.getenv("AUTONOMOUS_MODE", "true").lower() == "true"
_auto_last_run: datetime.datetime | None = None
_auto_last_msg: str | None               = None
# Tracks which (user_id, device_id, slot) combos already received a thought today
_auto_sent: set[tuple[str, str, str]] = set()
# Per-user seen email IDs (Message-ID) — resets daily
_auto_email_seen: dict[str, set] = {}
# Email check runs every 3rd tick (≈ 30 min), general tick every 10 min
_auto_email_tick: int = 0


async def _autonomous_loop() -> None:
    """Background task: agent thinks proactively every 10 min, checks emails every 30 min."""
    global _auto_last_run, _auto_last_msg, _auto_sent, _auto_email_seen, _auto_email_tick
    await asyncio.sleep(60)          # 1-min warm-up after startup
    last_date: str = ""
    while True:
        try:
            if _auto_enabled:
                today = datetime.date.today().isoformat()
                if today != last_date:   # reset de-dup sets each calendar day
                    _auto_sent.clear()
                    _auto_email_seen.clear()
                    last_date = today

                _auto_email_tick += 1
                check_emails = (_auto_email_tick % 3 == 0)  # every 3rd tick = 30 min

                # ── General proactive thought ──────────────────────────────
                msg = agent.autonomous_tick()
                _auto_last_run = datetime.datetime.now()

                if msg:
                    _auto_last_msg = msg
                    online = auth.get_all_online_devices()
                    for device in online:
                        uid  = device["user_id"]
                        did  = device["id"]
                        slot = datetime.datetime.now().strftime("%Y-%m-%d-%H")
                        key  = (uid, did, slot)
                        if key not in _auto_sent:
                            _auto_sent.add(key)
                            auth.queue_command(uid, did, f"[PROATIVO] {msg}")

                # ── Autonomous email check (per-user, every 30 min) ────────
                if check_emails:
                    users = auth.get_all_users()
                    online = auth.get_all_online_devices()
                    online_by_user: dict[str, list[dict]] = {}
                    for d in online:
                        online_by_user.setdefault(d["user_id"], []).append(d)

                    for user in users:
                        uid = user["id"]
                        if uid not in online_by_user:
                            continue   # user has no online device right now
                        gmail_int = auth.get_integration(uid, "gmail")
                        if not gmail_int:
                            continue   # no Gmail linked for this user
                        cfg = gmail_int["config"]
                        seen = _auto_email_seen.get(uid, set())
                        email_msg, new_seen = agent.autonomous_email_check(
                            email_addr=cfg.get("email", ""),
                            password=cfg.get("app_password", ""),
                            seen_ids=seen,
                        )
                        _auto_email_seen[uid] = new_seen
                        if email_msg:
                            for device in online_by_user[uid]:
                                auth.queue_command(uid, device["id"], f"[PROATIVO] {email_msg}")

        except Exception as exc:
            print(f"⚠️  Autonomous loop error: {exc}")
        await asyncio.sleep(600)     # tick every 10 minutes


@asynccontextmanager
async def _lifespan(app_):
    task = asyncio.create_task(_autonomous_loop())
    try:
        yield
    finally:
        task.cancel()


class CommandRequest(BaseModel):
    text: str
    source: str = "external"
    user_id: Optional[str] = None


class CommandResponse(BaseModel):
    ok: bool
    answer: str


def require_token(auth_header: Optional[str], expected_token: str) -> None:
    if not expected_token:
        return
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth_header.split(" ", 1)[1].strip()
    if token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid token")


app = FastAPI(title="Barretão Hub", version="2.1.0", lifespan=_lifespan)
hub_enable_voice = os.getenv("HUB_ENABLE_VOICE", "false").strip().lower() == "true"
agent = PersonalAIAgent(enable_voice=hub_enable_voice)
api_token = os.getenv("HUB_API_TOKEN", "").strip()

# Initialize auth DB
auth.init_db()


# ── Auth models ────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    email: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class GmailConnectRequest(BaseModel):
    email: str
    app_password: str


class HassConnectRequest(BaseModel):
    url: str
    token: str


class WebhookFireRequest(BaseModel):
    payload: dict = {}


class DeviceRegisterRequest(BaseModel):
    device_id: str
    name: str
    type: str = "other"  # pc | phone | tablet | console | car | other


class DeviceRenameRequest(BaseModel):
    name: str


class DeviceAckRequest(BaseModel):
    answer: str = ""


def require_auth(authorization: Optional[str]) -> dict:
    """Validates bearer token (session or static API token). Returns user dict."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        # Static API token (MCP / legacy) — treated as system user
        if api_token and token == api_token:
            return {"id": "__system__", "username": "system", "display_name": "System"}
        # Session token
        user = auth.get_user_by_token(token)
        if user:
            return user
    raise HTTPException(status_code=401, detail="Login necessário")


# ── Auth endpoints ─────────────────────────────────────────────────────────
@app.post("/auth/register")
def api_register(payload: RegisterRequest) -> dict:
    """First registration is always allowed. Subsequent ones are locked."""
    count = auth.user_count()
    if count >= 1:
        # Allow re-registration only if a valid session or admin token is provided
        raise HTTPException(
            status_code=403,
            detail="Registro fechado. Este é um assistente pessoal privado.",
        )
    user = auth.register_user(payload.username, payload.password, payload.email, payload.display_name)
    if not user:
        raise HTTPException(status_code=409, detail="Usuário já existe")
    token = auth.login_user(payload.username, payload.password)
    return {"ok": True, "token": token, "user": user}


@app.post("/auth/login")
def api_login(payload: LoginRequest) -> dict:
    token = auth.login_user(payload.username, payload.password)
    if not token:
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")
    user = auth.get_user_by_token(token)
    return {"ok": True, "token": token, "user": user}


@app.get("/auth/me")
def api_me(authorization: Optional[str] = Header(default=None)) -> dict:
    user = require_auth(authorization)
    return {"ok": True, "user": user}


@app.post("/auth/logout")
def api_logout(authorization: Optional[str] = Header(default=None)) -> dict:
    if authorization and authorization.startswith("Bearer "):
        auth.logout_token(authorization.split(" ", 1)[1].strip())
    return {"ok": True}


@app.get("/auth/setup")
def api_setup_status() -> dict:
    """Returns whether first-time setup is needed."""
    return {"needs_setup": auth.user_count() == 0}


# ── Device endpoints ────────────────────────────────────────────────────────
@app.get("/devices")
def api_devices(authorization: Optional[str] = Header(default=None)) -> dict:
    user = require_auth(authorization)
    return {"ok": True, "devices": auth.get_devices(user["id"])}


@app.post("/devices/register")
def api_register_device(
    payload: DeviceRegisterRequest,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    user = require_auth(authorization)
    device = auth.register_device(user["id"], payload.device_id, payload.name, payload.type)
    return {"ok": True, "device": device}


@app.post("/devices/{device_id}/heartbeat")
def api_heartbeat(
    device_id: str,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    user = require_auth(authorization)
    auth.heartbeat_device(device_id, user["id"])
    cmds = auth.get_pending_commands(device_id, user["id"])
    return {"ok": True, "pending_commands": cmds}


@app.post("/devices/{device_id}/ack/{cmd_id}")
def api_ack_command(
    device_id: str,
    cmd_id: str,
    payload: DeviceAckRequest = DeviceAckRequest(),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    require_auth(authorization)
    auth.ack_command(cmd_id, payload.answer)
    return {"ok": True}


@app.post("/devices/{device_id}/command")
def api_send_to_device(
    device_id: str,
    payload: CommandRequest,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    user = require_auth(authorization)
    cmd_id = auth.queue_command(user["id"], device_id, payload.text)
    return {"ok": True, "cmd_id": cmd_id}


@app.patch("/devices/{device_id}")
def api_rename_device(
    device_id: str,
    payload: DeviceRenameRequest,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    user = require_auth(authorization)
    ok = auth.rename_device(device_id, user["id"], payload.name)
    if not ok:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado.")
    return {"ok": True}


@app.delete("/devices/{device_id}")
def api_delete_device(
    device_id: str,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    user = require_auth(authorization)
    ok = auth.delete_device(device_id, user["id"])
    return {"ok": ok}

# ── Serve PWA webapp ───────────────────────────────────────────────────────
if WEBAPP_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")

@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/app/")

@app.get("/app/icon-192.png")
def icon_png() -> FileResponse:
    """Fallback: serve icon.svg when icon-192.png is not present."""
    png_path = WEBAPP_DIR / "icon-192.png"
    svg_path = WEBAPP_DIR / "icon.svg"
    if png_path.exists():
        return FileResponse(str(png_path), media_type="image/png")
    return FileResponse(str(svg_path), media_type="image/svg+xml")

@app.get("/cert")
def download_cert():
    """Serve the self-signed certificate for iOS/Safari installation."""
    cert_file = CERTS_DIR / "cert.pem"
    if not cert_file.exists():
        raise HTTPException(status_code=404, detail="Certificado não gerado ainda.")
    # iOS requires .crt extension and x-x509-ca-cert MIME type to trigger install
    return FileResponse(
        str(cert_file),
        media_type="application/x-x509-ca-cert",
        filename="barretao.crt",
        headers={"Content-Disposition": "attachment; filename=barretao.crt"},
    )

# ── API endpoints ──────────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "barretao-hub", "version": "2.0.0"}


# ── Stats endpoint ─────────────────────────────────────────────────────────
@app.get("/stats")
def api_stats(authorization: Optional[str] = Header(default=None)) -> dict:
    user = require_auth(authorization)
    stats = agent.get_stats_dict()
    devices = auth.get_devices(user["id"])
    gmail_int = auth.get_integration(user["id"], "gmail")
    stats["devices"] = len(devices)
    stats["devices_online"] = sum(1 for d in devices if d.get("is_online"))
    stats["gmail_connected"] = bool(gmail_int)
    stats["gmail_email"] = gmail_int["config"].get("email", "") if gmail_int else ""
    return {"ok": True, **stats}


# ── Memory tags endpoint ────────────────────────────────────────────────────
@app.get("/memory")
def api_memory(authorization: Optional[str] = Header(default=None)) -> dict:
    require_auth(authorization)
    tags = agent.get_memory_tags(limit=30)
    return {"ok": True, "tags": tags}


# ── Integrations endpoints ─────────────────────────────────────────────────
@app.get("/integrations")
def api_integrations(authorization: Optional[str] = Header(default=None)) -> dict:
    user = require_auth(authorization)
    integrations = auth.list_integrations(user["id"])
    # Strip sensitive fields from config before returning
    safe = []
    for intg in integrations:
        cfg = dict(intg["config"])
        if "app_password" in cfg:
            cfg["app_password"] = "****"
        safe.append({"name": intg["name"], "config": cfg, "connected_at": intg["connected_at"]})
    return {"ok": True, "integrations": safe}


@app.post("/integrations/gmail/connect")
def api_gmail_connect(
    payload: GmailConnectRequest,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    user = require_auth(authorization)
    if not payload.email.strip() or not payload.app_password.strip():
        raise HTTPException(status_code=400, detail="E-mail e senha de app são obrigatórios")
    # Test the connection first
    test = agent.fetch_emails_imap(email_addr=payload.email.strip(), password=payload.app_password.strip(), limit=1)
    if test and isinstance(test, list) and test and "error" in test[0]:
        raise HTTPException(status_code=400, detail=f"Falha de conexão: {test[0]['error']}")
    auth.save_integration(user["id"], "gmail", {
        "email": payload.email.strip(),
        "app_password": payload.app_password.strip(),
    })
    return {"ok": True, "message": f"Gmail {payload.email.strip()} conectado com sucesso!"}


@app.delete("/integrations/{name}")
def api_integration_delete(
    name: str,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    user = require_auth(authorization)
    auth.delete_integration(user["id"], name)
    return {"ok": True}


# ── Emails endpoint ─────────────────────────────────────────────────────────
@app.get("/emails")
def api_emails(authorization: Optional[str] = Header(default=None)) -> dict:
    user = require_auth(authorization)
    gmail_int = auth.get_integration(user["id"], "gmail")
    if not gmail_int:
        raise HTTPException(status_code=404, detail="Gmail não configurado. Conecte em Integrações.")
    cfg = gmail_int["config"]
    emails = agent.fetch_emails_imap(
        email_addr=cfg.get("email", ""),
        password=cfg.get("app_password", ""),
        limit=15,
    )
    if emails and "error" in emails[0]:
        raise HTTPException(status_code=502, detail=emails[0]["error"])
    return {"ok": True, "emails": emails, "count": len(emails)}


# ── Autonomous endpoints ──────────────────────────────────────────────────────
@app.get("/autonomous/status")
def api_auto_status(authorization: Optional[str] = Header(default=None)) -> dict:
    """Returns the current state of the autonomous agent loop."""
    require_auth(authorization)
    return {
        "ok": True,
        "enabled": _auto_enabled,
        "last_run": _auto_last_run.isoformat() if _auto_last_run else None,
        "last_message": _auto_last_msg,
    }


@app.post("/autonomous/run")
def api_auto_run(authorization: Optional[str] = Header(default=None)) -> dict:
    """Manually trigger one autonomous tick right now."""
    user = require_auth(authorization)
    msg = agent.autonomous_tick()
    if msg:
        devices = auth.get_devices(user["id"])
        for d in devices:
            auth.queue_command(user["id"], d["id"], f"[PROATIVO] {msg}")
    return {"ok": True, "triggered": bool(msg), "message": msg}


@app.post("/autonomous/toggle")
def api_auto_toggle(authorization: Optional[str] = Header(default=None)) -> dict:
    """Enable or disable the autonomous loop at runtime."""
    global _auto_enabled
    require_auth(authorization)
    _auto_enabled = not _auto_enabled
    return {"ok": True, "enabled": _auto_enabled}


# ── Home Assistant endpoints ──────────────────────────────────────────────────────────────────
@app.post("/integrations/hass/connect")
def api_hass_connect(
    payload: HassConnectRequest,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    user = require_auth(authorization)
    url = payload.url.rstrip("/")
    token = payload.token.strip()
    if not url or not token:
        raise HTTPException(status_code=400, detail="url e token são obrigatórios")
    # Quick connectivity test
    try:
        import requests as _req
        r = _req.get(
            f"{url}/api/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        if not r.ok:
            raise HTTPException(status_code=400, detail=f"HA retornou {r.status_code}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Não foi possível conectar ao HA: {e}")
    auth.save_integration(user["id"], "home_assistant", {"url": url, "token": token})
    # Update agent live
    agent.hass_url = url
    agent.hass_token = token
    agent.hass_enabled = True
    return {"ok": True, "message": f"Home Assistant conectado: {url}"}


@app.get("/hass/entities")
def api_hass_entities(
    domain: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    user = require_auth(authorization)
    # Always try to load from stored integration
    if not agent.hass_enabled:
        ha_int = auth.get_integration(user["id"], "home_assistant")
        if ha_int:
            agent.hass_url = ha_int["config"].get("url", "")
            agent.hass_token = ha_int["config"].get("token", "")
            agent.hass_enabled = bool(agent.hass_url and agent.hass_token)
    if not agent.hass_enabled:
        raise HTTPException(status_code=404, detail="Home Assistant não configurado")
    entities = agent.list_hass_entities(domain_filter=domain or "")
    return {"ok": True, "entities": entities, "count": len(entities)}


@app.post("/hass/{domain}/{service}")
def api_hass_service(
    domain: str,
    service: str,
    entity_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    user = require_auth(authorization)
    if not agent.hass_enabled:
        ha_int = auth.get_integration(user["id"], "home_assistant")
        if ha_int:
            agent.hass_url = ha_int["config"].get("url", "")
            agent.hass_token = ha_int["config"].get("token", "")
            agent.hass_enabled = bool(agent.hass_url and agent.hass_token)
    if not agent.hass_enabled:
        raise HTTPException(status_code=404, detail="Home Assistant não configurado")
    result = agent.run_hass_command(domain, service, entity_id or "")
    return {"ok": True, "result": result}


# ── Google Calendar endpoint ────────────────────────────────────────────────────────────────
@app.get("/calendar")
def api_calendar(
    days: int = 7,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    require_auth(authorization)
    result = agent.get_calendar_events(days_ahead=days)
    return {"ok": True, "text": result}


# ── Generic reactive webhook ────────────────────────────────────────────────────────────────
@app.post("/webhook/{source}")
def api_webhook(
    source: str,
    payload: WebhookFireRequest,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """
    Generic reactive webhook: POST /webhook/github, /webhook/zapier, etc.
    Builds a proactive message and queues it to all online devices.
    Auth is optional — if no session token, accept any call (public webhook).
    """
    # Try to get user from auth; fall back to system if public
    try:
        user = require_auth(authorization)
        uid = user["id"]
    except HTTPException:
        uid = None

    summary_lines = [f"🔔 Webhook recebido: *{source}*"]
    for k, v in (payload.payload or {}).items():
        summary_lines.append(f"  {k}: {str(v)[:80]}")
    summary = "\n".join(summary_lines[:8])

    # Queue to all online devices
    online = auth.get_all_online_devices()
    sent = 0
    for dev in online:
        if uid and dev["user_id"] != uid:
            continue
        auth.queue_command(dev["user_id"], dev["id"], f"[PROATIVO] {summary}")
        sent += 1

    return {"ok": True, "source": source, "delivered_to": sent}


@app.post("/command", response_model=CommandResponse)
def command(
    payload: CommandRequest,
    authorization: Optional[str] = Header(default=None),
) -> CommandResponse:
    require_auth(authorization)  # aceita session token OU api_token estático

    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    try:
        answer = agent.answer_command(text, allow_confirmation=False)
    except Exception as e:
        err = str(e)
        if "11434" in err or "localhost" in err or "Connection" in err:
            answer = "❌ O Ollama não está rodando. Inicie com: ollama run llama3.1:8b"
        else:
            answer = f"❌ Erro interno: {err}"
    return CommandResponse(ok=True, answer=answer)


@app.get("/briefing", response_model=CommandResponse)
def briefing(authorization: Optional[str] = Header(default=None)) -> CommandResponse:
    require_auth(authorization)  # aceita session token OU api_token estático
    try:
        return CommandResponse(ok=True, answer=agent.daily_briefing())
    except Exception as e:
        return CommandResponse(ok=True, answer=f"❌ Erro ao gerar briefing: {e}")


if __name__ == "__main__":
    uvicorn = importlib.import_module("uvicorn")

    host     = os.getenv("HUB_HOST", "0.0.0.0")
    port     = int(os.getenv("HUB_PORT", "8787"))
    local_ip = _get_lan_ip()

    cert_file, key_file = _ensure_ssl_cert(local_ip)
    use_ssl = cert_file is not None
    scheme  = "https" if use_ssl else "http"
    enable_public_tunnel = os.getenv("PUBLIC_TUNNEL", "false").strip().lower() == "true"

    tunnel_proc: subprocess.Popen | None = None
    public_url: str | None = None
    tunnel_err: str | None = None

    FIXED_PUBLIC_URL = os.getenv("BARRETAO_PUBLIC_URL", "https://barretao.myaiv4.com")

    print(f"\n🌐 Hub rodando em:")
    print(f"   PC:     {scheme}://localhost:{port}/app/")
    print(f"   Rede:   {scheme}://{local_ip}:{port}/app/")
    print(f"\n📱 No celular — use sempre esta URL fixa:")
    print(f"   🔗  {FIXED_PUBLIC_URL}/app/")
    print(f"   (Cloudflare Tunnel permanente — funciona dentro e fora de casa)\n")
    if use_ssl:
        pass  # SSL do Cloudflare já cobre o acesso externo
    else:
        print(f"   Depois: Menu → Adicionar à tela inicial\n")

    run_kwargs: dict = dict(host=host, port=port, reload=False)
    if use_ssl:
        run_kwargs["ssl_certfile"] = cert_file
        run_kwargs["ssl_keyfile"]  = key_file

    if enable_public_tunnel:
        origin_url = f"{scheme}://127.0.0.1:{port}"
        tunnel_proc, public_url, tunnel_err = _start_cloudflare_tunnel(origin_url)
        if public_url:
            print("\n🌍 Túnel temporário também ativo (Cloudflare Quick Tunnel):")
            print(f"   Público: {public_url}/app/")
        elif tunnel_err:
            print(f"\n⚠️  Túnel público: {tunnel_err}")

    try:
        uvicorn.run("barretao_hub:app", **run_kwargs)
    finally:
        if tunnel_proc and tunnel_proc.poll() is None:
            tunnel_proc.terminate()
