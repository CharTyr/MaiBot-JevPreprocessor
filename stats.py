"""运行统计：只记录计数与延迟，绝不记录聊天正文或凭据。"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Sequence

DEFAULT_MAX_LATENCY_SAMPLES = 500


def _percentile(ordered: List[float], fraction: float) -> float:
    """最近秩百分位：小样本下不插值，返回真实观测值。"""
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[min(index, len(ordered) - 1)]


def latency_summary(values: Sequence[float]) -> Dict[str, Optional[float]]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"count": 0, "p50": None, "p95": None, "max": None}
    return {
        "count": len(ordered),
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "max": ordered[-1],
    }


def should_log_stats(rounds: int, every: int) -> bool:
    """轮次闸门：只在非零轮次且命中周期时输出摘要。"""
    try:
        every_value = int(every)
        rounds_value = int(rounds)
    except (TypeError, ValueError):
        return False
    return every_value > 0 and rounds_value > 0 and rounds_value % every_value == 0


@dataclass
class Stats:
    """进程内累计计数；重启即归零，属于运维观测而非持久数据。"""

    max_latency_samples: int = DEFAULT_MAX_LATENCY_SAMPLES

    rounds: int = 0
    no_state: int = 0
    cache_hits: int = 0
    joins: int = 0
    upstream_calls: int = 0
    upstream_ok: int = 0
    upstream_fail: int = 0
    timeouts: int = 0
    breaker_open_events: int = 0
    breaker_skips: int = 0
    applied: int = 0
    unchanged: int = 0
    memories_dropped: int = 0
    blocks_dropped: int = 0
    memories_kept_same_entity: int = 0
    fact_markers: int = 0
    fact_categorized: int = 0

    _latency_samples: Deque[float] = field(default_factory=deque, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._latency_samples = deque(maxlen=max(1, int(self.max_latency_samples)))

    def record_latency(self, milliseconds: float) -> None:
        try:
            self._latency_samples.append(float(milliseconds))
        except (TypeError, ValueError):
            return

    @property
    def latency(self) -> Dict[str, Optional[float]]:
        return latency_summary(self._latency_samples)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "rounds": self.rounds,
            "no_state": self.no_state,
            "cache_hits": self.cache_hits,
            "joins": self.joins,
            "upstream_calls": self.upstream_calls,
            "upstream_ok": self.upstream_ok,
            "upstream_fail": self.upstream_fail,
            "timeouts": self.timeouts,
            "breaker_open_events": self.breaker_open_events,
            "breaker_skips": self.breaker_skips,
            "applied": self.applied,
            "unchanged": self.unchanged,
            "memories_dropped": self.memories_dropped,
            "blocks_dropped": self.blocks_dropped,
            "memories_kept_same_entity": self.memories_kept_same_entity,
            "fact_markers": self.fact_markers,
            "fact_categorized": self.fact_categorized,
            "latency": self.latency,
        }

    def render(self) -> str:
        """单行摘要，便于日志聚合；不含任何输入文本。"""
        latency = self.latency
        if latency["count"]:
            latency_part = (
                f"latency_ms[n={latency['count']} p50={latency['p50']:.0f} "
                f"p95={latency['p95']:.0f} max={latency['max']:.0f}]"
            )
        else:
            latency_part = "latency_ms[n=0]"
        return (
            f"Jev 前置统计 rounds={self.rounds} no_state={self.no_state} "
            f"cache_hit={self.cache_hits} joins={self.joins} "
            f"upstream_calls={self.upstream_calls} upstream_ok={self.upstream_ok} "
            f"upstream_fail={self.upstream_fail} timeout={self.timeouts} "
            f"breaker_open={self.breaker_open_events} breaker_skip={self.breaker_skips} "
            f"applied={self.applied} unchanged={self.unchanged} "
            f"memories_dropped={self.memories_dropped} blocks_dropped={self.blocks_dropped} "
            f"memories_kept_same_entity={self.memories_kept_same_entity} "
            f"fact_markers={self.fact_markers} fact_categorized={self.fact_categorized} {latency_part}"
        )

    def reset(self) -> None:
        self._latency_samples.clear()
        for name in (
            "rounds",
            "no_state",
            "cache_hits",
            "joins",
            "upstream_calls",
            "upstream_ok",
            "upstream_fail",
            "timeouts",
            "breaker_open_events",
            "breaker_skips",
            "applied",
            "unchanged",
            "memories_dropped",
            "blocks_dropped",
            "memories_kept_same_entity",
            "fact_markers",
            "fact_categorized",
        ):
            setattr(self, name, 0)
