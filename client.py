"""Jev-compatible judgment service HTTP client; never logs request bodies or credentials.

Supports two protocols:
- ``systemone``: TypeSafe-native — POST ``{model, state, questions}`` → ``{answers: {name: ...}}``
- ``openai_decisions``: OpenAI Decisions — POST ``{model, input, questions:[…]}`` → ``{answers: [...]}``

Provider presets in provider_presets.py. ``api_url`` may contain a ``{account_id}``
placeholder (Cloudflare) — substitute before use.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import httpx

from .provider_presets import PROVIDER_ENV_KEYS, DEFAULT_PROVIDER, get_preset

DEFAULT_API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.13.0"
DEFAULT_PROTOCOL = "systemone"


class TypeSafeError(Exception):
    pass


def resolve_key(
    configured: str = "",
    key_file: str = "",
    provider_id: str = DEFAULT_PROVIDER,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve API key: env var → configured → key_file.

    Provider-specific env var names come from PROVIDER_ENV_KEYS;
    falls back to TYPESAFE_API_KEY for unknown providers.
    """
    source = os.environ if env is None else env
    env_name = PROVIDER_ENV_KEYS.get(provider_id, PROVIDER_ENV_KEYS[DEFAULT_PROVIDER])
    key = str(source.get(env_name, "") or configured or "").strip()
    if key:
        return key
    path = str(
        source.get("TYPESAFE_KEY_FILE", "")
        or key_file
        or (Path.home() / ".typesafe_key")
    )
    try:
        candidate = Path(path).expanduser()
        if candidate.is_symlink() or not candidate.is_file():
            return ""
        return candidate.read_text().strip()
    except OSError:
        return ""


class TypeSafeClient:
    """POST to a systemone-protocol endpoint and return the answers dict."""

    def __init__(
        self,
        *,
        http: Any,
        api_url: str = DEFAULT_API_URL,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 1.5,
    ) -> None:
        self.http = http
        self.api_url = str(api_url or DEFAULT_API_URL).strip()
        self.model = str(model or DEFAULT_MODEL).strip()
        self.timeout_s = max(0.1, float(timeout_s))

    async def evaluate(
        self,
        api_key: str,
        state: Dict[str, Any],
        questions: Dict[str, Dict[str, str]],
    ) -> Dict[str, Any]:
        if not api_key:
            raise TypeSafeError("no_api_key")
        payload = {"model": self.model, "state": state, "questions": questions}
        try:
            response = await self.http.post(
                self.api_url,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=self.timeout_s,
            )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            raise TypeSafeError(type(exc).__name__) from exc
        if response.status_code != 200:
            raise TypeSafeError(f"http_{response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise TypeSafeError("bad_json") from exc
        if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
            raise TypeSafeError("missing_answers")
        return data


class OpenAIDecisionsClient:
    """POST to OpenAI Decisions API and normalise the answers list into a dict.

    Request shape: ``{model, input, questions: [{name, type, instructions, criteria?}]}``
    Response shape: ``{answers: [{name, value, ...}]}``

    The ``questions`` dict sent by the caller is keyed by question name;
    this client converts to/from the array form transparently.
    """

    def __init__(
        self,
        *,
        http: Any,
        api_url: str = "https://api.openai.com/v1/decisions",
        model: str = "gpt-6-luna",
        timeout_s: float = 1.5,
    ) -> None:
        self.http = http
        self.api_url = str(api_url or "https://api.openai.com/v1/decisions").strip()
        self.model = str(model or "gpt-6-luna").strip()
        self.timeout_s = max(0.1, float(timeout_s))

    async def evaluate(
        self,
        api_key: str,
        state: Dict[str, Any],
        questions: Dict[str, Dict[str, str]],
    ) -> Dict[str, Any]:
        if not api_key:
            raise TypeSafeError("no_api_key")

        # Convert dict-keyed questions to the array form OpenAI expects
        question_list: List[Dict[str, Any]] = []
        for name, q in questions.items():
            entry: Dict[str, Any] = {"name": name, "type": q.get("type", "noul")}
            if q.get("instructions"):
                entry["instructions"] = q["instructions"]
            if q.get("criteria"):
                entry["criteria"] = q["criteria"]
            question_list.append(entry)

        payload = {
            "model": self.model,
            "input": state,
            "questions": question_list,
        }
        try:
            response = await self.http.post(
                self.api_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_s,
            )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            raise TypeSafeError(type(exc).__name__) from exc
        if response.status_code != 200:
            raise TypeSafeError(f"http_{response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise TypeSafeError("bad_json") from exc

        # Normalise answers array → dict keyed by name
        answers = data.get("answers")
        if not isinstance(answers, list):
            raise TypeSafeError("missing_answers")
        result: Dict[str, Any] = {}
        for item in answers:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if name:
                result[str(name)] = item
        if not result:
            raise TypeSafeError("missing_answers")
        return {"answers": result}


def make_client(
    *,
    http: Any,
    provider_id: str = DEFAULT_PROVIDER,
    api_url: str = "",
    model: str = "",
    timeout_s: float = 1.5,
) -> TypeSafeClient | OpenAIDecisionsClient:
    """Factory: pick the right client class for a provider.

    ``api_url`` and ``model`` override the preset defaults when non-empty.
    ``{account_id}`` in the URL is substituted if the provider is cloudflare.
    """
    preset = get_preset(provider_id)
    url = api_url or preset.url
    mdl = model or preset.model
    ts = max(0.1, float(timeout_s))

    if preset.protocol == "openai_decisions":
        return OpenAIDecisionsClient(http=http, api_url=url, model=mdl, timeout_s=ts)

    # Cloudflare URL may contain {account_id} — substitute from env
    if provider_id == "cloudflare" and "{account_id}" in url:
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        if account_id:
            url = url.replace("{account_id}", account_id)

    return TypeSafeClient(http=http, api_url=url, model=mdl, timeout_s=ts)
