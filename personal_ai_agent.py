import os
import sqlite3
import importlib
import subprocess
import webbrowser
import time
import re
import unicodedata
import difflib
import threading
import urllib.parse
import asyncio
import tempfile
import uuid
import queue
import socket
from datetime import datetime
from typing import Any

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    resolved_db_path = (db_path or os.getenv("AGENT_DB_PATH", "agent_memory.db")).strip()
    conn = sqlite3.connect(resolved_db_path, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shortcuts (
            name TEXT PRIMARY KEY,
            actions TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS routine_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            target TEXT NOT NULL,
            executed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS aliases (
            name TEXT PRIMARY KEY,
            target TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS personal_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weekday INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profile (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS learned_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            fact TEXT NOT NULL,
            source TEXT NOT NULL,
            learned_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL,
            tags TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_topic ON knowledge_base(topic)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_category ON knowledge_base(category)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_updated_at ON knowledge_base(updated_at)"
    )
    conn.commit()
    return conn


class VoiceIO:
    def __init__(
        self,
        language: str,
        stt_engine: str,
        auto_speak: bool,
        tts_rate: int,
        tts_volume: float,
        tts_voice_hint: str,
        tts_humanized: bool,
        tts_provider: str,
        edge_tts_voice: str,
        edge_tts_rate: str,
        edge_tts_volume: str,
    ) -> None:
        self.language = language
        self.stt_engine = stt_engine.lower().strip()
        self.auto_speak = auto_speak
        self.enabled = True
        self.tts_rate = tts_rate
        self.tts_volume = max(0.0, min(1.0, tts_volume))
        self.tts_voice_hint = tts_voice_hint.strip().lower()
        self.tts_humanized = tts_humanized
        self.tts_provider = tts_provider.strip().lower()
        self.edge_tts_voice = edge_tts_voice.strip() or "pt-BR-FranciscaNeural"
        self.edge_tts_rate = edge_tts_rate.strip() or "+0%"
        self.edge_tts_volume = edge_tts_volume.strip() or "+0%"

        self._stop_signal = threading.Event()
        self._speak_queue: queue.Queue[str] = queue.Queue()
        self._speaker_thread = threading.Thread(target=self._speaker_loop, daemon=True)

        self.pyttsx3: Any | None = None
        self.sr: Any | None = None
        self.tts_engine: Any | None = None
        self.recognizer: Any | None = None

        self._init_tts()
        self._init_stt()
        self._speaker_thread.start()

    def set_edge_voice(self, voice_id: str) -> bool:
        candidate = voice_id.strip()
        if not candidate:
            return False
        if "Neural" not in candidate and "Multilingual" not in candidate:
            return False
        self.edge_tts_voice = candidate
        return True

    def apply_voice_preset(self, preset: str) -> tuple[bool, str]:
        p = preset.strip().lower()
        presets: dict[str, tuple[str, str]] = {
            "feminina": ("pt-BR-FranciscaNeural", "pt-br"),
            "masculina": ("pt-BR-AntonioNeural", "pt-br"),
            "profissional": ("pt-BR-AntonioNeural", "portuguese"),
            "natural": ("pt-BR-FranciscaNeural", "pt-br"),
        }
        if p not in presets:
            return False, "Preset de voz inválido. Use: feminina, masculina, profissional ou natural."

        edge_voice, hint = presets[p]
        self.edge_tts_voice = edge_voice
        self.tts_voice_hint = hint
        self._select_tts_voice()
        return True, f"Voz alterada para '{p}' ({edge_voice})."

    def _init_tts(self) -> None:
        try:
            self.pyttsx3 = importlib.import_module("pyttsx3")
            self.tts_engine = self.pyttsx3.init()
            self.tts_engine.setProperty("rate", self.tts_rate)
            self.tts_engine.setProperty("volume", self.tts_volume)
            self._select_tts_voice()
        except Exception:
            self.tts_engine = None

    def _select_tts_voice(self) -> None:
        if not self.tts_engine:
            return

        try:
            voices = self.tts_engine.getProperty("voices") or []
        except Exception:
            return

        preferred_tokens = [
            self.tts_voice_hint,
            self.language.lower(),
            "pt-br",
            "portuguese",
            "portugues",
            "brazil",
            "maria",
            "helena",
        ]
        preferred_tokens = [token for token in preferred_tokens if token]

        def score_voice(v: Any) -> int:
            text = " ".join(
                [
                    str(getattr(v, "id", "")),
                    str(getattr(v, "name", "")),
                    str(getattr(v, "languages", "")),
                ]
            ).lower()
            return sum(1 for token in preferred_tokens if token in text)

        best_voice = None
        best_score = -1
        for voice in voices:
            points = score_voice(voice)
            if points > best_score:
                best_score = points
                best_voice = voice

        if best_voice and best_score > 0:
            self.tts_engine.setProperty("voice", best_voice.id)

    def _humanize_text(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if self.tts_humanized:
            cleaned = cleaned.replace("...", ".")
            cleaned = cleaned.replace(":", ",")
            cleaned = cleaned.replace(";", ",")
            cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
        return cleaned

    def _init_stt(self) -> None:
        try:
            self.sr = importlib.import_module("speech_recognition")
            self.recognizer = self.sr.Recognizer()
        except Exception:
            self.recognizer = None

    def speak(self, text: str, force: bool = False) -> None:
        if not force and (not self.enabled or not self.auto_speak):
            return

        say_text = self._humanize_text(text)
        self._speak_queue.put(say_text)

    def _speaker_loop(self) -> None:
        while True:
            text = self._speak_queue.get()
            if not text:
                continue
            self._stop_signal.clear()

            if self.tts_provider == "edge":
                ok = self._speak_with_edge_tts(text)
                if ok:
                    continue

            if self.tts_engine:
                try:
                    self.tts_engine.say(text)
                    self.tts_engine.runAndWait()
                except Exception:
                    pass

    def stop_speaking(self) -> None:
        self._stop_signal.set()
        try:
            if self.tts_engine:
                self.tts_engine.stop()
        except Exception:
            pass
        try:
            pygame = importlib.import_module("pygame")
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass

        try:
            while not self._speak_queue.empty():
                self._speak_queue.get_nowait()
        except Exception:
            pass

    def _speak_with_edge_tts(self, text: str) -> bool:
        try:
            edge_tts = importlib.import_module("edge_tts")
            pygame = importlib.import_module("pygame")
        except Exception:
            return False

        file_path = os.path.join(
            tempfile.gettempdir(), f"barretao_tts_{uuid.uuid4().hex}.mp3"
        )

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.edge_tts_voice,
                rate=self.edge_tts_rate,
                volume=self.edge_tts_volume,
            )
            asyncio.run(communicate.save(file_path))

            if not pygame.mixer.get_init():
                pygame.mixer.init()

            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if self._stop_signal.is_set():
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.05)
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass
            return True
        except Exception:
            return False
        finally:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

    def listen_once(self) -> str:
        if not self.sr or not self.recognizer:
            raise RuntimeError("STT indisponível. Instale SpeechRecognition e pocketsphinx.")

        try:
            with self.sr.Microphone() as source:
                print("🎙️ Ouvindo...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=20)
        except Exception as e:
            raise RuntimeError(f"Erro no microfone: {e}") from e

        try:
            if self.stt_engine == "sphinx":
                try:
                    return self.recognizer.recognize_sphinx(audio, language=self.language)
                except Exception:
                    return self.recognizer.recognize_google(audio, language=self.language)
            return self.recognizer.recognize_google(audio, language=self.language)
        except Exception as e:
            raise RuntimeError(f"Não entendi o áudio: {e}") from e


class SilentVoice:
    def __init__(self) -> None:
        self.auto_speak = False
        self.enabled = False

    def speak(self, text: str, force: bool = False) -> None:
        return

    def stop_speaking(self) -> None:
        return

    def listen_once(self) -> str:
        raise RuntimeError("Voz desativada neste modo.")


class LocalOllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float,
        provider: str = "ollama",
        api_key: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.provider = provider.strip().lower() or "ollama"
        self.api_key = api_key.strip()
        self.requests = importlib.import_module("requests")

    def _messages_to_text(self, messages: list[dict[str, str]]) -> str:
        parts: list[str] = []
        for msg in messages:
            role = str(msg.get("role", "user")).strip()
            content = str(msg.get("content", "")).strip()
            if content:
                parts.append(f"[{role}] {content}")
        return "\n\n".join(parts)

    def chat(self, messages: list[dict[str, str]]) -> str:
        if self.provider in {"openai", "openai-compatible", "openrouter", "groq"}:
            url = f"{self.base_url}/v1/chat/completions"
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
            }
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            response = self.requests.post(url, json=payload, headers=headers, timeout=180)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") if isinstance(data, dict) else None
            if choices and isinstance(choices, list):
                msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                return str(msg.get("content", "")).strip()
            return ""

        if self.provider == "gemini":
            endpoint = f"{self.base_url}/v1beta/models/{self.model}:generateContent"
            params = {"key": self.api_key} if self.api_key else None
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": self._messages_to_text(messages)}],
                    }
                ],
                "generationConfig": {"temperature": self.temperature},
            }
            response = self.requests.post(endpoint, params=params, json=payload, timeout=180)
            response.raise_for_status()
            data = response.json()
            candidates = data.get("candidates") if isinstance(data, dict) else None
            if candidates and isinstance(candidates, list):
                content = candidates[0].get("content", {}) if isinstance(candidates[0], dict) else {}
                parts = content.get("parts", []) if isinstance(content, dict) else []
                if parts and isinstance(parts, list):
                    return str(parts[0].get("text", "")).strip()
            return ""

        # default: ollama
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        response = self.requests.post(url, json=payload, timeout=180)
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "").strip()

    def is_available(self) -> bool:
        try:
            if self.provider in {"openai", "openai-compatible", "openrouter", "groq"}:
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                response = self.requests.get(f"{self.base_url}/v1/models", headers=headers, timeout=5)
                return response.status_code < 500
            if self.provider == "gemini":
                params = {"key": self.api_key} if self.api_key else None
                response = self.requests.get(f"{self.base_url}/v1beta/models", params=params, timeout=5)
                return response.status_code < 500
            response = self.requests.get(f"{self.base_url}/api/tags", timeout=3)
            return response.status_code < 500
        except Exception:
            return False

    def list_available_models(self) -> list[str]:
        try:
            if self.provider in {"openai", "openai-compatible", "openrouter", "groq"}:
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                response = self.requests.get(f"{self.base_url}/v1/models", headers=headers, timeout=8)
                response.raise_for_status()
                data = response.json()
                items = data.get("data", []) if isinstance(data, dict) else []
                names: list[str] = []
                for item in items:
                    model_id = str(item.get("id", "")).strip() if isinstance(item, dict) else ""
                    if model_id:
                        names.append(model_id)
                return names

            if self.provider == "gemini":
                params = {"key": self.api_key} if self.api_key else None
                response = self.requests.get(f"{self.base_url}/v1beta/models", params=params, timeout=8)
                response.raise_for_status()
                data = response.json()
                items = data.get("models", []) if isinstance(data, dict) else []
                names: list[str] = []
                for item in items:
                    name = str(item.get("name", "")).strip() if isinstance(item, dict) else ""
                    # retorno: models/gemini-1.5-flash
                    if name.startswith("models/"):
                        name = name.split("/", 1)[1]
                    if name:
                        names.append(name)
                return names

            response = self.requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            data = response.json()
            models = data.get("models", []) if isinstance(data, dict) else []
            names: list[str] = []
            for item in models:
                name = str(item.get("name", "")).strip() if isinstance(item, dict) else ""
                if name:
                    names.append(name)
            return names
        except Exception:
            return []


class PersonalAIAgent:
    def __init__(self, enable_voice: bool = True) -> None:
        dotenv = importlib.import_module("dotenv")
        dotenv.load_dotenv()

        self.agent_name = os.getenv("AGENT_NAME", "Assistente")
        self.wake_name = os.getenv("WAKE_NAME", self.agent_name).strip().lower()
        self.llm_provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
        self.model = (
            os.getenv("LLM_MODEL", "").strip()
            or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
            or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        )
        self.temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0.7"))
        self.multi_model_enabled = os.getenv("MULTI_MODEL_ENABLED", "false").lower() == "true"
        self.multi_model_mode = os.getenv("MULTI_MODEL_MODE", "primary_fallback").strip().lower()
        if self.multi_model_mode not in {"primary_fallback", "smart_router", "round_robin"}:
            self.multi_model_mode = "primary_fallback"
        self.auto_use_all_models = os.getenv("AUTO_USE_ALL_MODELS", "false").lower() == "true"
        self.secondary_model = os.getenv("OLLAMA_MODEL_SECONDARY", "").strip()
        primary_base = os.getenv("LLM_BASE_URL", "").strip() or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        primary_key = os.getenv("LLM_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
        self.client = LocalOllamaClient(
            base_url=primary_base,
            model=self.model,
            temperature=self.temperature,
            provider=self.llm_provider,
            api_key=primary_key,
        )
        self.secondary_client: LocalOllamaClient | None = None
        if self.multi_model_enabled and self.secondary_model:
            secondary_base = os.getenv("OLLAMA_BASE_URL_SECONDARY", primary_base)
            self.secondary_client = LocalOllamaClient(
                base_url=secondary_base,
                model=self.secondary_model,
                temperature=self.temperature,
                provider=self.llm_provider,
                api_key=primary_key,
            )
        self.model_pool: list[LocalOllamaClient] = []
        self._rr_index = 0
        self._refresh_model_pool()

        self.voice = (
            VoiceIO(
                language=os.getenv("VOICE_LANGUAGE", "pt-BR"),
                stt_engine=os.getenv("STT_ENGINE", "sphinx"),
                auto_speak=os.getenv("AUTO_SPEAK", "true").lower() == "true",
                tts_rate=int(os.getenv("TTS_RATE", "165")),
                tts_volume=float(os.getenv("TTS_VOLUME", "1.0")),
                tts_voice_hint=os.getenv("TTS_VOICE_HINT", "pt-br"),
                tts_humanized=os.getenv("TTS_HUMANIZED", "true").lower() == "true",
                tts_provider=os.getenv("TTS_PROVIDER", "edge"),
                edge_tts_voice=os.getenv("EDGE_TTS_VOICE", "pt-BR-FranciscaNeural"),
                edge_tts_rate=os.getenv("EDGE_TTS_RATE", "+0%"),
                edge_tts_volume=os.getenv("EDGE_TTS_VOLUME", "+0%"),
            )
            if enable_voice
            else SilentVoice()
        )
        self.routine_learning_enabled = (
            os.getenv("ROUTINE_LEARNING", "true").lower() == "true"
        )
        self.proactive_enabled = os.getenv("PROACTIVE_MODE", "true").lower() == "true"
        self.proactive_min_count = int(os.getenv("PROACTIVE_MIN_COUNT", "2"))
        self.last_proactive_slot: str | None = None
        self.discord_enabled = os.getenv("DISCORD_ENABLED", "false").lower() == "true"
        self.discord_trigger = os.getenv("DISCORD_TRIGGER", "!barretao").strip()
        self.discord_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        self.user_city = os.getenv("USER_CITY", "").strip()
        self.user_country = os.getenv("USER_COUNTRY", "BR").strip().upper()
        self.auto_city_by_ip = os.getenv("AUTO_CITY_BY_IP", "true").lower() == "true"
        self.force_chrome = os.getenv("FORCE_CHROME", "false").lower() == "true"
        self.chrome_path = os.getenv("CHROME_PATH", "").strip()
        self.persona_mode = os.getenv("PERSONA_MODE", "default").strip().lower()
        self.persona_humor = os.getenv("PERSONA_HUMOR", "medio").strip().lower()
        self._cached_ip_city: str | None = None
        channel_ids = os.getenv("DISCORD_CHANNEL_IDS", "").strip()
        self.discord_channel_ids = {
            int(item.strip())
            for item in channel_ids.split(",")
            if item.strip().isdigit()
        }

        self.conn = init_db()
        self.history: list[dict[str, str]] = []

        self._restore_voice_preferences()

        self.system_prompt = self.build_system_prompt()

    def _refresh_model_pool(self) -> None:
        pool: list[LocalOllamaClient] = [self.client]
        if self.secondary_client:
            pool.append(self.secondary_client)

        if self.auto_use_all_models:
            discovered = self.client.list_available_models()
            for model_name in discovered:
                if model_name == self.client.model:
                    continue
                if self.secondary_client and model_name == self.secondary_client.model:
                    continue
                pool.append(
                    LocalOllamaClient(
                        base_url=self.client.base_url,
                        model=model_name,
                        temperature=self.temperature,
                        provider=self.client.provider,
                        api_key=self.client.api_key,
                    )
                )

        unique: list[LocalOllamaClient] = []
        seen: set[str] = set()
        for cli in pool:
            key = f"{cli.base_url}|{cli.model}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(cli)

        self.model_pool = unique

    def _get_chat_clients(self, purpose: str = "chat") -> list[LocalOllamaClient]:
        clients = self.model_pool[:] if self.model_pool else [self.client]
        if len(clients) == 1:
            return clients

        if self.multi_model_mode == "round_robin":
            start = self._rr_index % len(clients)
            self._rr_index += 1
            return clients[start:] + clients[:start]

        if self.multi_model_mode == "smart_router":
            preferred: list[LocalOllamaClient] = []
            fallback: list[LocalOllamaClient] = []
            for cli in clients:
                model_n = self.normalize_text(cli.model)
                light_hint = any(k in model_n for k in {"mistral", "phi", "qwen", "deepseek"})
                if purpose in {"extract", "seed", "learn"} and light_hint:
                    preferred.append(cli)
                elif purpose in {"chat", "web"} and not light_hint:
                    preferred.append(cli)
                else:
                    fallback.append(cli)
            return preferred + fallback if preferred else clients

        # default: primary_fallback
        return clients

    def _chat_with_models(self, messages: list[dict[str, str]], purpose: str = "chat") -> str:
        last_error: Exception | None = None
        for cli in self._get_chat_clients(purpose=purpose):
            try:
                return cli.chat(messages)
            except Exception as e:
                last_error = e
                continue
        if last_error:
            raise last_error
        raise RuntimeError("Nenhum modelo disponível para responder.")

    def get_model_status(self) -> str:
        rows = [f"- provider: {self.client.provider}"]
        rows.append(f"- primário: {self.client.model} @ {self.client.base_url}")
        rows.append(f"- modo: {self.multi_model_mode}")
        rows.append(f"- multi-modelo: {'ativado' if len(self.model_pool) > 1 else 'desativado'}")
        rows.append(f"- auto usar todos os modelos: {'on' if self.auto_use_all_models else 'off'}")
        rows.append(f"- total no pool: {len(self.model_pool)}")
        if self.secondary_client:
            rows.append(f"- secundário fixo: {self.secondary_client.model} @ {self.secondary_client.base_url}")
        for idx, cli in enumerate(self.model_pool[:12], start=1):
            rows.append(f"  {idx}. {cli.model}")
        if len(self.model_pool) > 12:
            rows.append(f"  ... +{len(self.model_pool) - 12} modelos")
        return "🧠 Status dos modelos:\n" + "\n".join(rows)

    def refresh_models(self) -> str:
        self._refresh_model_pool()
        return f"✅ Pool de modelos atualizado. Total: {len(self.model_pool)}"

    def _any_llm_available(self) -> bool:
        for cli in self._get_chat_clients(purpose="seed"):
            if cli.is_available():
                return True
        return False

    def _restore_voice_preferences(self) -> None:
        if isinstance(self.voice, SilentVoice):
            return
        try:
            row_custom = self.conn.execute(
                "SELECT value FROM user_profile WHERE key = 'voice_edge'"
            ).fetchone()
            if row_custom and str(row_custom[0]).strip():
                self.voice.set_edge_voice(str(row_custom[0]).strip())
                return

            row_profile = self.conn.execute(
                "SELECT value FROM user_profile WHERE key = 'voz_perfil'"
            ).fetchone()
            if row_profile and str(row_profile[0]).strip():
                self.voice.apply_voice_preset(str(row_profile[0]).strip())
        except Exception:
            pass

    def get_voice_status(self) -> str:
        if isinstance(self.voice, SilentVoice):
            return "Voz desativada neste modo."
        return (
            "🎙️ Voz atual:\n"
            f"- Provider: {self.voice.tts_provider}\n"
            f"- Edge voice: {self.voice.edge_tts_voice}\n"
            f"- Auto speak: {'on' if self.voice.auto_speak else 'off'}"
        )

    def set_voice_profile(self, raw_profile: str) -> str:
        if isinstance(self.voice, SilentVoice):
            return "Voz desativada neste modo."

        profile_raw = raw_profile.strip()
        profile_n = self.normalize_text(profile_raw)
        if not profile_raw:
            return "Use: alterar voz para <feminina|masculina|profissional|natural|pt-BR-...Neural>"

        alias_map = {
            "feminina": "feminina",
            "mulher": "feminina",
            "voz feminina": "feminina",
            "masculina": "masculina",
            "homem": "masculina",
            "voz masculina": "masculina",
            "profissional": "profissional",
            "natural": "natural",
        }
        target = alias_map.get(profile_n)

        if target:
            ok, msg = self.voice.apply_voice_preset(target)
            if not ok:
                return msg
            self.save_user_fact("voz_perfil", target)
            self.save_user_fact("voice_edge", self.voice.edge_tts_voice)
            self.voice.speak("Voz atualizada com sucesso.", force=True)
            return f"✅ {msg}"

        custom = profile_raw.replace("voz ", "").strip()
        if self.voice.set_edge_voice(custom):
            self.save_user_fact("voz_perfil", "custom")
            self.save_user_fact("voice_edge", self.voice.edge_tts_voice)
            self.voice.speak("Voz atualizada com sucesso.", force=True)
            return f"✅ Voz custom aplicada: {self.voice.edge_tts_voice}"

        return "Não reconheci a voz. Exemplos: 'alterar voz para masculina' ou 'alterar voz para pt-BR-AntonioNeural'."

    def build_system_prompt(self) -> str:
        base = (
            f"Você é {self.agent_name}, um assistente pessoal 100%% funcional e adaptativo. "
            "Você aprende sobre o usuário a cada conversa — preferências, hábitos, gostos, rotina — "
            "e usa esse conhecimento para personalizar cada resposta cada vez mais. "
            "Use o perfil do usuário sempre que relevante para dar respostas mais precisas e contextualizadas. "
            "Responda em português do Brasil. "
            "Quando útil, proponha passos curtos e acionáveis."
        )

        if self.persona_mode in {"grok", "grok-like", "grok_like", "irreverente"}:
            humor_map = {
                "baixo": "tom sério com pitadas leves de humor",
                "medio": "tom direto e irreverente, com humor moderado",
                "alto": "tom ousado e bem-humorado, sem perder clareza",
            }
            humor_tone = humor_map.get(self.persona_humor, humor_map["medio"])
            return (
                base
                + " Use frases curtas e objetivas. "
                + f"Adote {humor_tone}. "
                + "Se a pergunta for factual, priorize precisão e diga quando houver incerteza. "
                + "Evite enrolação."
            )

        return base

    # ── Perfil do usuário ──────────────────────────────────────────────────

    def save_user_fact(self, key: str, value: str) -> str:
        k = key.strip().lower()
        v = value.strip()
        if not k or not v:
            return "Chave ou valor inválido."
        self.conn.execute(
            """
            INSERT INTO user_profile (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (k, v, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return f"Aprendi: {k} = {v}"

    def get_user_facts(self) -> list[tuple[str, str, str]]:
        cur = self.conn.execute(
            "SELECT key, value, updated_at FROM user_profile ORDER BY key ASC"
        )
        return cur.fetchall()

    def delete_user_fact(self, key: str) -> str:
        k = key.strip().lower()
        if not k:
            return "Informe o que quer que eu esqueça."
        cur = self.conn.execute("DELETE FROM user_profile WHERE key = ?", (k,))
        self.conn.commit()
        if cur.rowcount:
            return f"Esqueci: {k}"
        # try learned_facts too
        cur2 = self.conn.execute(
            "DELETE FROM learned_facts WHERE category = ? OR fact LIKE ?",
            (k, f"%{k}%"),
        )
        self.conn.commit()
        if cur2.rowcount:
            return f"Removi aprendizados relacionados a '{k}'."
        return f"Não tenho nada salvo com o nome '{k}'."

    def save_learned_fact(self, category: str, fact: str, source: str = "conversa") -> None:
        # Avoid exact duplicates
        cur = self.conn.execute(
            "SELECT id FROM learned_facts WHERE category = ? AND fact = ?",
            (category.strip().lower(), fact.strip()),
        )
        if cur.fetchone():
            return
        self.conn.execute(
            "INSERT INTO learned_facts (category, fact, source, learned_at) VALUES (?, ?, ?, ?)",
            (
                category.strip().lower(),
                fact.strip(),
                source.strip(),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()

    def get_learned_facts(self, limit: int = 20) -> list[tuple[int, str, str]]:
        cur = self.conn.execute(
            "SELECT id, category, fact FROM learned_facts ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    def format_user_profile_context(self) -> str:
        facts = self.get_user_facts()
        learned = self.get_learned_facts(limit=12)
        parts: list[str] = []
        if facts:
            lines = [f"- {k}: {v}" for k, v, _ in facts]
            parts.append("O que sei sobre o usuário:\n" + "\n".join(lines))
        if learned:
            lines = [f"- [{cat}] {fact}" for _, cat, fact in learned]
            parts.append("Outros aprendizados sobre o usuário:\n" + "\n".join(lines))
        return "\n\n".join(parts)

    def show_user_profile(self) -> str:
        facts = self.get_user_facts()
        learned = self.get_learned_facts(limit=20)
        if not facts and not learned:
            return (
                "Ainda não aprendi nada específico sobre você.\n"
                "Fale comigo normalmente — quanto mais conversarmos, mais vou aprendendo."
            )
        lines = ["📋 O que sei sobre você:\n"]
        if facts:
            for k, v, updated in facts:
                lines.append(f"  {k}: {v}")
        if learned:
            lines.append("\n💡 Outros aprendizados:")
            for _, cat, fact in learned:
                lines.append(f"  [{cat}] {fact}")
        lines.append(
            "\nDica: use '/esquecer <chave>' para apagar algo que aprendi errado."
        )
        return "\n".join(lines)

    # ── Extração de fatos ──────────────────────────────────────────────────

    def _extract_facts_quick(self, text: str) -> None:
        """Extrai fatos óbvios da mensagem por regex, sem LLM."""
        # Nome
        for pat in [
            r"(?:meu nome [eé]|me chamo|pode me chamar de|me chamam de)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s]{1,25})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip().rstrip(".,!?")
                if 1 < len(name.split()) <= 4 or (len(name) >= 2 and " " not in name):
                    self.save_user_fact("nome", name)
                    break

        # Cidade / onde mora
        for pat in [
            r"(?:eu moro em|moro em|sou de|minha cidade [eé]|vivo em|resido em|minha cidade natal [eé])\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\-]{2,30})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                city = m.group(1).strip().rstrip(".,!?")
                city = re.split(r"\s+(?:de|do|da|no|na|em)\s+", city)[0].strip()
                if len(city.split()) <= 3 and len(city) >= 2:
                    self.save_user_fact("cidade", city)
                    if not self.user_city:
                        self.user_city = city
                    break

        # Idade
        for pat in [
            r"(?:tenho|minha idade [eé]|com)\s+(\d{1,2})\s+anos",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                self.save_user_fact("idade", f"{m.group(1)} anos")
                break

        # Profissão
        for pat in [
            r"(?:trabalho como|sou (?:um |uma )?|minha profiss[aã]o [eé]|trabalho de)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s]{3,30})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                job = m.group(1).strip().rstrip(".,!?")
                if len(job.split()) <= 4:
                    self.save_user_fact("profissão", job)
                    break

    def _background_learn(self, user_msg: str, agent_reply: str) -> None:
        """Roda em daemon thread: usa LLM para extrair fatos da conversa."""

        def _learn() -> None:
            try:
                prompt = (
                    "Analise a mensagem do usuário abaixo e extraia SOMENTE fatos "
                    "explícitos e concretos sobre o usuário (preferências, gostos, "
                    "hábitos, objetivos, informações pessoais declaradas pelo próprio).\n"
                    "Retorne um JSON compacto com chaves em português minúsculo e sem acentos, sem markdown.\n"
                    "Se não houver nada relevante, retorne exatamente: {}\n\n"
                    "Exemplos de chaves válidas: gosta_de, nao_gosta_de, hobby, "
                    "objetivo, preferencia, habito, time_favorito, comida_favorita\n"
                    "NÃO extraia perguntas, opiniões gerais ou contexto de conversa.\n\n"
                    f"Mensagem do usuário: {user_msg}\n\n"
                    "Retorne APENAS o JSON, sem texto antes ou depois."
                )
                raw = self._chat_with_models(
                    [
                        {
                            "role": "system",
                            "content": "Você é um extrator de fatos. Retorne apenas JSON compacto ou {}.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    purpose="extract",
                )
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if not match:
                    return
                import json

                data = json.loads(match.group())
                skip_keys = {"nome", "cidade", "idade", "profissao", "profissão"}
                for key, value in data.items():
                    if not key or not value:
                        continue
                    k = str(key).strip().lower()
                    v = str(value).strip()
                    if k in skip_keys or len(v) < 2 or len(v) > 200:
                        continue
                    self.save_learned_fact(k, v)
            except Exception:
                pass

        threading.Thread(target=_learn, daemon=True).start()

    # ------------------------------------------------------------------
    # Knowledge Base: armazena e recupera conhecimento estruturado
    # ------------------------------------------------------------------

    def save_kb_entry(self, topic: str, content: str, category: str, tags: str = "") -> None:
        """Salva uma entrada no knowledge base."""
        try:
            now = datetime.now().isoformat()
            self.conn.execute(
                "INSERT INTO knowledge_base (topic, content, category, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (topic, content, category, tags, now, now),
            )
            self.conn.commit()
        except Exception as e:
            print(f"Erro ao salvar KB: {e}")

    def _cntk_tokenize(self, text: str) -> list[str]:
        """Tokenização leve para ranking CNTK (Contexto + N-gramas + Tags + Keywords)."""
        normalized = self.normalize_text(text)
        tokens = re.findall(r"[a-z0-9]{2,}", normalized)
        stop = {
            "de",
            "da",
            "do",
            "das",
            "dos",
            "e",
            "o",
            "a",
            "os",
            "as",
            "um",
            "uma",
            "para",
            "com",
            "sem",
            "que",
            "na",
            "no",
            "nas",
            "nos",
            "em",
            "por",
            "sobre",
            "como",
            "mais",
        }
        return [t for t in tokens if t not in stop]

    def _cntk_compose_tags(self, topic: str, content: str, category: str, max_tags: int = 12) -> str:
        tokens = self._cntk_tokenize(f"{topic} {category} {content}")
        uniq: list[str] = []
        for tok in tokens:
            if tok not in uniq:
                uniq.append(tok)
            if len(uniq) >= max_tags:
                break
        return ", ".join(uniq)

    def _cntk_category_boosters(self, category: str) -> list[str]:
        cat = self.normalize_text(category)
        boosters: dict[str, list[str]] = {
            "tecnologia": ["software", "dados", "automacao", "inovacao", "algoritmo"],
            "saude": ["prevencao", "habitos", "bem-estar", "sono", "equilibrio"],
            "educacao": ["estudo", "aprendizagem", "pratica", "didatica", "conhecimento"],
            "historia": ["contexto", "periodo", "evento", "transformacao", "memoria"],
            "economia": ["mercado", "juros", "inflacao", "orcamento", "consumo"],
            "ciencia": ["evidencia", "metodo", "pesquisa", "analise", "descoberta"],
            "negocios": ["cliente", "valor", "vendas", "estrategia", "resultado"],
            "financas": ["reserva", "investimento", "risco", "gastos", "planejamento"],
            "habilidades": ["comunicacao", "foco", "lideranca", "colaboracao", "disciplina"],
            "produtividade": ["prioridade", "rotina", "execucao", "consistencia", "metas"],
            "esportes": ["treino", "desempenho", "equipe", "resistencia", "saude"],
            "cultura": ["identidade", "expressao", "arte", "tradicao", "diversidade"],
            "geografia": ["territorio", "regiao", "clima", "bioma", "espaco"],
        }
        return boosters.get(cat, ["contexto", "conceito", "pratica"])

    def _cntk_compose_tags_aggressive(
        self, topic: str, content: str, category: str, max_tags: int = 24
    ) -> str:
        base_tokens = self._cntk_tokenize(f"{topic} {category} {content}")
        topic_tokens = self._cntk_tokenize(topic)
        topic_bigrams = [
            f"{topic_tokens[i]} {topic_tokens[i + 1]}"
            for i in range(len(topic_tokens) - 1)
        ]
        combined = base_tokens + topic_bigrams + self._cntk_category_boosters(category)

        uniq: list[str] = []
        for tok in combined:
            if tok and tok not in uniq:
                uniq.append(tok)
            if len(uniq) >= max_tags:
                break
        return ", ".join(uniq)

    def optimize_kb_with_cntk(self, aggressive: bool = False) -> dict[str, int]:
        """Aprimora o KB com sistema CNTK, recalculando tags para melhorar recuperação."""
        try:
            rows = self.conn.execute(
                "SELECT id, topic, content, category, COALESCE(tags, '') FROM knowledge_base"
            ).fetchall()
            updated = 0
            for row_id, topic, content, category, tags in rows:
                fresh_tags = (
                    self._cntk_compose_tags_aggressive(topic, content, category)
                    if aggressive
                    else self._cntk_compose_tags(topic, content, category)
                )
                if fresh_tags and fresh_tags != (tags or "").strip():
                    self.conn.execute(
                        "UPDATE knowledge_base SET tags = ?, updated_at = ? WHERE id = ?",
                        (fresh_tags, datetime.now().isoformat(), row_id),
                    )
                    updated += 1
            self.conn.commit()
            return {"updated": updated, "total": len(rows)}
        except Exception:
            return {"updated": 0, "total": 0}

    def query_knowledge_base(self, query: str, limit: int = 3) -> list[tuple[int, str, str, str]]:
        """Busca no KB usando ranking CNTK (Contexto + N-gramas + Tags + Keywords)."""
        try:
            q_norm = self.normalize_text(query)
            q_tokens = self._cntk_tokenize(query)
            if not q_tokens:
                return []

            q_bigrams = {
                f"{q_tokens[i]} {q_tokens[i + 1]}" for i in range(len(q_tokens) - 1)
            }

            rows = self.conn.execute(
                "SELECT id, topic, content, category, COALESCE(tags, '') FROM knowledge_base ORDER BY updated_at DESC LIMIT 200"
            ).fetchall()

            scored: list[tuple[float, tuple[int, str, str, str]]] = []
            for row_id, topic, content, category, tags in rows:
                topic_n = self.normalize_text(topic)
                category_n = self.normalize_text(category)
                content_n = self.normalize_text(content)
                tags_n = self.normalize_text(tags)

                score = 0.0

                if q_norm in topic_n:
                    score += 6.0

                for tok in q_tokens:
                    if tok in topic_n:
                        score += 3.0
                    if tok in tags_n:
                        score += 2.0
                    if tok in category_n:
                        score += 1.5
                    if tok in content_n:
                        score += 1.0

                if q_bigrams:
                    row_tokens = self._cntk_tokenize(f"{topic} {tags} {content}")
                    row_bigrams = {
                        f"{row_tokens[i]} {row_tokens[i + 1]}"
                        for i in range(len(row_tokens) - 1)
                    }
                    score += 2.0 * len(q_bigrams.intersection(row_bigrams))

                fuzzy = difflib.SequenceMatcher(None, q_norm, topic_n).ratio()
                score += fuzzy * 3.0

                if score > 0.5:
                    scored.append((score, (row_id, topic, content, category)))

            scored.sort(key=lambda item: item[0], reverse=True)
            return [row for _, row in scored[:limit]]
        except Exception:
            return []

    def get_kb_stats(self) -> dict:
        """Retorna estatísticas do KB."""
        try:
            total = self.conn.execute("SELECT COUNT(*) FROM knowledge_base").fetchone()[0]
            categories = self.conn.execute(
                "SELECT category, COUNT(*) FROM knowledge_base GROUP BY category"
            ).fetchall()
            return {"total": total, "by_category": dict(categories)}
        except Exception:
            return {"total": 0, "by_category": {}}

    def seed_knowledge_base_auto(self) -> None:
        """Gera conhecimento inicial no KB com fallback local quando Ollama estiver offline."""
        topics = [
            (
                "História do Brasil",
                "história",
                "brasil, história, colonial, república, império",
                "A história do Brasil passa por período indígena, colonização portuguesa, independência em 1822, império, república e transformações sociais e econômicas que moldaram o país atual.",
            ),
            (
                "Geografia do Brasil",
                "geografia",
                "brasil, regiões, norte, nordeste, sudeste, sul, centro-oeste",
                "O Brasil tem cinco regiões com climas e economias diferentes, grande biodiversidade, vasto litoral e biomas como Amazônia, Cerrado, Caatinga, Mata Atlântica, Pampa e Pantanal.",
            ),
            (
                "Economia Brasileira",
                "economia",
                "brasil, pib, inflação, câmbio, mercado, finanças",
                "A economia brasileira combina agro, indústria e serviços, com influência de inflação, juros, câmbio e mercado internacional em emprego, consumo, investimento e renda da população.",
            ),
            (
                "Tecnologia e IA",
                "tecnologia",
                "ia, machine learning, python, programação, software",
                "Tecnologia e IA aceleram automação e produtividade; com dados de qualidade, bons modelos e ética, aplicações em saúde, educação, finanças e atendimento ganham escala e eficiência.",
            ),
            (
                "Saúde e Bem-estar",
                "saúde",
                "nutrição, exercício, mental, doença, prevenção",
                "Saúde e bem-estar dependem de sono regular, alimentação equilibrada, atividade física, hidratação e atenção à saúde mental, com prevenção e acompanhamento médico quando necessário.",
            ),
            (
                "Culinária Brasileira",
                "cultura",
                "comida, receita, ingrediente, prato, tradicional",
                "A culinária brasileira mistura influências indígenas, africanas e europeias, com pratos como feijoada, moqueca, acarajé e pão de queijo, variando bastante entre as regiões.",
            ),
            (
                "Esportes no Brasil",
                "esportes",
                "futebol, vôlei, natação, olimpíada, seleção",
                "Esportes no Brasil têm forte tradição no futebol e também destaque em vôlei, judô, surfe e atletismo, com impacto em saúde, lazer, educação e identidade cultural.",
            ),
            (
                "Ciência e Natureza",
                "ciência",
                "física, química, biologia, universo, planeta",
                "Ciência e natureza se conectam no estudo da matéria, da vida e do universo, ajudando a explicar fenômenos, desenvolver tecnologia e orientar decisões ambientais sustentáveis.",
            ),
            (
                "Arte e Cultura",
                "cultura",
                "arte, música, cinema, literatura, folclore",
                "Arte e cultura expressam identidade e memória coletiva por meio de música, literatura, cinema, dança e artes visuais, fortalecendo diversidade e pensamento crítico.",
            ),
            (
                "Educação no Brasil",
                "educação",
                "escola, universidade, ensino, aprendizado, formação",
                "Educação no Brasil envolve desafios de acesso, permanência e qualidade, e avança com formação docente, tecnologia educacional e políticas de inclusão escolar.",
            ),
            (
                "Produtividade Pessoal",
                "produtividade",
                "foco, rotina, planejamento, tempo, prioridades",
                "Produtividade pessoal melhora com metas claras, priorização diária, blocos de foco, pausas curtas e revisão semanal para ajustar rotina e manter consistência.",
            ),
            (
                "Finanças Pessoais",
                "finanças",
                "orçamento, reserva, dívida, investimento, gastos",
                "Finanças pessoais ficam mais estáveis com orçamento simples, controle de gastos, quitação de dívidas caras, reserva de emergência e investimentos alinhados ao perfil de risco.",
            ),
            (
                "Segurança Digital",
                "tecnologia",
                "senhas, phishing, backup, autenticação, privacidade",
                "Segurança digital exige senhas fortes, autenticação em dois fatores, atualização de sistemas, backup regular e cuidado com links suspeitos para reduzir golpes e vazamentos.",
            ),
            (
                "Comunicação Eficaz",
                "habilidades",
                "escuta, clareza, feedback, negociação, empatia",
                "Comunicação eficaz combina escuta ativa, clareza de mensagem, empatia e feedback objetivo, reduzindo ruídos e aumentando colaboração em casa e no trabalho.",
            ),
            (
                "Aprendizado Contínuo",
                "educação",
                "estudo, prática, revisão, memória, hábito",
                "Aprendizado contínuo funciona melhor com sessões curtas e frequentes, prática ativa, revisão espaçada e aplicação real do conteúdo para consolidar memória e habilidade.",
            ),
            (
                "Empreendedorismo",
                "negócios",
                "negocio, cliente, proposta de valor, vendas, mercado",
                "Empreendedorismo começa pela dor do cliente, validação rápida de solução e melhoria contínua da proposta de valor, com atenção a caixa, vendas e retenção.",
            ),
            (
                "Marketing Digital",
                "negócios",
                "conteudo, audiencia, funil, anuncio, conversao",
                "Marketing digital combina conteúdo útil, posicionamento claro e análise de métricas para atrair audiência, gerar confiança e converter interesse em resultado.",
            ),
            (
                "Meio Ambiente e Sustentabilidade",
                "ciência",
                "clima, reciclagem, energia, biodiversidade, consumo",
                "Sustentabilidade envolve uso responsável de recursos, eficiência energética, redução de resíduos e proteção da biodiversidade para equilibrar desenvolvimento e qualidade de vida.",
            ),
            (
                "Saúde Mental no Dia a Dia",
                "saúde",
                "estresse, ansiedade, descanso, apoio, autocuidado",
                "Saúde mental no dia a dia melhora com rotina de descanso, limites saudáveis, autocuidado, conexão social e procura de ajuda profissional quando necessário.",
            ),
            (
                "Liderança e Trabalho em Equipe",
                "habilidades",
                "lideranca, equipe, delegacao, alinhamento, resultado",
                "Liderança eficaz dá direção clara, delega com contexto, acompanha indicadores e cria ambiente de confiança para que a equipe entregue resultados sustentáveis.",
            ),
        ]

        llm_available = self._any_llm_available()

        for topic, category, tags, fallback_content in topics:
            # Verifica se já existe
            existing = self.conn.execute(
                "SELECT COUNT(*) FROM knowledge_base WHERE topic = ?", (topic,)
            ).fetchone()[0]
            if existing > 0:
                continue
            
            try:
                content = fallback_content
                # Gera conhecimento via LLM (quando disponível)
                if llm_available:
                    prompt = f"""Forneça 3-4 fatos principais e interessantes sobre "{topic}" em português do Brasil.
Seja conciso, informativo e correto. Não use bullet points, escreva em parágrafo contínuo.
Máximo 300 caracteres."""

                    llm_content = self._chat_with_models(
                        [
                            {"role": "system", "content": "Você é um especialista em fornecer informações corretas e concisas."},
                            {"role": "user", "content": prompt},
                        ],
                        purpose="seed",
                    )
                    if llm_content and len(llm_content.strip()) >= 40:
                        content = llm_content.strip()
                
                # Salva no KB
                self.save_kb_entry(topic, content, category, tags)
                print(f"OK - KB: {topic}")
            except Exception as e:
                print(f"ERRO ao gerar KB para {topic}: {e}")
                self.save_kb_entry(topic, fallback_content, category, tags)
            
            if llm_available:
                time.sleep(0.5)  # Rate limit

    def learn_topic_interactive(self, topic: str) -> str:
        """Permite ao usuário aprender sobre um novo tópico e salvá-lo."""
        # Verifica se já existe
        existing = self.conn.execute(
            "SELECT content FROM knowledge_base WHERE topic = ?", (topic,)
        ).fetchone()
        if existing:
            return f"Já tenho conhecimento sobre '{topic}':\n{existing[0]}"
        
        try:
            prompt = f"""Explique de forma clara e educativa sobre "{topic}".
Use linguagem simples, cite exemplos práticos.
Máximo 400 caracteres, sem bullet points."""
            
            content = self._chat_with_models(
                [
                    {"role": "system", "content": "Você é um educador que explica conceitos de forma clara e acessível."},
                    {"role": "user", "content": prompt},
                ],
                purpose="learn",
            )
            
            # Salva
            self.save_kb_entry(topic, content, "geral", topic.lower())
            return f"Aprendi sobre '{topic}'! 🎓\n\n{content}"
        except Exception as e:
            return f"Erro ao aprender sobre {topic}: {e}"

    def _inject_kb_context(self, query: str) -> str:
        """Retorna contexto relevante do KB para injetar no prompt."""
        results = self.query_knowledge_base(query, limit=2)
        if not results:
            return ""
        
        lines = ["📚 Contexto do meu Knowledge Base:"]
        for _, topic, content, category in results:
            lines.append(f"- [{category}] {topic}:\n  {content[:150]}...")
        
        return "\n".join(lines)

    def _default_aliases(self) -> dict[str, str]:
        return {
            "youtube": "https://youtube.com",
            "google": "https://google.com",
            "whatsapp": "https://web.whatsapp.com",
            "discord": "https://discord.com/app",
            "gmail": "https://mail.google.com",
            "insta": "https://instagram.com",
            "instagram": "https://instagram.com",
            "face": "https://facebook.com",
            "facebook": "https://facebook.com",
            "chatgpt": "https://chatgpt.com",
            "github": "https://github.com",
            "x": "https://x.com",
            "twitter": "https://x.com",
            "linkedin": "https://linkedin.com",
            "netflix": "https://netflix.com",
        }

    def save_alias(self, name: str, target: str) -> str:
        alias_name = name.strip().lower()
        alias_target = target.strip()
        if not alias_name:
            return "Nome do alias inválido."
        if not alias_target:
            return "Alvo do alias inválido."
        self.conn.execute(
            """
            INSERT INTO aliases (name, target, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                target = excluded.target,
                created_at = excluded.created_at
            """,
            (
                alias_name,
                alias_target,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()
        return f"Alias '{alias_name}' salvo para: {alias_target}"

    def fix_alias(self, name: str, target: str) -> str:
        alias_name = self.normalize_text(name)
        if not alias_name:
            return "Use: corrigir site <nome> para <url>"
        return self.save_alias(alias_name, target)

    def delete_alias(self, name: str) -> str:
        alias_name = name.strip().lower()
        if not alias_name:
            return "Use: /alias del <nome>"
        cur = self.conn.execute("DELETE FROM aliases WHERE name = ?", (alias_name,))
        self.conn.commit()
        if cur.rowcount:
            return f"Alias '{alias_name}' removido."
        return f"Alias '{alias_name}' não encontrado."

    def list_aliases(self) -> list[tuple[str, str, str]]:
        cur = self.conn.execute("SELECT name, target, created_at FROM aliases ORDER BY name ASC")
        return cur.fetchall()

    def get_alias_target(self, name: str) -> str | None:
        alias_name = name.strip().lower()
        defaults = self._default_aliases()
        if alias_name in defaults:
            return defaults[alias_name]
        cur = self.conn.execute("SELECT target FROM aliases WHERE name = ?", (alias_name,))
        row = cur.fetchone()
        return row[0] if row else None

    def save_note(self, content: str) -> None:
        self.conn.execute(
            "INSERT INTO notes (content, created_at) VALUES (?, ?)",
            (content.strip(), datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def get_notes(self) -> list[tuple[int, str, str]]:
        cur = self.conn.execute(
            "SELECT id, content, created_at FROM notes ORDER BY id DESC LIMIT 30"
        )
        return cur.fetchall()

    def save_personal_event(self, event_date: str, title: str) -> str:
        try:
            parsed = datetime.strptime(event_date.strip(), "%Y-%m-%d")
        except ValueError:
            return "Use a data no formato YYYY-MM-DD."

        name = title.strip()
        if not name:
            return "Informe o título do evento."

        self.conn.execute(
            "INSERT INTO personal_events (event_date, title, created_at) VALUES (?, ?, ?)",
            (
                parsed.strftime("%Y-%m-%d"),
                name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()
        return f"Evento salvo para {parsed.strftime('%d/%m/%Y')}: {name}"

    def _weekday_from_text(self, weekday_text: str) -> int | None:
        normalized = self.normalize_text(weekday_text)
        mapping = {
            "segunda": 0,
            "segunda-feira": 0,
            "terca": 1,
            "terca-feira": 1,
            "terça": 1,
            "terça-feira": 1,
            "quarta": 2,
            "quarta-feira": 2,
            "quinta": 3,
            "quinta-feira": 3,
            "sexta": 4,
            "sexta-feira": 4,
            "sabado": 5,
            "sábado": 5,
            "domingo": 6,
            "hoje": datetime.now().weekday(),
        }
        return mapping.get(normalized)

    def _weekday_name(self, weekday: int) -> str:
        names = {
            0: "segunda-feira",
            1: "terça-feira",
            2: "quarta-feira",
            3: "quinta-feira",
            4: "sexta-feira",
            5: "sábado",
            6: "domingo",
        }
        return names.get(weekday, "dia inválido")

    def save_weekly_routine(self, weekday_text: str, title: str) -> str:
        weekday = self._weekday_from_text(weekday_text)
        if weekday is None:
            return "Dia inválido. Use: segunda, terça, quarta, quinta, sexta, sábado ou domingo."

        task = title.strip()
        if not task:
            return "Informe a tarefa da rotina."

        self.conn.execute(
            "INSERT INTO weekly_routines (weekday, title, created_at) VALUES (?, ?, ?)",
            (
                weekday,
                task,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()
        return f"Rotina salva em {self._weekday_name(weekday)}: {task}"

    def list_weekly_routines(self, weekday_text: str | None = None) -> list[tuple[int, int, str]]:
        if weekday_text:
            weekday = self._weekday_from_text(weekday_text)
            if weekday is None:
                return []
            cur = self.conn.execute(
                "SELECT id, weekday, title FROM weekly_routines WHERE weekday = ? ORDER BY id ASC",
                (weekday,),
            )
            return cur.fetchall()

        cur = self.conn.execute(
            "SELECT id, weekday, title FROM weekly_routines ORDER BY weekday ASC, id ASC"
        )
        return cur.fetchall()

    def delete_weekly_routine(self, routine_id: str) -> str:
        if not routine_id.strip().isdigit():
            return "Use: /week del <id>"
        cur = self.conn.execute(
            "DELETE FROM weekly_routines WHERE id = ?",
            (int(routine_id.strip()),),
        )
        self.conn.commit()
        if cur.rowcount:
            return f"Rotina {routine_id.strip()} removida."
        return f"Rotina {routine_id.strip()} não encontrada."

    def format_weekly_routine_for_day(self, weekday_text: str) -> str:
        weekday = self._weekday_from_text(weekday_text)
        if weekday is None:
            return "Dia inválido."
        items = self.list_weekly_routines(weekday_text)
        if not items:
            return f"Sem rotina para {self._weekday_name(weekday)}."
        lines = [f"Rotina de {self._weekday_name(weekday)}:"]
        for routine_id, _w, title in items:
            lines.append(f"- [{routine_id}] {title}")
        return "\n".join(lines)

    def list_personal_events(self, event_date: str | None = None) -> list[tuple[int, str, str]]:
        if event_date:
            cur = self.conn.execute(
                "SELECT id, event_date, title FROM personal_events WHERE event_date = ? ORDER BY title ASC",
                (event_date,),
            )
        else:
            cur = self.conn.execute(
                "SELECT id, event_date, title FROM personal_events ORDER BY event_date ASC, title ASC LIMIT 50"
            )
        return cur.fetchall()

    def delete_personal_event(self, event_id: str) -> str:
        if not event_id.strip().isdigit():
            return "Use: /event del <id>"
        cur = self.conn.execute(
            "DELETE FROM personal_events WHERE id = ?",
            (int(event_id.strip()),),
        )
        self.conn.commit()
        if cur.rowcount:
            return f"Evento {event_id.strip()} removido."
        return f"Evento {event_id.strip()} não encontrado."

    def format_events_for_date(self, event_date: str) -> str:
        events = self.list_personal_events(event_date)
        if not events:
            return "Sem eventos pessoais para hoje."
        lines = ["Seus eventos importantes:"]
        for event_id, _date, title in events:
            lines.append(f"- [{event_id}] {title}")
        return "\n".join(lines)

    def clear_history(self) -> None:
        self.history = []

    def log_routine_event(self, action_type: str, target: str) -> None:
        if not self.routine_learning_enabled:
            return
        value = target.strip()
        if not value:
            return
        self.conn.execute(
            "INSERT INTO routine_events (action_type, target, executed_at) VALUES (?, ?, ?)",
            (
                action_type.strip().lower(),
                value,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        self.conn.commit()

    def get_routine_overview(self, limit: int = 12) -> list[tuple[str, str, int]]:
        cur = self.conn.execute(
            """
            SELECT action_type, target, COUNT(*) as qtd
            FROM routine_events
            GROUP BY action_type, target
            ORDER BY qtd DESC, MAX(executed_at) DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()

    def get_current_slot_patterns(self, min_count: int = 2) -> list[tuple[str, str, int]]:
        now = datetime.now()
        weekday = now.strftime("%w")
        hour = f"{now.hour:02d}"
        cur = self.conn.execute(
            """
            SELECT action_type, target, COUNT(*) as qtd
            FROM routine_events
            WHERE strftime('%w', executed_at) = ?
              AND strftime('%H', executed_at) = ?
            GROUP BY action_type, target
            HAVING qtd >= ?
            ORDER BY qtd DESC, MAX(executed_at) DESC
            LIMIT 8
            """,
            (weekday, hour, min_count),
        )
        return cur.fetchall()

    def _parse_shortcut_actions(self, actions: str) -> set[str]:
        steps = [s.strip() for s in actions.split("||") if s.strip()]
        parsed: set[str] = set()
        for step in steps:
            if ":" not in step:
                continue
            action_type, target = step.split(":", 1)
            parsed.add(f"{action_type.strip().lower()}:{target.strip()}")
        return parsed

    def get_proactive_shortcut_suggestion(self) -> tuple[str, int] | None:
        patterns = self.get_current_slot_patterns(min_count=self.proactive_min_count)
        if not patterns:
            return None

        weighted: dict[str, int] = {f"{a}:{t}": qtd for a, t, qtd in patterns}
        pattern_keys = set(weighted.keys())

        best_name: str | None = None
        best_score = 0
        for name, actions, _created_at in self.list_shortcuts():
            keys = self._parse_shortcut_actions(actions)
            score = sum(weighted.get(k, 0) for k in keys.intersection(pattern_keys))
            if score > best_score:
                best_name = name
                best_score = score

        if not best_name:
            return None
        return best_name, best_score

    def should_prompt_proactive_now(self) -> bool:
        if not self.proactive_enabled:
            return False
        slot = datetime.now().strftime("%Y-%m-%d-%H")
        if self.last_proactive_slot == slot:
            return False
        return True

    def mark_proactive_prompted(self) -> None:
        self.last_proactive_slot = datetime.now().strftime("%Y-%m-%d-%H")

    def routine_suggestions_text(self) -> str:
        patterns = self.get_current_slot_patterns()
        if not patterns:
            return (
                "Ainda não aprendi padrões suficientes para este horário. "
                "Continue usando /open, /ps e /shortcut run para eu aprender."
            )
        lines = ["Padrões aprendidos para este dia/horário:"]
        for action_type, target, qtd in patterns:
            lines.append(f"- {action_type}:{target} (repetiu {qtd}x)")
        lines.append("Dica: use /routine auto <nome> para salvar isso como atalho.")
        return "\n".join(lines)

    def create_shortcut_from_routine(self, name: str) -> str:
        patterns = self.get_current_slot_patterns()
        if not patterns:
            return "Sem padrões suficientes neste horário para criar atalho."
        actions = " || ".join([f"{a}:{t}" for a, t, _ in patterns])
        return self.save_shortcut(name, actions)

    def save_shortcut(self, name: str, actions: str) -> str:
        shortcut_name = name.strip().lower()
        shortcut_actions = actions.strip()

        if not shortcut_name:
            return "Nome do atalho inválido."
        if not shortcut_actions:
            return "Ações do atalho inválidas."

        self.conn.execute(
            """
            INSERT INTO shortcuts (name, actions, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                actions = excluded.actions,
                created_at = excluded.created_at
            """,
            (
                shortcut_name,
                shortcut_actions,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()
        return f"Atalho '{shortcut_name}' salvo."

    def list_shortcuts(self) -> list[tuple[str, str, str]]:
        cur = self.conn.execute(
            "SELECT name, actions, created_at FROM shortcuts ORDER BY name ASC"
        )
        return cur.fetchall()

    def delete_shortcut(self, name: str) -> str:
        shortcut_name = name.strip().lower()
        if not shortcut_name:
            return "Use: /shortcut del <nome>"
        cur = self.conn.execute("DELETE FROM shortcuts WHERE name = ?", (shortcut_name,))
        self.conn.commit()
        if cur.rowcount:
            return f"Atalho '{shortcut_name}' removido."
        return f"Atalho '{shortcut_name}' não encontrado."

    def get_shortcut(self, name: str) -> tuple[str, str] | None:
        shortcut_name = name.strip().lower()
        cur = self.conn.execute(
            "SELECT name, actions FROM shortcuts WHERE name = ?", (shortcut_name,)
        )
        return cur.fetchone()

    def build_memory_context(self) -> str:
        profile_block = self.format_user_profile_context()

        notes = self.get_notes()
        notes_block = ""
        if notes:
            lines = [f"- [{n[0]}] {n[1]} ({n[2]})" for n in notes]
            notes_block = "Anotações do usuário:\n" + "\n".join(lines)

        routine = self.get_routine_overview(limit=5)
        routine_block = ""
        if routine:
            routine_lines = [f"- {a}:{t} ({q}x)" for a, t, q in routine]
            routine_block = "Rotina observada:\n" + "\n".join(routine_lines)

        blocks = [b for b in [profile_block, notes_block, routine_block] if b]
        return "\n\n".join(blocks) if blocks else "Sem contexto pessoal ainda."

    def ask(self, user_message: str) -> str:
        # Extrai fatos rápidos por regex antes de responder
        self._extract_facts_quick(user_message)

        self.history.append({"role": "user", "content": user_message})

        # Injeta contexto do Knowledge Base se relevante
        kb_context = self._inject_kb_context(user_message)

        context = [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": self.build_memory_context()},
        ]
        
        # Adiciona KB context se disponível
        if kb_context:
            context.append({"role": "system", "content": kb_context})
        
        context.extend(self.history[-12:])

        answer = self._chat_with_models(context, purpose="chat")
        self.history.append({"role": "assistant", "content": answer})

        # Aprendizado em background (LLM extrai preferências da conversa)
        self._background_learn(user_message, answer)

        return answer

    def search_web(self, query: str) -> str:
        question = query.strip()
        if not question:
            return "Use: /search <pergunta>"

        requests = importlib.import_module("requests")
        snippets: list[str] = []
        sources: list[str] = []

        try:
            g = requests.get(
                "https://www.google.com/search",
                params={"q": question, "hl": "pt-BR", "gl": "br", "num": 10},
                timeout=20,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "pt-BR,pt;q=0.9",
                },
            )
            g.raise_for_status()
            html = g.text

            # Links de resultado
            links = re.findall(r'href="/url\?q=(https?://[^&\"]+)"', html)
            for link in links[:10]:
                clean = self._extract_search_result_url(link)
                if clean.startswith("http") and self._is_good_official_candidate(clean, question):
                    sources.append(clean)

            # Snippets VwiC3b (resultado padrão)
            for m in re.finditer(
                r'<div[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</div>',
                html, flags=re.IGNORECASE | re.DOTALL
            ):
                plain = re.sub(r"<[^>]+>", " ", m.group(1))
                plain = re.sub(r"\s+", " ", plain).strip()
                if len(plain) > 30:
                    snippets.append(plain)

            # Featured snippet / knowledge panel
            for pat in [
                r'<div[^>]*data-attrid="[^"]*description[^"]*"[^>]*>(.*?)</div>',
                r'<span[^>]*class="[^"]*ILfuVd[^"]*"[^>]*>(.*?)</span>',
                r'<div[^>]*class="[^"]*kno-rdesc[^"]*"[^>]*>(.*?)</div>',
            ]:
                for m in re.finditer(pat, html, re.IGNORECASE | re.DOTALL):
                    plain = re.sub(r"<[^>]+>", " ", m.group(1))
                    plain = re.sub(r"\s+", " ", plain).strip()
                    if len(plain) > 20:
                        snippets.insert(0, plain)  # priority
        except Exception:
            pass

        try:
            wiki_search = requests.get(
                "https://pt.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": question,
                    "limit": 1,
                    "namespace": 0,
                    "format": "json",
                },
                timeout=20,
            )
            wiki_search.raise_for_status()
            wiki_data = wiki_search.json()
            titles = wiki_data[1] if len(wiki_data) > 1 else []
            if titles:
                title = titles[0]
                summary = requests.get(
                    f"https://pt.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}",
                    timeout=20,
                )
                summary.raise_for_status()
                summary_data = summary.json()
                extract = (summary_data.get("extract") or "").strip()
                if extract:
                    snippets.append(extract)
                content_urls = summary_data.get("content_urls", {})
                desktop = content_urls.get("desktop", {}).get("page")
                if desktop:
                    sources.append(desktop)
        except Exception:
            pass

        unique_snippets: list[str] = []
        seen: set[str] = set()
        for item in snippets:
            if item and item not in seen:
                seen.add(item)
                unique_snippets.append(item)

        if not unique_snippets:
            return "Não encontrei resultados suficientes na web para essa pergunta."

        research_context = "\n\n".join(unique_snippets[:5])
        source_text = "\n".join(f"- {url}" for url in list(dict.fromkeys(sources))[:3])

        hoje = datetime.now().strftime("%d/%m/%Y %H:%M")
        try:
            answer = self._chat_with_models(
                [
                    {
                        "role": "system",
                        "content": (
                            f"Você é um assistente pessoal. Hoje é {hoje}.\n"
                            "Responda SOMENTE com base nas informações da web fornecidas abaixo. "
                            "NÃO use seu conhecimento de treinamento para dados que mudam (preços, clima, placares, notícias). "
                            "Se as informações forem insuficientes, diga exatamente o que encontrou e peça para o usuário verificar a fonte. "
                            "Seja objetivo, claro e responda em português do Brasil."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Pergunta: {question}\n\n"
                            f"Informações encontradas na web (coletadas agora):\n{research_context}\n\n"
                            "Responda a pergunta usando apenas essas informações."
                        ),
                    },
                ],
                purpose="web",
            )
        except Exception:
            answer = unique_snippets[0]

        if source_text:
            return f"{answer}\n\n📌 Fontes:\n{source_text}"
        return answer

    def get_weather_summary(self) -> str:
        city = self.user_city or self.detect_city_by_ip()
        if not city:
            return "Previsão do tempo indisponível. Configure USER_CITY no .env."
        try:
            requests = importlib.import_module("requests")
            response = requests.get(
                f"https://wttr.in/{urllib.parse.quote(city)}",
                params={"format": "%l:+%C,+%t,+sensação+%f"},
                timeout=20,
            )
            response.raise_for_status()
            response.encoding = "utf-8"
            text = response.text.strip()
            text = text.replace("+", " ")
            text = text.replace("Â°C", "°C")
            text = text.replace("sensaÃ§Ã£o", "sensação")
            text = re.sub(r"\s+", " ", text).strip()
            return f"Tempo agora: {text}"
        except Exception:
            return f"Previsão do tempo indisponível para {city}."

    def get_weather_full(self, city: str = "") -> str:
        """Rich weather using wttr.in JSON API — detailed current + today forecast."""
        target = city.strip() or self.user_city or self.detect_city_by_ip() or ""
        if not target:
            return "Não sei sua cidade. Diga 'moro em <cidade>' ou configure USER_CITY no .env."
        try:
            requests = importlib.import_module("requests")
            r = requests.get(
                f"https://wttr.in/{urllib.parse.quote(target)}",
                params={"format": "j1"},
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            r.raise_for_status()
            data = r.json()

            cur = data["current_condition"][0]
            temp     = cur.get("temp_C", "?") + "°C"
            feels    = cur.get("FeelsLikeC", "?") + "°C"
            humidity = cur.get("humidity", "?") + "%"
            wind     = cur.get("windspeedKmph", "?") + " km/h"
            desc_list = cur.get("lang_pt") or cur.get("weatherDesc") or [{}]
            desc     = (desc_list[0].get("value") or "").strip() or "?"

            today = data["weather"][0] if data.get("weather") else {}
            max_t = today.get("maxtempC", "?") + "°C"
            min_t = today.get("mintempC", "?") + "°C"

            hourly = today.get("hourly", [])
            rain_chance = 0
            for h in hourly:
                rc = int(h.get("chanceofrain", 0))
                if rc > rain_chance:
                    rain_chance = rc

            rain_text = (
                f"🌧️ Chance de chuva hoje: {rain_chance}%"
                if rain_chance > 20
                else "☀️ Sem previsão de chuva hoje"
            )

            lines = [
                f"🌡️ Previsão do tempo — {target.title()}",
                f"Agora: {desc}, {temp} (sensação {feels})",
                f"Máxima {max_t} / Mínima {min_t}",
                f"Umidade: {humidity} | Vento: {wind}",
                rain_text,
            ]
            return "\n".join(lines)
        except Exception as e:
            # Fallback to simple format
            return self.get_weather_summary()

    def detect_city_by_ip(self) -> str | None:
        if self._cached_ip_city:
            return self._cached_ip_city
        if not self.auto_city_by_ip:
            return None

        try:
            requests = importlib.import_module("requests")
            response = requests.get("http://ip-api.com/json/?fields=status,city", timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "success":
                city = (data.get("city") or "").strip()
                if city:
                    self._cached_ip_city = city
                    return city
        except Exception:
            return None
        return None

    def get_holiday_summary(self, target_date: datetime) -> str:
        if self.user_country != "BR":
            return "Consulta de feriado automática disponível apenas para BR no momento."

        try:
            requests = importlib.import_module("requests")
            response = requests.get(
                f"https://brasilapi.com.br/api/feriados/v1/{target_date.year}",
                timeout=20,
            )
            response.raise_for_status()
            holidays = response.json()
            iso_date = target_date.strftime("%Y-%m-%d")
            for holiday in holidays:
                if holiday.get("date") == iso_date:
                    return f"Hoje é feriado: {holiday.get('name', 'Feriado')}"
            return "Hoje não é feriado nacional."
        except Exception:
            return "Não consegui consultar feriados agora."

    # ------------------------------------------------------------------
    # Dedicated real-time data sources
    # ------------------------------------------------------------------

    def get_currency_rate(self, pair: str = "USD-BRL") -> str:
        """Returns current exchange rate using AwesomeAPI (Brazilian market)."""
        try:
            requests = importlib.import_module("requests")
            key = pair.replace("-", "")
            r = requests.get(
                f"https://economia.awesomeapi.com.br/json/last/{pair}",
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            info = data.get(key, {})
            bid   = info.get("bid", "?")
            ask   = info.get("ask", "?")
            pct   = info.get("pctChange", "?")
            name  = info.get("name", pair)
            high  = info.get("high", "?")
            low   = info.get("low", "?")
            arrow = "📈" if str(pct).startswith("-") is False and pct not in ("?", "0") else "📉"
            try:
                bid_f = f"R$ {float(bid):.4f}"
                ask_f = f"R$ {float(ask):.4f}"
                high_f = f"R$ {float(high):.4f}"
                low_f  = f"R$ {float(low):.4f}"
                pct_f  = f"{float(pct):+.2f}%"
            except Exception:
                bid_f, ask_f, high_f, low_f, pct_f = bid, ask, high, low, str(pct)
            lines = [
                f"{arrow} {name}",
                f"Compra: {bid_f} | Venda: {ask_f}",
                f"Máx: {high_f} | Mín: {low_f} | Variação: {pct_f}",
                f"Atualizado em tempo real (AwesomeAPI / B3)",
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"Não consegui obter a cotação de {pair} agora ({e})."

    def get_news_headlines(self, source: str = "g1") -> str:
        """Returns top Brazilian news headlines via RSS."""
        feeds = {
            "g1": "https://g1.globo.com/rss/g1/",
            "uol": "https://rss.uol.com.br/feed/noticias.xml",
            "agencia_brasil": "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml",
        }
        url = feeds.get(source, feeds["g1"])
        try:
            requests = importlib.import_module("requests")
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            xml = r.text
            titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", xml)
            if not titles:
                titles = re.findall(r"<title>(.*?)</title>", xml)
            # Skip the feed title (first item) and get 5 headlines
            headlines = [t.strip() for t in titles if t.strip()]
            headlines = [h for h in headlines if len(h) > 10][1:6]
            if not headlines:
                return "Não encontrei manchetes agora."
            hoje = datetime.now().strftime("%d/%m/%Y %H:%M")
            lines = [f"📰 Manchetes de hoje ({hoje}):"]
            for i, h in enumerate(headlines, 1):
                lines.append(f"{i}. {h}")
            lines.append(f"\nFonte: {url}")
            return "\n".join(lines)
        except Exception as e:
            return f"Não consegui buscar notícias agora ({e})."

    def daily_briefing(self) -> str:
        today = datetime.now()
        date_text = today.strftime("%d/%m/%Y")
        weekday_names = {
            0: "segunda-feira",
            1: "terça-feira",
            2: "quarta-feira",
            3: "quinta-feira",
            4: "sexta-feira",
            5: "sábado",
            6: "domingo",
        }
        weekday = weekday_names[today.weekday()]
        parts = [
            f"Bom dia. Hoje é {weekday}, {date_text}.",
            self.get_weather_full(),  # Rich weather instead of summary
            self.get_holiday_summary(today),
            self.format_events_for_date(today.strftime('%Y-%m-%d')),
            self.format_weekly_routine_for_day("hoje"),
        ]
        return "\n".join(parts)

    def answer_command(self, command: str, allow_confirmation: bool = True) -> str:
        local_result = self.handle_local_command(command)
        if local_result is not None:
            return local_result

        normalized = self.normalize_text(command)

        # Weather queries → rich weather handler
        weather_kws = [
            "previsao do tempo", "previsão do tempo", "tempo hoje", "clima hoje",
            "temperatura hoje", "temperatura agora", "vai chover", "chovendo",
            "tempo amanha", "tempo amanhã", "previsao amanha", "previsão amanhã",
            "como esta o tempo", "como está o tempo", "clima amanha", "clima amanhã",
        ]
        if any(kw in normalized for kw in weather_kws):
            city_match = re.search(
                r"(?:em|para|de|n[ao])\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s]{2,30}?)(?:\s+(?:hoje|amanhã|amanha|agora|pra|para|esta semana)|\.?$)",
                command, re.IGNORECASE,
            )
            city = city_match.group(1).strip() if city_match else ""
            return self.get_weather_full(city)

        # Currency / exchange rate queries → AwesomeAPI
        currency_map = {
            ("dolar", "usd", "dólar"): "USD-BRL",
            ("euro", "eur"): "EUR-BRL",
            ("libra", "gbp"): "GBP-BRL",
            ("bitcoin", "btc"): "BTC-BRL",
            ("ethereum", "eth"): "ETH-BRL",
            ("iene", "jpy", "yen"): "JPY-BRL",
            ("dolar australiano", "aud"): "AUD-BRL",
            ("dolar canadense", "cad"): "CAD-BRL",
        }
        currency_trigger_kws = [
            "cotacao", "cotação", "valor do", "valor da", "hoje",
            "preco do", "preço do", "quanto esta", "quanto está",
        ]
        has_currency_trigger = any(kw in normalized for kw in currency_trigger_kws)
        if has_currency_trigger:
            for keys, pair in currency_map.items():
                if any(k in normalized for k in keys):
                    return self.get_currency_rate(pair)

        # News queries → RSS headlines
        news_kws = [
            "noticias", "notícias", "manchetes", "ultimas noticias",
            "últimas notícias", "o que esta acontecendo", "o que está acontecendo",
            "novidades", "o que aconteceu hoje",
        ]
        if any(kw in normalized for kw in news_kws):
            return self.get_news_headlines()

        # Real-time / explicit web queries → web search first, then fallback to LLM
        if self.looks_like_search_question(command):
            web_answer = self.search_web(command)
            if "Não encontrei resultados suficientes" not in web_answer:
                return web_answer
            # fallback inteligente: usa memória + KB + LLM
            return self.ask(command)

        if allow_confirmation:
            suggestion = self.suggest_command_correction(command)
            if suggestion and self.confirm_suggestion(suggestion):
                local_result = self.handle_local_command(suggestion)
                if local_result is not None:
                    return local_result

        return self.ask(command)

    def _looks_like_local_app_target(self, value: str) -> bool:
        lowered = value.lower()
        if any(sep in value for sep in ["\\", "/", ":"]):
            return True
        if lowered.endswith((".exe", ".bat", ".cmd", ".msi", ".lnk")):
            return True
        return False

    def _extract_duckduckgo_result_url(self, raw_url: str) -> str:
        return self._extract_search_result_url(raw_url)

    def _extract_search_result_url(self, raw_url: str) -> str:
        try:
            parsed = urllib.parse.urlparse(raw_url)
            if parsed.netloc.endswith("startpage.com") and parsed.path.startswith("/sp/redirect"):
                query = urllib.parse.parse_qs(parsed.query)
                target = query.get("url", [""])[0]
                if target:
                    return urllib.parse.unquote(target)
            if parsed.netloc.endswith("google.com") and parsed.path == "/url":
                query = urllib.parse.parse_qs(parsed.query)
                target = query.get("q", [""])[0]
                if target:
                    return urllib.parse.unquote(target)
            if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
                query = urllib.parse.parse_qs(parsed.query)
                uddg = query.get("uddg", [""])[0]
                if uddg:
                    return urllib.parse.unquote(uddg)
        except Exception:
            return raw_url
        return raw_url

    def _is_search_or_aggregator_domain(self, host: str) -> bool:
        bad_domains = {
            "startpage.com",
            "google.com",
            "bing.com",
            "yahoo.com",
            "search.brave.com",
            "wikipedia.org",
            "facebook.com",
            "instagram.com",
            "youtube.com",
        }
        host = host.lower().replace("www.", "")
        return any(host == domain or host.endswith("." + domain) for domain in bad_domains)

    def _is_good_official_candidate(self, url: str, query: str) -> bool:
        try:
            parsed = urllib.parse.urlparse(url)
            host = parsed.netloc.lower().replace("www.", "")
            path = (parsed.path or "").lower()
        except Exception:
            return False

        if not host or self._is_search_or_aggregator_domain(host):
            return False

        token = re.sub(r"[^a-z0-9]", "", self.normalize_text(query))
        host_compact = re.sub(r"[^a-z0-9]", "", host)
        path_compact = re.sub(r"[^a-z0-9]", "", path)

        if token and (token in host_compact or token in path_compact):
            return True

        return bool(host.endswith(".com") or host.endswith(".com.br"))

    def _guess_official_url(self, query: str) -> str | None:
        requests = importlib.import_module("requests")
        q = query.strip()
        if not q:
            return None

        try:
            html = requests.get(
                "https://www.google.com/search",
                params={"q": f"site oficial {q}", "hl": "pt-BR", "gl": "br", "num": 10},
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            html.raise_for_status()
            matches = re.findall(r'href="/url\?q=(https?://[^&\"]+)"', html.text)
            cleaned = [self._extract_search_result_url(url) for url in matches]

            norm_query = self.normalize_text(q).replace(" ", "")
            def score(url: str) -> int:
                try:
                    host = urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
                except Exception:
                    return -1
                if not host or self._is_search_or_aggregator_domain(host):
                    return 0
                points = 1
                host_compact = re.sub(r"[^a-z0-9]", "", host)
                if norm_query and norm_query in host_compact:
                    points += 3
                if host.endswith(".com") or host.endswith(".com.br"):
                    points += 1
                return points

            ranked = sorted(cleaned, key=score, reverse=True)
            for candidate in ranked:
                if candidate.startswith("http") and self._is_good_official_candidate(candidate, q):
                    return candidate
        except Exception:
            return None

        return None

    def _candidate_chrome_paths(self) -> list[str]:
        candidates = []
        if self.chrome_path:
            candidates.append(self.chrome_path)

        local_app_data = os.getenv("LOCALAPPDATA", "")
        program_files = os.getenv("ProgramFiles", "")
        program_files_x86 = os.getenv("ProgramFiles(x86)", "")

        candidates.extend(
            [
                os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
            ]
        )
        return [path for path in candidates if path]

    def _open_url(self, url: str) -> bool:
        if self.force_chrome:
            for chrome_exe in self._candidate_chrome_paths():
                try:
                    if os.path.exists(chrome_exe):
                        subprocess.Popen([chrome_exe, url])
                        return True
                except Exception:
                    continue
        try:
            webbrowser.open(url)
            return True
        except Exception:
            return False

    def open_target(self, target: str) -> str:
        value = target.strip().strip('"')
        if not value:
            return "Informe algo para abrir."

        if value.startswith("http://") or value.startswith("https://"):
            if self._open_url(value):
                self.log_routine_event("open", value)
                browser_label = "no Chrome" if self.force_chrome else ""
                return f"Abrindo site {browser_label}: {value}".replace("  ", " ").strip()
            return f"Falha ao abrir site: {value}"

        if os.path.exists(value):
            os.startfile(value)
            self.log_routine_event("open", value)
            return f"Abrindo: {value}"

        if not self._looks_like_local_app_target(value):
            official_url = self._guess_official_url(value)
            if official_url:
                opened = self._open_url(official_url)
                if not opened:
                    return f"Falha ao abrir site encontrado: {official_url}"
                self.log_routine_event("open", official_url)
                learned_key = self.normalize_text(value)
                if learned_key:
                    self.save_alias(learned_key, official_url)
                    return (
                        f"Abrindo site oficial mais próximo: {official_url}\n"
                        f"Aprendi que '{learned_key}' -> {official_url}"
                    )
                return f"Abrindo site oficial mais próximo: {official_url}"

        try:
            subprocess.Popen(value, shell=True)
            self.log_routine_event("open", value)
            return f"Tentando abrir app/comando: {value}"
        except Exception as e:
            return f"Falha ao abrir '{value}': {e}"

    def run_powershell(self, command: str) -> str:
        cmd = command.strip()
        if not cmd:
            return "Use: /ps <comando>"
        self.log_routine_event("ps", cmd)
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
            output = output.strip() or "(sem saída)"
            return f"Exit code {result.returncode}\n{output}"
        except Exception as e:
            return f"Erro ao executar comando: {e}"

    def wake_on_lan(self, mac: str, broadcast_ip: str = "255.255.255.255", port: int = 9) -> str:
        raw_mac = mac.strip().lower().replace("-", "").replace(":", "")
        if len(raw_mac) != 12 or not re.fullmatch(r"[0-9a-f]{12}", raw_mac):
            return "MAC inválido. Use formato: AA:BB:CC:DD:EE:FF"

        try:
            mac_bytes = bytes.fromhex(raw_mac)
            magic_packet = b"\xff" * 6 + mac_bytes * 16

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(magic_packet, (broadcast_ip, int(port)))
            sock.close()
            return f"⚡ Pacote Wake-on-LAN enviado para {mac.upper()} via {broadcast_ip}:{port}."
        except Exception as e:
            return f"Erro ao enviar Wake-on-LAN: {e}"

    def _get_profile_value(self, key: str) -> str:
        try:
            row = self.conn.execute(
                "SELECT value FROM user_profile WHERE key = ?",
                (key.strip().lower(),),
            ).fetchone()
            return str(row[0]).strip() if row and row[0] is not None else ""
        except Exception:
            return ""

    def get_wol_status(self) -> str:
        mac = self._get_profile_value("wol_default_mac") or os.getenv("WOL_DEFAULT_MAC", "").strip()
        broadcast = self._get_profile_value("wol_broadcast") or os.getenv("WOL_BROADCAST", "255.255.255.255").strip() or "255.255.255.255"
        port = self._get_profile_value("wol_port") or os.getenv("WOL_PORT", "9").strip() or "9"
        return (
            "⚙️ Wake-on-LAN status:\n"
            f"- MAC padrão: {mac if mac else '(não configurado)'}\n"
            f"- Broadcast: {broadcast}\n"
            f"- Porta: {port}\n"
            "Use: /wol set AA:BB:CC:DD:EE:FF 192.168.1.255 9"
        )

    def set_wol_defaults(self, mac: str, broadcast_ip: str = "255.255.255.255", port: int = 9) -> str:
        raw_mac = mac.strip().lower().replace("-", "").replace(":", "")
        if len(raw_mac) != 12 or not re.fullmatch(r"[0-9a-f]{12}", raw_mac):
            return "MAC inválido. Use formato: AA:BB:CC:DD:EE:FF"

        pretty_mac = ":".join(raw_mac[i : i + 2] for i in range(0, 12, 2)).upper()
        self.save_user_fact("wol_default_mac", pretty_mac)
        self.save_user_fact("wol_broadcast", (broadcast_ip or "255.255.255.255").strip())
        self.save_user_fact("wol_port", str(int(port)))
        return f"✅ Wake-on-LAN configurado: {pretty_mac} via {broadcast_ip}:{int(port)}"

    def run_wol_command(self, payload: str) -> str:
        raw = payload.strip()
        default_mac = self._get_profile_value("wol_default_mac") or os.getenv("WOL_DEFAULT_MAC", "").strip()
        default_broadcast = (
            self._get_profile_value("wol_broadcast")
            or os.getenv("WOL_BROADCAST", "255.255.255.255").strip()
            or "255.255.255.255"
        )
        default_port = int(self._get_profile_value("wol_port") or os.getenv("WOL_PORT", "9") or "9")

        if self.normalize_text(raw) in {"status", "st"}:
            return self.get_wol_status()

        if self.normalize_text(raw).startswith("set "):
            set_payload = raw[4:].strip()
            set_parts = set_payload.split()
            if not set_parts:
                return "Use: /wol set <MAC> [broadcast_ip] [porta]"
            mac = set_parts[0]
            broadcast = set_parts[1] if len(set_parts) >= 2 else default_broadcast
            port = default_port
            if len(set_parts) >= 3 and set_parts[2].isdigit():
                port = int(set_parts[2])
            return self.set_wol_defaults(mac, broadcast, port)

        if not raw:
            if default_mac:
                return self.wake_on_lan(default_mac, default_broadcast, default_port)
            return "Use: /wol <MAC> [broadcast_ip] [porta] ou /wol set <MAC> ..."

        parts = raw.split()
        mac = parts[0]
        broadcast = parts[1] if len(parts) >= 2 else default_broadcast
        port = default_port
        if len(parts) >= 3 and parts[2].isdigit():
            port = int(parts[2])

        return self.wake_on_lan(mac, broadcast, port)

    def run_pc_command(self, payload: str) -> str:
        raw = payload.strip()
        if not raw:
            return (
                "Use: /pc shutdown [segundos] | restart [segundos] | lock | sleep | hibernate | logout | cancel | wake [MAC]"
            )

        parts = raw.split()
        action = self.normalize_text(parts[0])
        delay = 60
        if len(parts) > 1 and parts[1].isdigit():
            delay = max(0, min(3600, int(parts[1])))

        try:
            if action in {"shutdown", "desligar", "desliga"}:
                subprocess.Popen(["shutdown", "/s", "/t", str(delay)], shell=False)
                return f"🛑 Desligamento agendado para {delay}s. Use '/pc cancel' para cancelar."

            if action in {"restart", "reiniciar", "reinicia"}:
                subprocess.Popen(["shutdown", "/r", "/t", str(delay)], shell=False)
                return f"🔄 Reinicialização agendada para {delay}s. Use '/pc cancel' para cancelar."

            if action in {"cancel", "abort", "cancelar"}:
                result = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
                if result.returncode == 0:
                    return "✅ Ação de desligar/reiniciar cancelada."
                return "ℹ️ Não havia desligamento/reinicialização pendente."

            if action in {"wake", "ligar", "acordar"}:
                if len(parts) >= 2:
                    rest = " ".join(parts[1:])
                    return self.run_wol_command(rest)
                return self.run_wol_command("")

            if action in {"lock", "bloquear", "bloqueia"}:
                subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"], shell=False)
                return "🔒 PC bloqueado."

            if action in {"sleep", "suspender", "suspende"}:
                subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], shell=False)
                return "💤 Enviando PC para suspensão."

            if action in {"hibernate", "hibernar", "hiberna"}:
                subprocess.Popen(["shutdown", "/h"], shell=False)
                return "🛌 Enviando PC para hibernação."

            if action in {"logout", "sair", "logoff"}:
                subprocess.Popen(["shutdown", "/l"], shell=False)
                return "👋 Encerrando sessão do usuário."

            return (
                "Comando de PC inválido. Use: shutdown [segundos], restart [segundos], lock, sleep, hibernate, logout, cancel, wake [MAC]"
            )
        except Exception as e:
            return f"Erro ao executar comando de PC: {e}"

    def execute_shortcut_action(self, action: str) -> str:
        step = action.strip()
        if not step:
            return "(ação vazia ignorada)"

        if step.lower().startswith("open:"):
            return self.open_target(step[5:].strip())
        if step.lower().startswith("ps:"):
            return self.run_powershell(step[3:].strip())
        if step.lower().startswith("say:"):
            text = step[4:].strip()
            if text:
                self.voice.speak(text, force=True)
                return f"Falou: {text}"
            return "say sem texto"

        return (
            "Ação inválida. Use prefixos: open:, ps:, say:. "
            f"Recebido: {step}"
        )

    def run_shortcut(self, name: str) -> str:
        shortcut = self.get_shortcut(name)
        if not shortcut:
            return f"Atalho '{name.strip().lower()}' não encontrado."

        shortcut_name, actions = shortcut
        steps = [s.strip() for s in actions.split("||") if s.strip()]
        if not steps:
            return f"Atalho '{shortcut_name}' sem ações válidas."

        outputs: list[str] = [f"Executando atalho '{shortcut_name}':"]
        for index, step in enumerate(steps, start=1):
            result = self.execute_shortcut_action(step)
            outputs.append(f"{index}. {result}")
        return "\n".join(outputs)

    def normalize_text(self, value: str) -> str:
        text = value.strip().lower()
        text = unicodedata.normalize("NFD", text)
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        text = re.sub(r"\s+", " ", text)
        return text

    def clean_target_words(self, value: str) -> str:
        target = value.strip()
        parts = target.split()
        while parts and self.normalize_text(parts[0]) in {
            "o",
            "a",
            "os",
            "as",
            "um",
            "uma",
            "pro",
            "pra",
            "para",
            "no",
            "na",
            "nos",
            "nas",
            "do",
            "da",
            "dos",
            "das",
            "arquivo",
            "pasta",
            "app",
            "aplicativo",
            "programa",
        }:
            parts = parts[1:]
        return " ".join(parts).strip()

    def extract_after_first(self, text: str, markers: list[str]) -> str | None:
        normalized = self.normalize_text(text)
        for marker in markers:
            idx = normalized.find(marker)
            if idx >= 0:
                return text[idx + len(marker) :].strip()
        return None

    def suggest_command_correction(self, command: str) -> str | None:
        normalized = self.normalize_text(command)
        if not normalized:
            return None

        aliases = list(self._default_aliases().keys()) + [name for name, _, _ in self.list_aliases()]
        open_markers = ["abrir ", "abre ", "open ", "iniciar ", "inicia "]
        target_open = self.extract_after_first(command, open_markers)
        if target_open:
            target = self.normalize_text(self.clean_target_words(target_open))
            close = difflib.get_close_matches(target, aliases, n=1, cutoff=0.72)
            if close and close[0] != target:
                return f"abrir {close[0]}"

        known_prefixes = [
            "abrir ",
            "open ",
            "executar atalho ",
            "rodar atalho ",
            "powershell ",
            "adicionar alias ",
            "remover alias ",
            "listar aliases",
        ]
        close_prefix = difflib.get_close_matches(normalized, known_prefixes, n=1, cutoff=0.78)
        if close_prefix:
            return close_prefix[0].strip()

        return None

    def looks_like_search_question(self, text: str) -> bool:
        normalized = self.normalize_text(text)
        if not normalized:
            return False

        # Busca web explícita por comando/intenção
        explicit_search_intent = (
            normalized.startswith("/search ")
            or normalized.startswith("pesquisar ")
            or normalized.startswith("pesquisa ")
            or normalized.startswith("buscar ")
            or normalized.startswith("busca ")
            or normalized.startswith("procurar ")
            or normalized.startswith("procura ")
            or normalized.startswith("pesquisa sobre ")
        )
        if explicit_search_intent:
            return True

        # Dados de tempo real sempre priorizam web/APIs
        if self._needs_realtime_data(normalized):
            return True

        # Perguntas gerais vão para LLM + memória + KB (não força web)
        return False

    def _needs_realtime_data(self, normalized: str) -> bool:
        """Detects queries that need real-time/current information."""
        realtime_keywords = [
            # Tempo / clima
            "previsao do tempo", "previsão do tempo", "tempo hoje", "clima hoje",
            "temperatura hoje", "temperatura agora", "vai chover", "chovendo",
            "tempo amanha", "tempo amanhã", "previsao amanha", "previsão amanhã",
            # Notícias
            "noticias", "notícias", "noticias de hoje", "ultimas noticias",
            "últimas notícias", "o que aconteceu", "novidades",
            # Preços / cotações
            "cotacao", "cotação", "dolar hoje", "dólar hoje", "euro hoje",
            "bitcoin hoje", "preco do", "preço do", "valor do", "valor da",
            "gasolina hoje", "selic hoje",
            # Esportes
            "resultado do jogo", "placar", "tabela do campeonato",
            "proximo jogo", "próximo jogo", "classificacao", "classificação",
            # Trânsito / tempo real
            "transito", "trânsito", "transito agora", "como esta o transito",
            # Horários
            "horario de funcionamento", "horário de funcionamento", "aberto agora",
            # Eventos
            "show hoje", "cinema hoje", "evento hoje",
        ]
        return any(kw in normalized for kw in realtime_keywords)

    def confirm_suggestion(self, suggestion: str) -> bool:
        print(f"{self.agent_name}: Você quis dizer '{suggestion}'? (s/n)")
        self.voice.speak(f"Você quis dizer {suggestion}? Responda sim ou não.", force=True)
        choice = input("Confirmação: ").strip().lower()
        return choice in {"s", "sim", "y", "yes"}

    def is_stop_command(self, text: str) -> bool:
        normalized = self.normalize_text(text)
        return normalized in {
            "parar",
            "pare",
            "stop",
            "silencio",
            "silencio por favor",
            "para de falar",
            "pare de falar",
            "parar de falar",
        }

    def handle_local_command(self, command: str) -> str | None:
        text = command.strip()
        lower = text.lower()
        normalized = self.normalize_text(text)

        if normalized in {"/help", "help", "ajuda"}:
            print_help()
            return "Comandos exibidos."

        if normalized in {"modelo status", "status dos modelos", "/model status", "model status"}:
            return self.get_model_status()

        if normalized in {"/model refresh", "model refresh", "atualizar modelos", "recarregar modelos"}:
            return self.refresh_models()

        if normalized.startswith("/wol ") or normalized in {"/wol", "wol"}:
            payload = self.extract_after_first(text, ["/wol ", "wol "]) or ""
            return self.run_wol_command(payload)

        if normalized in {"status do wol", "wol status", "wake on lan status"}:
            return self.get_wol_status()

        if normalized.startswith("configurar wol ") or normalized.startswith("configurar wake on lan "):
            payload = self.extract_after_first(text, ["configurar wol ", "configurar wake on lan "]) or ""
            return self.run_wol_command(f"set {payload}".strip())

        if normalized.startswith("/pc ") or normalized.startswith("pc "):
            payload = self.extract_after_first(text, ["/pc ", "pc "]) or ""
            return self.run_pc_command(payload)

        if self.is_stop_command(text):
            self.voice.stop_speaking()
            return "🔇"

        if normalized in {"voz status", "status da voz", "qual voz"}:
            return self.get_voice_status()

        if normalized in {"voz masculina", "mudar para voz masculina"}:
            return self.set_voice_profile("masculina")

        if normalized in {"voz feminina", "mudar para voz feminina"}:
            return self.set_voice_profile("feminina")

        if normalized.startswith("alterar voz para ") or normalized.startswith("mudar voz para "):
            value = self.extract_after_first(text, ["alterar voz para ", "mudar voz para "]) or ""
            return self.set_voice_profile(value)

        if normalized in {"bom dia", "bom dia!", "bom dia barretao", "bom dia barretao"}:
            return self.daily_briefing()

        if normalized in {"desligar pc", "desligar computador", "desliga o pc", "desliga computador"}:
            return self.run_pc_command("shutdown 60")

        if normalized in {"ligar pc", "ligar computador", "acordar pc", "wake pc"}:
            return self.run_pc_command("wake")

        if normalized in {"reiniciar pc", "reiniciar computador", "reinicia o pc", "reinicia computador"}:
            return self.run_pc_command("restart 60")

        if normalized in {"bloquear pc", "bloquear computador", "bloqueia o pc"}:
            return self.run_pc_command("lock")

        if normalized in {"suspender pc", "suspender computador", "hibernar pc", "hibernar computador"}:
            action = "hibernate" if "hibern" in normalized else "sleep"
            return self.run_pc_command(action)

        if normalized in {"cancelar desligamento", "cancelar reinicio", "cancelar reiniciar", "cancelar shutdown"}:
            return self.run_pc_command("cancel")

        # ── Perfil do usuário ──────────────────────────────────────────────
        profile_triggers = {
            "o que voce sabe sobre mim",
            "o que você sabe sobre mim",
            "meu perfil",
            "minha historia",
            "minha história",
            "o que aprendeu sobre mim",
            "o que voce aprendeu sobre mim",
            "o que você aprendeu sobre mim",
            "me fala meu perfil",
            "mostra meu perfil",
            "mostra o que sabe sobre mim",
        }
        if normalized in profile_triggers:
            return self.show_user_profile()

        # Ensinar nome diretamente
        name_markers = ["meu nome e ", "meu nome é ", "me chamo ", "pode me chamar de "]
        name_val = self.extract_after_first(text, name_markers)
        if name_val is not None:
            name_val = name_val.strip().rstrip(".,!?")
            if name_val:
                self.save_user_fact("nome", name_val)
                first = name_val.split()[0]
                return f"Ótimo! Vou te chamar de {first} daqui pra frente. 👋"

        # Ensinar cidade diretamente
        city_markers = ["eu moro em ", "moro em ", "minha cidade e ", "minha cidade é "]
        city_val = self.extract_after_first(text, city_markers)
        if city_val is not None:
            city_val = city_val.strip().rstrip(".,!?")
            city_val = re.split(r"\s+(?:de|do|da|no|na|em)\s+", city_val)[0].strip()
            if city_val:
                self.save_user_fact("cidade", city_val)
                self.user_city = city_val
                return f"Entendido! Sua cidade é {city_val}. Vou usar isso para o briefing do tempo. ☀️"

        # Esquecer algo do perfil por linguagem natural
        forget_markers = ["esquecer que ", "esqueça que ", "esquece que ", "apagar que "]
        forget_val = self.extract_after_first(text, forget_markers)
        if forget_val is not None:
            key = forget_val.strip().rstrip(".,!?")
            return self.delete_user_fact(key)

        search_markers = ["pesquisar ", "pesquisa ", "buscar ", "busca ", "procura ", "procurar "]
        search_query = self.extract_after_first(text, search_markers)
        if search_query is not None:
            return self.search_web(search_query)

        if normalized.startswith("adicionar evento ") or normalized.startswith("criar evento "):
            payload = self.extract_after_first(text, ["adicionar evento ", "criar evento "]) or ""
            parts = payload.split(" ", 1)
            if len(parts) < 2:
                return "Use: adicionar evento YYYY-MM-DD <título>"
            return self.save_personal_event(parts[0], parts[1])

        if normalized in {"meus eventos", "eventos de hoje", "agenda de hoje"}:
            return self.format_events_for_date(datetime.now().strftime("%Y-%m-%d"))

        if normalized.startswith("adicionar na minha rotina ") or normalized.startswith("adicionar rotina "):
            payload = self.extract_after_first(text, ["adicionar na minha rotina ", "adicionar rotina "]) or ""
            parts = payload.split(" ", 1)
            if len(parts) < 2:
                return "Use: adicionar na minha rotina <dia> <tarefa>"
            return self.save_weekly_routine(parts[0], parts[1])

        if normalized.startswith("minha rotina ") or normalized.startswith("rotina de "):
            day = self.extract_after_first(text, ["minha rotina ", "rotina de "]) or ""
            return self.format_weekly_routine_for_day(day)

        if normalized in {"minha rotina", "minhas rotinas", "rotina da semana"}:
            items = self.list_weekly_routines()
            if not items:
                return "Você ainda não tem rotinas semanais salvas."
            lines = ["Suas rotinas da semana:"]
            for routine_id, weekday, title in items:
                lines.append(f"- [{routine_id}] {self._weekday_name(weekday)}: {title}")
            return "\n".join(lines)

        open_markers = ["abrir ", "abre ", "open ", "iniciar ", "inicia "]
        target_open = self.extract_after_first(text, open_markers)
        if target_open is not None:
            target = self.clean_target_words(target_open)
            resolved = self.get_alias_target(self.normalize_text(target))
            if not resolved:
                resolved = self.get_alias_target(target)
            return self.open_target(resolved if resolved else target)

        if normalized.startswith("adicionar alias ") or normalized.startswith("criar alias ") or normalized.startswith("adiciona alias "):
            payload = self.extract_after_first(text, ["adicionar alias ", "adiciona alias ", "criar alias "]) or ""
            payload_n = self.normalize_text(payload)
            if " para " not in payload_n:
                return "Use: adicionar alias <nome> para <url|alvo>"
            index = payload_n.find(" para ")
            alias_name = payload[:index].strip()
            alias_target = payload[index + 6 :].strip()
            return self.save_alias(alias_name, alias_target)

        if normalized.startswith("corrigir site ") or normalized.startswith("corrigir alias "):
            payload = self.extract_after_first(text, ["corrigir site ", "corrigir alias "]) or ""
            payload_n = self.normalize_text(payload)
            if " para " not in payload_n:
                return "Use: corrigir site <nome> para <url|alvo>"
            index = payload_n.find(" para ")
            alias_name = payload[:index].strip()
            alias_target = payload[index + 6 :].strip()
            return self.fix_alias(alias_name, alias_target)

        if normalized.startswith("remover alias ") or normalized.startswith("apagar alias "):
            payload = self.extract_after_first(text, ["remover alias ", "apagar alias "]) or ""
            return self.delete_alias(payload)

        if normalized in {"listar alias", "listar aliases", "mostrar alias", "mostrar aliases", "quais alias", "quais aliases"}:
            aliases = self.list_aliases()
            if not aliases:
                return "Sem aliases personalizados salvos."
            lines = ["Aliases personalizados:"]
            for name, target, _created_at in aliases:
                lines.append(f"- {name} -> {target}")
            return "\n".join(lines)

        if normalized.startswith("executar atalho ") or normalized.startswith("rodar atalho ") or normalized.startswith("iniciar atalho "):
            payload = self.extract_after_first(text, ["executar atalho ", "rodar atalho ", "iniciar atalho "]) or ""
            return self.run_shortcut(payload)

        if normalized.startswith("powershell ") or normalized.startswith("comando powershell "):
            payload = self.extract_after_first(text, ["comando powershell ", "powershell "]) or ""
            return self.run_powershell(payload)

        if normalized.startswith("falar ") or normalized.startswith("dizer "):
            parts = text.split(" ", 1)
            if len(parts) == 2 and parts[1].strip():
                self.voice.speak(parts[1].strip(), force=True)
                return f"Falou: {parts[1].strip()}"

        # ── Knowledge Base ──────────────────────────────────────────────
        if normalized in {
            "aprender",
            "treinar",
            "treinar barretao",
            "treinar mais",
            "treine o barretao",
            "treine o barretao mais",
        } or ("trein" in normalized and "barretao" in normalized):
            def _seed_bg() -> None:
                try:
                    self.seed_knowledge_base_auto()
                except Exception as e:
                    print(f"Erro no seed do KB: {e}")

            threading.Thread(target=_seed_bg, daemon=True).start()
            return "💾 Treinamento iniciado em background (KB). Use '/kb status' para acompanhar."

        if normalized.startswith("aprender sobre "):
            topic = self.extract_after_first(text, ["aprender sobre "]) or ""
            if topic.strip():
                return self.learn_topic_interactive(topic.strip())
            return "Use: aprender sobre <tópico>"

        if normalized in {"/kb", "/kb status", "status do kb", "kb status"}:
            stats = self.get_kb_stats()
            lines = ["📚 Knowledge Base Status:"]
            lines.append(f"Total de entradas: {stats['total']}")
            for cat, count in stats["by_category"].items():
                lines.append(f"  - {cat}: {count}")
            return "\n".join(lines)

        if normalized in {"/kb cntk+", "kb cntk+", "cntk agressivo", "otimizar kb agressivo"}:
            result = self.optimize_kb_with_cntk(aggressive=True)
            return (
                "🧠 Sistema CNTK AGRESSIVO aplicado no Knowledge Base. "
                f"Entradas otimizadas: {result['updated']}/{result['total']}."
            )

        if normalized in {"/kb cntk", "kb cntk", "aprimorar kb", "otimizar kb"} or (
            "cntk" in normalized and ("kb" in normalized or "knowledge" in normalized or "barretao" in normalized)
        ):
            result = self.optimize_kb_with_cntk()
            return (
                "🧠 Sistema CNTK aplicado no Knowledge Base. "
                f"Entradas otimizadas: {result['updated']}/{result['total']}."
            )

        if normalized in {"/kb seed", "seed kb", "treinar kb"}:
            print("🌱 Seedando KB com tópicos base expandidos...")
            self.seed_knowledge_base_auto()
            return "✅ KB seedado com sucesso! Use '/kb status' para ver."

        if normalized.startswith("/kb search ") or normalized.startswith("buscar kb "):
            query = self.extract_after_first(text, ["/kb search ", "buscar kb "]) or ""
            if query.strip():
                results = self.query_knowledge_base(query.strip(), limit=5)
                if not results:
                    return f"Nenhuma entrada no KB sobre '{query}'."
                lines = [f"📚 Resultados sobre '{query}':"]
                for _, topic, content, category in results:
                    lines.append(f"[{category}] {topic}: {content[:100]}...")
                return "\n".join(lines)
            return "Use: buscar kb <termo>"

        return None

    def wake_mode_loop(self) -> None:
        print(
            "🎧 Modo de escuta ativo. Fale um comando direto. "
            "(Diga 'parar escuta' ou Ctrl+C para sair)"
        )
        while True:
            try:
                heard_original = self.voice.listen_once().strip()
                heard = self.normalize_text(heard_original)
                if not heard:
                    continue

                if "parar escuta" in heard:
                    print("Encerrando modo de chamada.")
                    return

                command = heard_original.strip()
                if not command:
                    print("Não captei o comando.")
                    continue

                if self.is_stop_command(command):
                    self.voice.stop_speaking()
                    print("🔇 Silêncio.")
                    continue

                print(f"Você (voz): {command}")
                answer = self.answer_command(command)
                if answer == "🔇":
                    print("🔇 Silêncio.")
                    continue
                print(f"\n{self.agent_name}: {answer}\n")
                self.voice.speak(answer)
            except KeyboardInterrupt:
                print("\nModo de chamada encerrado.")
                return
            except Exception as e:
                print(f"Erro no modo de chamada: {e}")
                if "Não entendi o áudio" in str(e):
                    print("Tente falar de novo, mais perto do microfone.")
                    continue
                if "PyAudio" in str(e):
                    print(
                        "Microfone não disponível. Entrando no modo de chamada por texto."
                    )
                    self.wake_mode_text_loop()
                    return
                time.sleep(1)

    def wake_mode_text_loop(self) -> None:
        print(
            "⌨️ Modo de escuta por texto ativo. Digite um comando direto. "
            "Exemplo: abrir youtube"
        )
        print("Digite 'parar escuta' para sair.")
        while True:
            try:
                heard = input("Chamada: ").strip()
            except KeyboardInterrupt:
                print("\nModo de chamada por texto encerrado.")
                return

            if not heard:
                continue

            lower = heard.lower()
            if lower == "parar escuta":
                print("Encerrando modo de chamada.")
                return

            if lower in {"/help", "help"}:
                print_help()
                continue

            command = heard

            if not command:
                print("Digite um comando.")
                continue

            if self.is_stop_command(command):
                self.voice.stop_speaking()
                print("🔇 Silêncio.")
                continue

            try:
                answer = self.answer_command(command)
                if answer == "🔇":
                    print("🔇 Silêncio.")
                    continue
                print(f"\n{self.agent_name}: {answer}\n")
                self.voice.speak(answer)
            except Exception as e:
                print(f"Erro ao responder: {e}")
                if "localhost" in str(e) and "11434" in str(e):
                    print("Dica: inicie o Ollama em outro terminal com: ollama run llama3.1:8b")


class DiscordRunner:
    def __init__(self, agent_name: str) -> None:
        self.agent = PersonalAIAgent(enable_voice=False)
        self.agent_name = agent_name

    def start(self) -> None:
        if not self.agent.discord_enabled:
            return
        if not self.agent.discord_token:
            print("Discord desativado: defina DISCORD_BOT_TOKEN no .env.")
            return

        thread = threading.Thread(target=self._run_bot, daemon=True)
        thread.start()
        print(
            f"Discord ativo. Comando de ativação: {self.agent.discord_trigger}"
        )

    def _run_bot(self) -> None:
        try:
            discord = importlib.import_module("discord")
        except Exception as e:
            print(f"Discord indisponível: {e}")
            return

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        trigger = self.agent.discord_trigger
        allowed_channels = self.agent.discord_channel_ids

        @client.event
        async def on_ready() -> None:
            print(f"Bot do Discord conectado como {client.user}")

        @client.event
        async def on_message(message: Any) -> None:
            if message.author == client.user:
                return
            if allowed_channels and message.channel.id not in allowed_channels:
                return

            content = (message.content or "").strip()
            if not content.startswith(trigger):
                return

            command = content[len(trigger) :].strip()
            if not command:
                await message.reply(
                    f"Use {trigger} <comando>. Ex.: {trigger} abrir discord"
                )
                return

            try:
                answer = self.agent.answer_command(command, allow_confirmation=False)
            except Exception as e:
                answer = f"Erro: {e}"

            for chunk_start in range(0, len(answer), 1800):
                await message.reply(answer[chunk_start : chunk_start + 1800])

        client.run(self.agent.discord_token)


def print_help() -> None:
    print("\nComandos disponíveis:")
    print("  /help               Mostrar ajuda")
    print("  /save <texto>       Salvar anotação")
    print("  /perfil             Ver o que o agente aprendeu sobre você")
    print("  /aprender <k> = <v> Ensinar um fato ao agente manualmente")
    print("  /esquecer <chave>   Apagar um fato aprendido")
    print("  /event add ...      Salvar evento pessoal")
    print("  /event list         Listar eventos")
    print("  /event today        Ver eventos de hoje")
    print("  /event del <id>     Remover evento")
    print("  /week add ...       Salvar rotina por dia da semana")
    print("  /week list          Listar rotinas semanais")
    print("  /week day <dia>     Ver rotina de um dia")
    print("  /week del <id>      Remover rotina semanal")
    print("  /notes              Ver últimas anotações")
    print("  /clear              Limpar histórico de conversa")
    print("  /open <alvo>        Abrir site, arquivo, pasta ou app")
    print("  /search <pergunta>  Pesquisar na web e responder")
    print("  /ps <comando>       Executar comando PowerShell")
    print("  /pc <acao>          Controlar PC (shutdown/restart/lock/sleep/hibernate/logout/cancel/wake)")
    print("  /wol <MAC> [ip] [p] Wake-on-LAN (liga/acorda PC na rede)")
    print("  /wol set <MAC> ...  Salvar MAC/broadcast/porta padrão")
    print("  /wol status         Ver configuração Wake-on-LAN")
    print("  /listen             Escutar voz e enviar para o agente")
    print("  /wake               Escuta contínua por nome/chamada")
    print("  /voice on|off       Ativar/desativar fala automática")
    print("  /voice status       Mostrar voz atual")
    print("  /voice set <perfil> Alterar voz (feminina|masculina|profissional|natural|pt-BR-...Neural)")
    print("  /stop               Parar fala atual imediatamente")
    print("  /say <texto>        Falar um texto agora")
    print("  /shortcut add ...   Salvar/atualizar atalho")
    print("  /shortcut run <n>   Executar atalho")
    print("  /shortcut list      Listar atalhos")
    print("  /shortcut del <n>   Remover atalho")
    print("  /alias add <n> <v>  Salvar alias de abertura")
    print("  /alias fix <n> <v>  Corrigir alias/site aprendido")
    print("  /alias list         Listar aliases")
    print("  /alias del <n>      Remover alias")
    print("  /routine status     Ver status do aprendizado")
    print("  /routine patterns   Ver padrões mais usados")
    print("  /routine suggest    Sugerir ações para agora")
    print("  /routine auto <n>   Criar atalho com padrões atuais")
    print("  /proactive status   Ver status do modo proativo")
    print("  /proactive on|off   Ativar/desativar modo proativo")
    print("  /proactive check    Ver atalho sugerido agora")
    print("  /discord status     Ver status da integração Discord")
    print("  /model status       Ver status dos modelos (primário/secundário)")
    print("  /model refresh      Recarregar modelos disponíveis no Ollama")
    print("  📚 Knowledge Base:")
    print("  /kb status          Ver stats do KB (quantas entradas)")
    print("  /kb seed            Gerar conhecimento base (10 tópicos)")
    print("  /kb search <termo>  Buscar no KB")
    print("  aprender sobre X    Aprender sobre novo tópico interativamente")
    print("  /exit               Sair")
    print("\nFormato de atalho:")
    print("  /shortcut add manha open:https://web.whatsapp.com || open:C:\\Users\\Administrador\\Desktop || ps:Get-Date")
    print("  Prefixos: open:, ps:, say:")
    print("\nAlias por voz/texto:")
    print("  adicionar alias trampo para https://calendar.google.com")
    print("  abrir trampo")
    print("  corrigir site ifood para https://www.ifood.com.br")
    print("\nPesquisa:")
    print("  /search quem foi Ayrton Senna")
    print("  pesquisar previsão do tempo em São Paulo")
    print("\nBriefing diário:")
    print("  bom dia")
    print("  adicionar evento 2026-04-10 Consulta médica")
    print("\nControle do PC:")
    print("  /pc shutdown 60     Desligar em 60s")
    print("  /pc restart 60      Reiniciar em 60s")
    print("  /pc lock            Bloquear sessão")
    print("  /pc wake            Enviar WOL para MAC padrão")
    print("  /wol AA:BB:CC:DD:EE:FF 192.168.1.255 9")
    print("  /pc cancel          Cancelar desligar/reiniciar")
    print("\nRotina semanal:")
    print("  adicionar na minha rotina segunda academia 19h")
    print("  minha rotina terça")


def main() -> None:
    print("=== Agente IA Pessoal ===")
    print("Digite /help para ver comandos.\n")

    try:
        agent = PersonalAIAgent()
    except Exception as e:
        print(f"Erro ao iniciar agente: {e}")
        print("Verifique .env, Ollama rodando e dependências instaladas.")
        return

    DiscordRunner(agent.agent_name).start()

    while True:
        if agent.should_prompt_proactive_now():
            suggestion = agent.get_proactive_shortcut_suggestion()
            if suggestion:
                name, score = suggestion
                agent.mark_proactive_prompted()
                choice = input(
                    f"🤖 Modo proativo: você costuma usar '{name}' agora (score {score}). Executar? (s/n): "
                ).strip().lower()
                if choice in {"s", "sim", "y", "yes"}:
                    print(agent.run_shortcut(name))

        user_input = input("Você: ").strip()
        if not user_input:
            continue

        if user_input.lower() == "/exit":
            print("Até mais!")
            break

        if user_input.lower() == "/help":
            print_help()
            continue

        if user_input.lower().startswith("/save "):
            note = user_input[6:].strip()
            if note:
                agent.save_note(note)
                print("✅ Anotação salva.")
            else:
                print("Use: /save <texto>")
            continue

        if user_input.lower() in {"/perfil", "/eu", "/mim"}:
            print(agent.show_user_profile())
            continue

        if user_input.lower().startswith("/aprender "):
            rest = user_input[10:].strip()
            if " = " in rest:
                k, v = rest.split(" = ", 1)
                print(agent.save_user_fact(k.strip(), v.strip()))
            elif " e " in rest.lower():
                parts = rest.split(" e ", 1)
                print(agent.save_user_fact(parts[0].strip(), parts[1].strip()))
            else:
                print("Use: /aprender <chave> = <valor>")
            continue

        if user_input.lower().startswith("/esquecer "):
            key = user_input[10:].strip()
            if key:
                print(agent.delete_user_fact(key))
            else:
                print("Use: /esquecer <chave>")
            continue

        if user_input.lower().startswith("/event "):
            payload = user_input[7:].strip()
            if payload.lower() == "list":
                events = agent.list_personal_events()
                if not events:
                    print("Sem eventos salvos.")
                else:
                    print("\nSeus eventos:")
                    for event_id, event_date, title in events:
                        print(f"- [{event_id}] {event_date} {title}")
                continue

            if payload.lower() == "today":
                print(agent.format_events_for_date(datetime.now().strftime("%Y-%m-%d")))
                continue

            if payload.lower().startswith("del "):
                print(agent.delete_personal_event(payload[4:].strip()))
                continue

            if payload.lower().startswith("add "):
                rest = payload[4:].strip()
                parts = rest.split(" ", 1)
                if len(parts) < 2:
                    print("Use: /event add YYYY-MM-DD <título>")
                else:
                    print(agent.save_personal_event(parts[0], parts[1]))
                continue

            print("Use: /event add|list|today|del ...")
            continue

        if user_input.lower().startswith("/week "):
            payload = user_input[6:].strip()

            if payload.lower() == "list":
                items = agent.list_weekly_routines()
                if not items:
                    print("Sem rotinas semanais salvas.")
                else:
                    print("\nSuas rotinas semanais:")
                    for routine_id, weekday, title in items:
                        print(f"- [{routine_id}] {agent._weekday_name(weekday)}: {title}")
                continue

            if payload.lower().startswith("day "):
                print(agent.format_weekly_routine_for_day(payload[4:].strip()))
                continue

            if payload.lower().startswith("del "):
                print(agent.delete_weekly_routine(payload[4:].strip()))
                continue

            if payload.lower().startswith("add "):
                rest = payload[4:].strip()
                parts = rest.split(" ", 1)
                if len(parts) < 2:
                    print("Use: /week add <dia> <tarefa>")
                else:
                    print(agent.save_weekly_routine(parts[0], parts[1]))
                continue

            print("Use: /week add|list|day|del ...")
            continue

        if user_input.lower() == "/notes":
            notes = agent.get_notes()
            if not notes:
                print("Sem anotações salvas.")
            else:
                print("\nÚltimas anotações:")
                for note_id, content, created_at in notes:
                    print(f"- [{note_id}] {content} ({created_at})")
            continue

        if user_input.lower() == "/clear":
            agent.clear_history()
            print("🧹 Histórico limpo.")
            continue

        if user_input.lower().startswith("/open "):
            print(agent.open_target(user_input[6:]))
            continue

        if user_input.lower().startswith("/search "):
            print(agent.search_web(user_input[8:]))
            continue

        if user_input.lower().startswith("/ps "):
            print(agent.run_powershell(user_input[4:]))
            continue

        if user_input.lower().startswith("/pc "):
            print(agent.run_pc_command(user_input[4:]))
            continue

        if user_input.lower() == "/wol" or user_input.lower().startswith("/wol "):
            payload = user_input[5:] if len(user_input) > 5 else ""
            print(agent.run_wol_command(payload))
            continue

        if user_input.lower() == "/listen":
            try:
                heard = agent.voice.listen_once().strip()
                if not heard:
                    print("Não captei fala.")
                    continue
                print(f"Você (voz): {heard}")
                answer = agent.ask(heard)
                print(f"\n{agent.agent_name}: {answer}\n")
                agent.voice.speak(answer)
            except Exception as e:
                print(f"Erro de voz: {e}")
            continue

        if user_input.lower() == "/wake":
            agent.wake_mode_loop()
            continue

        if user_input.lower().startswith("/voice "):
            option_raw = user_input[7:].strip()
            option = option_raw.lower()
            if option in {"on", "off"}:
                agent.voice.auto_speak = option == "on"
                print(f"Fala automática: {'ativada' if agent.voice.auto_speak else 'desativada'}")
            elif option == "status":
                print(agent.get_voice_status())
            elif option.startswith("set "):
                print(agent.set_voice_profile(option_raw[4:].strip()))
            else:
                print("Use: /voice on|off|status|set <perfil>")
            continue

        if user_input.lower() == "/stop":
            agent.voice.stop_speaking()
            print("🔇 Fala interrompida.")
            continue

        if user_input.lower().startswith("/say "):
            text = user_input[5:].strip()
            if text:
                agent.voice.speak(text, force=True)
                print("🔊 Falado.")
            else:
                print("Use: /say <texto>")
            continue

        if user_input.lower().startswith("/shortcut "):
            payload = user_input[10:].strip()

            if payload.lower() == "list":
                shortcuts = agent.list_shortcuts()
                if not shortcuts:
                    print("Sem atalhos salvos.")
                else:
                    print("\nAtalhos salvos:")
                    for name, actions, created_at in shortcuts:
                        print(f"- {name}: {actions} ({created_at})")
                continue

            if payload.lower().startswith("run "):
                name = payload[4:].strip()
                if not name:
                    print("Use: /shortcut run <nome>")
                else:
                    print(agent.run_shortcut(name))
                continue

            if payload.lower().startswith("del "):
                name = payload[4:].strip()
                print(agent.delete_shortcut(name))
                continue

            if payload.lower().startswith("add "):
                add_payload = payload[4:].strip()
                parts = add_payload.split(" ", 1)
                if len(parts) < 2:
                    print("Use: /shortcut add <nome> <acoes>")
                else:
                    name, actions = parts[0], parts[1]
                    print(agent.save_shortcut(name, actions))
                continue

            print("Use: /shortcut add|run|list|del ...")
            continue

        if user_input.lower().startswith("/alias "):
            payload = user_input[7:].strip()

            if payload.lower() == "list":
                aliases = agent.list_aliases()
                if not aliases:
                    print("Sem aliases personalizados salvos.")
                else:
                    print("\nAliases personalizados:")
                    for name, target, created_at in aliases:
                        print(f"- {name} -> {target} ({created_at})")
                continue

            if payload.lower().startswith("del "):
                print(agent.delete_alias(payload[4:].strip()))
                continue

            if payload.lower().startswith("add "):
                rest = payload[4:].strip()
                parts = rest.split(" ", 1)
                if len(parts) < 2:
                    print("Use: /alias add <nome> <url|alvo>")
                else:
                    print(agent.save_alias(parts[0], parts[1]))
                continue

            if payload.lower().startswith("fix "):
                rest = payload[4:].strip()
                parts = rest.split(" ", 1)
                if len(parts) < 2:
                    print("Use: /alias fix <nome> <url|alvo>")
                else:
                    print(agent.fix_alias(parts[0], parts[1]))
                continue

            print("Use: /alias add|fix|list|del ...")
            continue

        if user_input.lower().startswith("/routine"):
            payload = user_input[8:].strip()

            if payload == "" or payload.lower() == "status":
                status = "ativado" if agent.routine_learning_enabled else "desativado"
                print(f"Aprendizado de rotina: {status}")
                continue

            if payload.lower() == "patterns":
                items = agent.get_routine_overview(limit=20)
                if not items:
                    print("Sem padrões registrados ainda.")
                else:
                    print("\nPadrões mais frequentes:")
                    for action_type, target, count in items:
                        print(f"- {action_type}:{target} ({count}x)")
                continue

            if payload.lower() == "suggest":
                print(agent.routine_suggestions_text())
                continue

            if payload.lower().startswith("auto "):
                name = payload[5:].strip()
                if not name:
                    print("Use: /routine auto <nome>")
                else:
                    print(agent.create_shortcut_from_routine(name))
                continue

            print("Use: /routine status|patterns|suggest|auto <nome>")
            continue

        if user_input.lower().startswith("/proactive"):
            payload = user_input[10:].strip().lower()

            if payload in {"", "status"}:
                status = "ativado" if agent.proactive_enabled else "desativado"
                print(
                    f"Modo proativo: {status} (mínimo por padrão: {agent.proactive_min_count}x)"
                )
                continue

            if payload == "on":
                agent.proactive_enabled = True
                print("Modo proativo ativado.")
                continue

            if payload == "off":
                agent.proactive_enabled = False
                print("Modo proativo desativado.")
                continue

            if payload == "check":
                suggestion = agent.get_proactive_shortcut_suggestion()
                if not suggestion:
                    print("Sem sugestão proativa para este horário.")
                else:
                    name, score = suggestion
                    print(f"Sugestão atual: '{name}' (score {score})")
                continue

            print("Use: /proactive status|on|off|check")
            continue

        if user_input.lower().startswith("/discord"):
            payload = user_input[8:].strip().lower()
            if payload in {"", "status"}:
                status = "ativado" if agent.discord_enabled else "desativado"
                channels = (
                    ", ".join(str(item) for item in sorted(agent.discord_channel_ids))
                    if agent.discord_channel_ids
                    else "todos"
                )
                print(
                    f"Discord: {status} | trigger: {agent.discord_trigger} | canais: {channels}"
                )
                continue

            print("Use: /discord status")
            continue

        if user_input.lower().startswith("/model"):
            payload = user_input[6:].strip().lower()
            if payload in {"", "status"}:
                print(agent.get_model_status())
            elif payload == "refresh":
                print(agent.refresh_models())
            else:
                print("Use: /model status|refresh")
            continue

        try:
            answer = agent.ask(user_input)
            print(f"\n{agent.agent_name}: {answer}\n")
            agent.voice.speak(answer)
        except Exception as e:
            print(f"Erro ao gerar resposta: {e}")
            if "localhost" in str(e) and "11434" in str(e):
                print("Dica: inicie o Ollama e rode: ollama run llama3.1:8b")


if __name__ == "__main__":
    main()
