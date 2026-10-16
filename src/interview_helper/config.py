"""Small, backend-only TOML configuration; paths resolve beside the config."""

from dataclasses import dataclass, field
from pathlib import Path
import os
import tomllib
from urllib.parse import urlsplit


@dataclass
class Endpoint:
    name: str
    base_url: str
    model: str
    api_key_env: str = "INTERVIEW_API_KEY"
    api_key: str = field(default="", repr=False)
    api_key_file: str = field(default="", repr=False)
    transport: str = "http"
    compact: bool = False
    host_id: str = ""
    parameters: dict = field(default_factory=dict)
    timeout: float = 90
    backend: str = "chat_completions"
    oauth_file: str = field(default="", repr=False)
    # False means drain to completion: disconnect is not proven to stop inference.
    cancel_supported: bool = False

    def __post_init__(self):
        u = urlsplit(self.base_url)
        if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
            raise ValueError("Endpoint must be an HTTP(S) URL without embedded credentials")
        if u.query or u.fragment:
            raise ValueError("Endpoint URL cannot contain query or fragment")
        if not self.name or not self.model or not 1 <= self.timeout <= 300:
            raise ValueError("Endpoint needs name, model and timeout between 1 and 300 seconds")
        if self.backend not in {"chat_completions", "openai_api", "chatgpt"}:
            raise ValueError("Unknown inference backend")
        if self.transport not in {"http", "websocket"}:
            raise ValueError("Unknown transport")
        if self.backend == "chat_completions" and (self.transport != "http" or self.compact):
            raise ValueError("Local transport/protocol must remain unchanged")
        allowed = {"temperature", "top_p", "max_tokens", "reasoning_effort", "chat_template_kwargs"}
        if self.backend != "chat_completions":
            if self.base_url.rstrip("/") != "https://api.openai.com/v1":
                raise ValueError("Cloud backends require the official HTTPS API endpoint")
            allowed = (
                {"reasoning_effort", "max_output_tokens", "service_tier"}
                if self.backend == "openai_api"
                else {"reasoning_effort"}
            )
            if self.parameters.get("reasoning_effort", "low") not in {"none", "low"}:
                raise ValueError("This iteration supports explicit none or low cloud reasoning")
            if (
                self.model.startswith("gpt-6.1-sol")
                and self.parameters.get("reasoning_effort") == "none"
            ):
                raise ValueError(
                    "GPT-6.1 Sol does not support none reasoning; choose low explicitly"
                )
            if self.backend == "chatgpt" and not self.oauth_file:
                raise ValueError("ChatGPT backend requires its own account credential file")
        tier = self.parameters.get("service_tier", "default")
        if tier not in {"default", "fast", "ultrafast"}:
            raise ValueError("Unsupported service tier")
        if tier == "ultrafast" and not self.model.startswith("gpt-6.1-sol"):
            raise ValueError("Ultrafast requires a supported Sol model")
        if set(self.parameters) - allowed:
            raise ValueError("Unsupported endpoint parameter; routing overrides are forbidden")
        self.host_id = self.host_id or self.name

    @property
    def key(self):
        value = self.api_key or os.environ.get(self.api_key_env, "")
        if value or not self.api_key_file:
            return value
        path = Path(self.api_key_file)
        if not path.exists():
            return ""
        if path.stat().st_mode & 0o077:
            raise ValueError("API key file must have mode 0600")
        return path.read_text().strip()


@dataclass
class Config:
    root: Path
    data_dir: Path
    model_dir: Path
    device: str = "cuda"
    compute_type: str = "float16"
    model: str = "large-v3-turbo"
    model_revision: str = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
    language: str = "en"
    glossary: str = "Java, Perl, C++, Python, SQL, API, mutex, deadlock, idempotency, Kubernetes"
    strategy: str = "single"
    endpoints: list[Endpoint] = field(default_factory=list)
    local_endpoints: list[Endpoint] = field(default_factory=list)
    local_strategy: str = "single"
    selection_file: Path | None = field(default=None, init=False, repr=False)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    review_seconds: float = 1.8
    context_seconds: float = 90
    context_chars: int = 6000
    scenario_chars: int = 16000
    candidate_context: str = ""
    rms_threshold: float = 0.002
    port: int = 8787

    @classmethod
    def load(cls, path: Path):
        path = path.expanduser().resolve()
        raw = tomllib.loads(path.read_text()) if path.exists() else {}
        root = path.parent

        def local(value):
            return (root / value).expanduser().resolve()

        asr = raw.pop("asr", {})
        capture = raw.pop("capture", {})
        endpoint_data = raw.pop("endpoints", [])
        local_data = raw.pop("local_endpoints", [])
        for endpoint in endpoint_data + local_data:
            for key in ("oauth_file", "api_key_file"):
                if endpoint.get(key):
                    endpoint[key] = str(local(endpoint[key]))
        endpoints = [Endpoint(**e) for e in endpoint_data]
        obj = cls(
            root=root,
            data_dir=local(raw.pop("data_dir", "Transcribed")),
            model_dir=local(raw.pop("model_dir", "Models")),
            endpoints=endpoints,
            local_endpoints=[Endpoint(**e) for e in local_data],
            **asr,
            **capture,
            **raw,
        )
        if not local_data:
            obj.local_endpoints = [e for e in endpoints if e.backend == "chat_completions"]
            if len(obj.local_endpoints) == len(endpoints):
                obj.local_strategy = obj.strategy
        obj.validate()
        obj.selection_file = root / ".local" / (path.stem + "-connection.json")
        from .connections import restore

        restore(obj)
        return obj

    def validate(self):
        if self.device not in {"cpu", "cuda"}:
            raise ValueError("ASR device must be explicitly cpu or cuda")
        if self.compute_type not in {"int8", "float16", "float32", "int8_float16"}:
            raise ValueError("Unsupported compute_type")
        if self.local_strategy not in {"single", "race"}:
            raise ValueError("Local strategy must be single or race")
        if len(self.local_endpoints) > 2 or (
            self.local_strategy == "race" and len(self.local_endpoints) != 2
        ):
            raise ValueError("Local fallback supports up to two endpoints; race needs two")
        if any(e.backend != "chat_completions" for e in self.local_endpoints):
            raise ValueError("Local fallback must use local chat-completions endpoints")
        if len({e.host_id for e in self.local_endpoints}) != len(self.local_endpoints):
            raise ValueError("Local fallback hosts must be distinct")
        if len({e.name for e in self.local_endpoints}) != len(self.local_endpoints):
            raise ValueError("Local fallback names must be unique")
        if self.strategy not in {"single", "race"}:
            raise ValueError("strategy must be single or race")
        if len(self.endpoints) > 2 or (self.strategy == "race" and len(self.endpoints) != 2):
            raise ValueError("Race needs exactly two explicit endpoints; maximum two")
        if len({e.host_id for e in self.endpoints}) != len(self.endpoints):
            raise ValueError("Profiles must identify distinct inference hosts")
        if len({e.name for e in self.endpoints}) != len(self.endpoints):
            raise ValueError("Endpoint names must be unique")
        if not 0.3 <= self.review_seconds <= 10 or not 1000 <= self.context_chars <= 12000:
            raise ValueError("Review interval/context bound out of range")
        if not 1024 <= self.port <= 65535 or not 0 <= self.rms_threshold <= 0.1:
            raise ValueError("Port or silence threshold out of range")
        if not 10 <= self.context_seconds <= 180 or not 6000 <= self.scenario_chars <= 32000:
            raise ValueError("Recent/scenario context bound out of range")
        if len(self.candidate_context) > 6000:
            raise ValueError("Candidate context exceeds 6000 characters")
