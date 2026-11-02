"""Jev Planner 前置插件：只过滤无关记忆、标记外部事实属性。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

import httpx
from maibot_sdk import Field, HookHandler, MaiBotPlugin, PluginConfigBase
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder

from .client import DEFAULT_API_URL, DEFAULT_MODEL, make_client, resolve_key
from .hook_logic import run_before_request
from .processor import Processor, Settings
from .provider_presets import PRESETS, DEFAULT_PROVIDER, get_preset
from .stats import Stats, should_log_stats

logger = logging.getLogger(__name__)

PLUGIN_VERSION = "0.4.0"


class PluginSectionConfig(PluginConfigBase):
    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=False, description="是否启用；默认关闭")
    config_version: str = Field(default="0.3.0", description="配置版本")
    stats_log_every_n_rounds: int = Field(
        default=50,
        description="每处理 N 轮输出一次统计摘要到日志；0 表示关闭。摘要只含计数与延迟，不含聊天内容",
    )


class PreprocessorSectionConfig(PluginConfigBase):
    __ui_label__ = "Jev 前置处理"
    __ui_icon__ = "filter"
    __ui_order__ = 1

    provider: str = Field(
        default=DEFAULT_PROVIDER,
        description="判断服务商：typesafe / openrouter / opencode / commandcode / vercel / upstage / inception / liquid / cloudflare / openai",
    )
    api_url: str = Field(default="", description="API 地址；留空则按 provider 预设自动填充")
    model: str = Field(default="", description="模型名；留空则按 provider 预设自动填充")
    api_key: str = Field(default="", description="留空则读取环境变量或 key 文件")
    key_file: str = Field(default="~/.typesafe_key", description="私有 key 文件路径")
    timeout_s: float = Field(default=1.5, description="单次 Jev 请求超时秒数")
    memory_relevance_threshold: float = Field(default=0.65, description="保留记忆的相关概率门槛")
    fact_signal_threshold: float = Field(default=0.70, description="写入客观事实属性标记的概率门槛")
    memory_confirm_threshold: float = Field(
        default=0.60, description="判定记忆为撞词/无关所需的确信概率；低于则保留"
    )
    memory_kind_min_confidence: float = Field(
        default=0.60, description="记忆分类的 confidence 下限；低于则保留"
    )
    fact_kind_min_confidence: float = Field(
        default=0.60, description="事实类别的 confidence 下限；低于则只写通用标记"
    )
    max_messages: int = Field(default=12, description="送入 Jev 的最近消息上限")
    max_message_chars: int = Field(default=1200, description="单条消息字符上限")
    max_total_chars: int = Field(default=8000, description="聊天窗口总字符上限")
    max_memories: int = Field(default=8, description="单轮记忆候选上限")
    max_memory_chars: int = Field(default=1200, description="单条记忆字符上限")
    cache_ttl_s: float = Field(default=120.0, description="相同窗口判断缓存秒数")
    breaker_failure_threshold: int = Field(default=3, description="连续失败达到该次数后暂停调用 Jev")
    breaker_cooldown_s: float = Field(default=60.0, description="熔断暂停秒数，到期后放行一次探测")


class JevPreprocessorConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    preprocessor: PreprocessorSectionConfig = Field(default_factory=PreprocessorSectionConfig)


class JevPreprocessorPlugin(MaiBotPlugin):
    """只修改 Planner 的 items；不接触 reply 工具参数或 Replyer。"""

    config_model = JevPreprocessorConfig

    def __init__(self) -> None:
        super().__init__()
        self._http: httpx.AsyncClient | None = None
        self._client: Any = None  # TypeSafeClient or OpenAIDecisionsClient
        self._processor: Processor | None = None
        # 统计跨配置重载保留，否则热重载一次计数就归零，观测失去意义。
        self._stats = Stats()

    def _enabled(self) -> bool:
        try:
            return bool(self.config.plugin.enabled)
        except RuntimeError:
            return False

    def _settings(self) -> Settings:
        cfg = self.config.preprocessor
        return Settings(
            memory_relevance_threshold=max(0.0, min(1.0, float(cfg.memory_relevance_threshold))),
            fact_signal_threshold=max(0.0, min(1.0, float(cfg.fact_signal_threshold))),
            max_messages=max(1, min(30, int(cfg.max_messages))),
            max_message_chars=max(100, min(4000, int(cfg.max_message_chars))),
            max_total_chars=max(1000, min(30000, int(cfg.max_total_chars))),
            max_memories=max(1, min(20, int(cfg.max_memories))),
            max_memory_chars=max(100, min(4000, int(cfg.max_memory_chars))),
            timeout_s=max(0.2, min(2.0, float(cfg.timeout_s))),
            cache_ttl_s=max(0.0, min(1800.0, float(cfg.cache_ttl_s))),
            breaker_failure_threshold=max(1, min(50, int(cfg.breaker_failure_threshold))),
            breaker_cooldown_s=max(0.0, min(3600.0, float(cfg.breaker_cooldown_s))),
            memory_confirm_threshold=max(0.0, min(1.0, float(cfg.memory_confirm_threshold))),
            memory_kind_min_confidence=max(0.0, min(1.0, float(cfg.memory_kind_min_confidence))),
            fact_kind_min_confidence=max(0.0, min(1.0, float(cfg.fact_kind_min_confidence))),
        )

    def _stats_log_every(self) -> int:
        try:
            return max(0, int(self.config.plugin.stats_log_every_n_rounds))
        except RuntimeError:
            return 0

    def _maybe_log_stats(self) -> None:
        """按轮次输出单行计数摘要；只含计数与延迟，不含聊天正文。"""
        processor = self._processor
        if processor is None:
            return
        if not should_log_stats(processor.stats.rounds, self._stats_log_every()):
            return
        logger.info(processor.stats.render())

    def _configured_key(self) -> tuple[str, str, str]:
        try:
            cfg = self.config.preprocessor
            return (
                str(cfg.api_key or ""),
                str(cfg.key_file or ""),
                str(getattr(cfg, "provider", "") or DEFAULT_PROVIDER),
            )
        except RuntimeError:
            return "", "~/.typesafe_key", DEFAULT_PROVIDER

    async def _evaluate(self, state: Dict[str, Any], questions: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
        client = self._client
        if client is None:
            raise RuntimeError("client_not_ready")
        configured, key_file, provider_id = self._configured_key()
        api_key = await asyncio.to_thread(
            resolve_key, configured, key_file, provider_id
        )
        return await client.evaluate(api_key, state, questions)

    async def _rebuild_runtime(self) -> None:
        old_http = self._http
        self._http = httpx.AsyncClient()
        try:
            cfg = self.config.preprocessor
            provider_id = str(getattr(cfg, "provider", "") or DEFAULT_PROVIDER)
            api_url = str(cfg.api_url or "")  # empty → preset default
            model = str(cfg.model or "")
            timeout_s = max(0.2, min(2.0, float(cfg.timeout_s)))
            settings = self._settings()
        except RuntimeError:
            provider_id = DEFAULT_PROVIDER
            api_url = ""
            model = ""
            timeout_s = 1.5
            settings = Settings()
        self._client = make_client(
            http=self._http,
            provider_id=provider_id,
            api_url=api_url,
            model=model,
            timeout_s=timeout_s,
        )
        self._processor = Processor(settings, evaluate=self._evaluate, stats=self._stats)
        if old_http is not None:
            await old_http.aclose()

    async def on_load(self) -> None:
        await self._rebuild_runtime()
        logger.info(
            "Jev Preprocessor v%s 已加载: enabled=%s（仅处理 Planner 输入）",
            PLUGIN_VERSION,
            self._enabled(),
        )

    async def on_unload(self) -> None:
        if self._processor is not None:
            if self._processor.stats.rounds > 0:
                logger.info("%s（卸载前快照）", self._processor.stats.render())
            self._processor.clear()
        self._processor = None
        self._client = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        logger.info("Jev Preprocessor 已卸载")

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        if scope == "self":
            await self._rebuild_runtime()
            logger.info("Jev Preprocessor 配置已更新: version=%s enabled=%s", version, self._enabled())

    @HookHandler(
        "maisaka.planner.before_request",
        name="jev_preprocess_planner_context",
        description="过滤与当前话题无关的启发式记忆，并标记外部客观事实属性；不提供回复指导",
        mode=HookMode.BLOCKING,
        order=HookOrder.LATE,
        timeout_ms=2300,
        error_policy=ErrorPolicy.SKIP,
    )
    async def handle_planner_before_request(self, **kwargs: Any) -> Dict[str, Any]:
        processor = self._processor
        if processor is None:
            return {"action": "continue"}
        try:
            return await run_before_request(processor, enabled=self._enabled(), kwargs=kwargs)
        finally:
            self._maybe_log_stats()


def create_plugin() -> JevPreprocessorPlugin:
    return JevPreprocessorPlugin()


__all__ = ["PLUGIN_VERSION", "JevPreprocessorPlugin", "JevPreprocessorConfig", "create_plugin"]
