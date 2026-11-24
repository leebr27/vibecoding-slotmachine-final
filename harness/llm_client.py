"""Pluggable LLM client.

Backends
--------
* ``claude-cli`` (primary): shells out to ``claude -p --output-format json``
  with no tools, no session persistence, no settings/MCP, and our own system
  prompt, from an empty working directory. Each call is an isolated, real
  generation that uses whatever authentication Claude Code already has.
* ``ollama``: local models via http://localhost:11434 (auto-detected).
* ``anthropic`` / ``openai``: HTTP APIs if ANTHROPIC_API_KEY / OPENAI_API_KEY
  are set. Uses urllib only, so no SDK dependency.
* ``scripted``: deterministic canned responses, used only by unit tests.

Logging and resume
------------------
Every successful call is appended to a JSONL call log (prompt, system prompt,
raw backend response, token usage, cost, latency, purpose tag). The log is
also the cache: a request is identified by
``sha256(backend, model, system, prompt, sample_index)``, so re-running an
experiment after an interruption replays finished calls from disk and only
issues the missing ones.

``sample_index`` gives independent draws for the same prompt (sample 0, 1,
2, ...). Two experimental conditions that ask for the same (prompt, sample)
receive the same stored draw: the simulation technique of common random
numbers, which removes sampling noise from between-condition comparisons.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class LLMResponse:
    text: str
    backend: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    key: str = ""
    sample: int = 0
    tag: str = ""
    cached: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_creation_tokens

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.output_tokens


class LLMError(RuntimeError):
    pass


class RateLimitError(LLMError):
    pass


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
class Backend:
    name = "base"

    def __init__(self, model: str):
        self.model = model

    def complete(self, system: str, prompt: str) -> LLMResponse:  # pragma: no cover
        raise NotImplementedError


def find_claude_binary() -> str | None:
    cands = [os.environ.get("CLAUDE_BIN"), shutil.which("claude"),
             str(Path.home() / ".claude/local/claude"), str(Path.home() / ".local/bin/claude")]
    for pattern in ("~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude",
                    "~/.cursor/extensions/anthropic.claude-code-*/resources/native-binary/claude"):
        cands.extend(sorted(glob.glob(os.path.expanduser(pattern)), reverse=True))
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


# Fields of the CLI's JSON envelope that describe the local account rather
# than the generation; dropped before anything is written to disk.
SCRUB_KEYS = ("credential_expires_at",)

_RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "usage limit", "overloaded", "429", "529")


class ClaudeCLIBackend(Backend):
    name = "claude-cli"

    def __init__(self, model: str = "haiku", binary: str | None = None, timeout_s: float = 240.0):
        super().__init__(model)
        self.binary = binary or find_claude_binary()
        if not self.binary:
            raise LLMError("claude CLI not found; set CLAUDE_BIN or install Claude Code")
        self.timeout_s = timeout_s
        self._cwd = tempfile.mkdtemp(prefix="vsm_claude_")  # empty dir: no CLAUDE.md, no repo context

    def complete(self, system: str, prompt: str) -> LLMResponse:
        cmd = [self.binary, "-p", "--output-format", "json", "--model", self.model,
               "--tools", "", "--no-session-persistence", "--strict-mcp-config",
               "--setting-sources", "", "--system-prompt", system]
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  timeout=self.timeout_s, cwd=self._cwd)
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude CLI timed out after {self.timeout_s}s") from e
        latency = time.perf_counter() - t0
        out = proc.stdout.strip()
        try:
            data = json.loads(out.splitlines()[-1] if out else "{}")
        except json.JSONDecodeError:
            data = {}
        blob = (out + proc.stderr).lower()
        if proc.returncode != 0 or not data or data.get("is_error"):
            msg = data.get("result") or proc.stderr[-500:] or out[-500:]
            if any(m in blob for m in _RATE_LIMIT_MARKERS):
                raise RateLimitError(msg)
            raise LLMError(f"claude CLI error (rc={proc.returncode}): {msg}")
        usage = data.get("usage", {})
        model_usage = data.get("modelUsage", {})
        resolved = next(iter(model_usage), self.model)
        return LLMResponse(
            text=data.get("result", ""),
            backend=self.name,
            model=resolved,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
            cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
            cost_usd=float(data.get("total_cost_usd", 0.0)),
            latency_s=latency,
            raw={k: v for k, v in data.items() if k not in SCRUB_KEYS},
        )


def _http_json(url: str, payload: dict, headers: dict, timeout: float = 240.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
        "content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code in (429, 529, 503):
            raise RateLimitError(body) from e
        raise LLMError(f"HTTP {e.code}: {body[:500]}") from e


class OllamaBackend(Backend):
    name = "ollama"
    URL = "http://localhost:11434"

    @classmethod
    def available(cls) -> bool:
        try:
            with urllib.request.urlopen(cls.URL + "/api/tags", timeout=1.5):
                return True
        except Exception:
            return False

    def complete(self, system: str, prompt: str) -> LLMResponse:
        t0 = time.perf_counter()
        data = _http_json(self.URL + "/api/chat", {
            "model": self.model, "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }, {})
        return LLMResponse(
            text=data.get("message", {}).get("content", ""), backend=self.name, model=self.model,
            input_tokens=int(data.get("prompt_eval_count", 0)), output_tokens=int(data.get("eval_count", 0)),
            latency_s=time.perf_counter() - t0, raw=data)


class AnthropicAPIBackend(Backend):
    name = "anthropic"
    ALIASES = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}

    def complete(self, system: str, prompt: str) -> LLMResponse:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY not set")
        model = self.ALIASES.get(self.model, self.model)
        t0 = time.perf_counter()
        data = _http_json("https://api.anthropic.com/v1/messages", {
            "model": model, "max_tokens": 4096, "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }, {"x-api-key": key, "anthropic-version": "2023-06-01"})
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        u = data.get("usage", {})
        return LLMResponse(text=text, backend=self.name, model=data.get("model", model),
                           input_tokens=int(u.get("input_tokens", 0)), output_tokens=int(u.get("output_tokens", 0)),
                           latency_s=time.perf_counter() - t0, raw=data)


class OpenAIAPIBackend(Backend):
    name = "openai"

    def complete(self, system: str, prompt: str) -> LLMResponse:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise LLMError("OPENAI_API_KEY not set")
        t0 = time.perf_counter()
        data = _http_json("https://api.openai.com/v1/chat/completions", {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }, {"authorization": f"Bearer {key}"})
        u = data.get("usage", {})
        return LLMResponse(text=data["choices"][0]["message"]["content"], backend=self.name,
                           model=data.get("model", self.model), input_tokens=int(u.get("prompt_tokens", 0)),
                           output_tokens=int(u.get("completion_tokens", 0)),
                           latency_s=time.perf_counter() - t0, raw=data)


class ScriptedBackend(Backend):
    """Deterministic backend for unit tests. `script(system, prompt, n)` -> text."""
    name = "scripted"

    def __init__(self, script: Callable[[str, str, int], str], model: str = "scripted"):
        super().__init__(model)
        self.script = script
        self.n_calls = 0
        self._lock = threading.Lock()

    def complete(self, system: str, prompt: str) -> LLMResponse:
        with self._lock:
            n = self.n_calls
            self.n_calls += 1
        text = self.script(system, prompt, n)
        return LLMResponse(text=text, backend=self.name, model=self.model,
                           input_tokens=len(prompt) // 4, output_tokens=len(text) // 4, latency_s=0.01)


# ---------------------------------------------------------------------------
# Client with persistent call log / cache
# ---------------------------------------------------------------------------
class LLMClient:
    def __init__(self, backend: Backend, log_path: str | Path | None = None,
                 max_retries: int = 4, use_cache: bool = True):
        self.backend = backend
        self.log_path = Path(log_path) if log_path else None
        self.max_retries = max_retries
        self.use_cache = use_cache
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}
        self.n_live_calls = 0
        if self.log_path and self.log_path.exists():
            for line in self.log_path.read_text().splitlines():
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue  # tolerate a torn final line from an interrupted run
                self._cache[rec["key"]] = rec

    @property
    def name(self) -> str:
        return f"{self.backend.name}:{self.backend.model}"

    def request_key(self, system: str, prompt: str, sample: int) -> str:
        h = hashlib.sha256()
        for part in (self.backend.name, self.backend.model, system, prompt, str(sample)):
            h.update(part.encode())
            h.update(b"\x00")
        return h.hexdigest()

    def complete(self, prompt: str, system: str, sample: int = 0, tag: str = "") -> LLMResponse:
        key = self.request_key(system, prompt, sample)
        if self.use_cache:
            with self._lock:
                rec = self._cache.get(key)
            if rec is not None:
                return self._from_record(rec, cached=True)
        delay = 5.0
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.backend.complete(system, prompt)
                break
            except RateLimitError as e:
                last = e
                time.sleep(delay * 6)
                delay *= 2
            except LLMError as e:
                last = e
                time.sleep(delay)
                delay *= 2
        else:
            raise LLMError(f"giving up after {self.max_retries + 1} attempts: {last}")
        resp.key, resp.sample, resp.tag = key, sample, tag
        rec = {"key": key, "sample": sample, "tag": tag, "system": system, "prompt": prompt,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **{k: v for k, v in asdict(resp).items()
                                                               if k not in ("key", "sample", "tag", "cached")}}
        with self._lock:
            self.n_live_calls += 1
            self._cache[key] = rec
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a") as f:
                    f.write(json.dumps(rec) + "\n")
        return resp

    @staticmethod
    def _from_record(rec: dict, cached: bool) -> LLMResponse:
        fields = {k: rec[k] for k in LLMResponse.__dataclass_fields__ if k in rec}
        fields["cached"] = cached
        return LLMResponse(**fields)


def make_backend(kind: str = "auto", model: str | None = None) -> Backend:
    """Construct a backend. `auto` prefers claude-cli, then ollama, then APIs."""
    if kind == "auto":
        if find_claude_binary():
            kind = "claude-cli"
        elif OllamaBackend.available():
            kind = "ollama"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            kind = "anthropic"
        elif os.environ.get("OPENAI_API_KEY"):
            kind = "openai"
        else:
            raise LLMError("no LLM backend available (claude CLI, ollama, or API key)")
    if kind == "claude-cli":
        return ClaudeCLIBackend(model or "haiku")
    if kind == "ollama":
        return OllamaBackend(model or "qwen2.5-coder:7b")
    if kind == "anthropic":
        return AnthropicAPIBackend(model or "haiku")
    if kind == "openai":
        return OpenAIAPIBackend(model or "gpt-4o-mini")
    raise ValueError(f"unknown backend {kind!r}")
