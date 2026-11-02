"""Provider presets for Jev-compatible judgment services.

Adapted from CharTyr_MaiWork/maiwork/jev_presets.py (GPLv3).
Two protocols:
- ``systemone``: TypeSafe-native shape — request ``{model, state, questions}``,
  response ``{answers: {name: ...}}``. Most providers use this.
- ``openai_decisions``: OpenAI Decisions API shape — request ``{model, input, questions:[…]}``,
  response ``answers`` is an array.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JevPreset:
    """One provider preset: default URL/model + a human-readable note."""

    id: str
    name: str
    protocol: str  # "systemone" or "openai_decisions"
    url: str
    model: str
    docs_url: str
    note: str


PRESETS: dict[str, JevPreset] = {
    "typesafe": JevPreset(
        id="typesafe",
        name="TypeSafe 官方",
        protocol="systemone",
        url="https://api.typesafe.ai/v1/systemone",
        model="jev-1.13.0",
        docs_url="https://docs.typesafe.ai/api",
        note="Jev 官方服务，即内置服务；也支持使用密钥文件。",
    ),
    "openrouter": JevPreset(
        id="openrouter",
        name="OpenRouter",
        protocol="systemone",
        url="https://openrouter.ai/api/v1/systemone",
        model="typesafe/jev-1.13",
        docs_url="https://openrouter.ai/docs/guides/community/jev",
        note="一个密钥可调用多家模型。",
    ),
    "opencode": JevPreset(
        id="opencode",
        name="OpenCode Zen",
        protocol="systemone",
        url="https://opencode.ai/zen/v1/systemone",
        model="jev-1.13",
        docs_url="https://opencode.ai/docs/zen",
        note="jev-1.13-free 限时免费。",
    ),
    "commandcode": JevPreset(
        id="commandcode",
        name="Command Code",
        protocol="systemone",
        url="https://api.commandcode.ai/provider/v1/systemone",
        model="typesafe/jev",
        docs_url="https://commandcode.ai/models/jev",
        note="需要订阅 Provider API 套餐。",
    ),
    "vercel": JevPreset(
        id="vercel",
        name="Vercel AI Gateway",
        protocol="systemone",
        url="https://ai-gateway.vercel.sh/typesafe/v1/systemone",
        model="typesafe-ai/jev",
        docs_url="https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe",
        note="通过 Vercel AI Gateway 调用，费用计入 Vercel 账户。",
    ),
    "upstage": JevPreset(
        id="upstage",
        name="Upstage Solar Decide",
        protocol="systemone",
        url="https://api.upstage.ai/v1/systemone",
        model="solar-decide",
        docs_url="https://console.upstage.ai/api/systemone",
        note="公测中；choice 类问题最多 26 个选项。",
    ),
    "inception": JevPreset(
        id="inception",
        name="Inception Mercury Decide",
        protocol="systemone",
        url="https://api.inceptionlabs.ai/v1/decisions",
        model="mercury-decide",
        docs_url="https://docs.inceptionlabs.ai/capabilities/decisions",
        note="",
    ),
    "liquid": JevPreset(
        id="liquid",
        name="Liquid AI d1",
        protocol="systemone",
        url="https://api.liquid.ai/decisions/v1/systemone",
        model="d1",
        docs_url="https://docs.liquid.ai/lfm/models/d1",
        note="d1:free 为免费档。",
    ),
    "cloudflare": JevPreset(
        id="cloudflare",
        name="Cloudflare Clef",
        protocol="systemone",
        url=(
            "https://api.cloudflare.com/client/v4/accounts/{account_id}"
            "/ai/run/@cf/cloudflare/clef-flash"
        ),
        model="clef-flash",
        docs_url="https://developers.cloudflare.com/workers-ai/models/clef/",
        note="需将地址中的 {account_id} 替换为 Cloudflare 账号 ID；使用 clef 模型时，地址末尾也需改为 clef。",
    ),
    "openai": JevPreset(
        id="openai",
        name="OpenAI Decisions",
        protocol="openai_decisions",
        url="https://api.openai.com/v1/decisions",
        model="gpt-6-luna",
        docs_url="https://developers.openai.com/api/docs/guides/decisions",
        note="OpenAI 自有的判断模型（公测中），不属于 Jev。",
    ),
}

# Map provider id -> env var name used for key resolution
PROVIDER_ENV_KEYS: dict[str, str] = {
    "typesafe": "TYPESAFE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "opencode": "OPENCODE_API_KEY",
    "commandcode": "COMMANDCODE_API_KEY",
    "vercel": "VERCEL_API_KEY",
    "upstage": "UPSTAGE_API_KEY",
    "inception": "INCEPTION_API_KEY",
    "liquid": "LIQUID_API_KEY",
    "cloudflare": "CLOUDFLARE_API_KEY",
    "openai": "OPENAI_API_KEY",
}

DEFAULT_PROVIDER = "typesafe"


def get_preset(provider_id: str) -> JevPreset:
    """Return the preset for a provider id, falling back to typesafe."""
    return PRESETS.get(provider_id, PRESETS[DEFAULT_PROVIDER])
