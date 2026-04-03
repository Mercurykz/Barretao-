import os
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
from typing import Optional

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


app = FastAPI(title="Barretão Hub", version="2.0.0")
hub_enable_voice = os.getenv("HUB_ENABLE_VOICE", "false").strip().lower() == "true"
agent = PersonalAIAgent(enable_voice=hub_enable_voice)
api_token = os.getenv("HUB_API_TOKEN", "").strip()

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


@app.post("/command", response_model=CommandResponse)
def command(
    payload: CommandRequest,
    authorization: Optional[str] = Header(default=None),
) -> CommandResponse:
    require_token(authorization, api_token)

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
    require_token(authorization, api_token)
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

    print(f"\n🌐 Hub rodando em:")
    print(f"   PC:     {scheme}://localhost:{port}/app/")
    print(f"   Rede:   {scheme}://{local_ip}:{port}/app/")
    print(f"\n📱 No celular (mesma rede Wi-Fi):")
    print(f"   Abra:   {scheme}://{local_ip}:{port}")
    if use_ssl:
        print(f"   ⚠️  Aparecerá aviso 'site não seguro' — clique em 'Avançado' → 'Continuar'")
        print(f"   🎤  Após aceitar, o MICROFONE funcionará normalmente\n")
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
            print("\n🌍 Acesso externo ativado (Cloudflare Tunnel):")
            print(f"   Público: {public_url}/app/")
            print("   Use este link no celular dentro e fora de casa.")
        elif tunnel_err:
            print(f"\n⚠️  Túnel público: {tunnel_err}")

    try:
        uvicorn.run("barretao_hub:app", **run_kwargs)
    finally:
        if tunnel_proc and tunnel_proc.poll() is None:
            tunnel_proc.terminate()
