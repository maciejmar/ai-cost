"""
Katalog modeli i routing.

  resolve_plan(model, strategy, messages, tools) → RoutingPlan
    model konkretny  → [model, *equivalents]
    model "auto" / brak → strategia (nagłówek albo domyślna aplikacji);
                          "auto" ocenia złożoność promptu
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from .config import get_settings

STRATEGIES = ("auto", "cheap", "smart", "fast")
AUTO_MODEL_NAMES = {"", "auto", "gateway-auto", "aigateway-x"}


@dataclass(frozen=True)
class ModelSpec:
    name:           str
    provider:       str
    upstream_model: str
    drop_params:    tuple[str, ...] = ()
    equivalents:    tuple[str, ...] = ()


@dataclass
class Catalog:
    models:              dict[str, ModelSpec]
    aliases:             dict[str, str]
    strategies:          dict[str, list[str]]
    smart_threshold:     float
    balanced_threshold:  float
    soft_limit_strategy: str


@dataclass
class RoutingPlan:
    candidates:  list[ModelSpec]
    strategy:    str                    # faktycznie użyty tier
    requested:   str | None
    complexity:  float | None = None
    reasons:     list[str] = field(default_factory=list)


@lru_cache
def get_catalog() -> Catalog:
    raw = yaml.safe_load(get_settings().gateway_routing_path.read_text(encoding="utf-8"))
    models = {
        name: ModelSpec(
            name=name,
            provider=m["provider"],
            upstream_model=m.get("upstream_model", name),
            drop_params=tuple(m.get("drop_params", [])),
            equivalents=tuple(m.get("equivalents", [])),
        )
        for name, m in raw["models"].items()
    }
    auto = raw.get("auto", {})
    return Catalog(
        models=models,
        aliases=raw.get("aliases") or {},
        strategies=raw["strategies"],
        smart_threshold=float(auto.get("smart_threshold", 0.6)),
        balanced_threshold=float(auto.get("balanced_threshold", 0.3)),
        soft_limit_strategy=raw.get("soft_limit_strategy", "cheap"),
    )


# ─── Ocena złożoności ─────────────────────────────────────────────────────

_COMPLEX = re.compile(
    r"\b(analy[sz]e|architect\w*|design|prove|proof|debug|refactor\w*|optimi[sz]e|"
    r"step[- ]by[- ]step|reason\w*|trade-?offs?|compare|evaluate|strategy|plan|why|"
    r"przeanalizuj|analiz\w*|zaprojektuj|projekt\w*|udowodnij|zdebuguj|refaktor\w*|"
    r"zoptymalizuj|krok po kroku|porównaj|oceń|dlaczego|strategi\w*)\b",
    re.IGNORECASE,
)
_SIMPLE = re.compile(
    r"\b(extract|format|convert|translate|summari[sz]e|classify|rewrite|list|"
    r"fix typos?|tag|label|json|csv|"
    r"wyodrębnij|wyciągnij|sformatuj|przekonwertuj|przetłumacz|streść|podsumuj|"
    r"sklasyfikuj|przepisz|popraw literówki)\b",
    re.IGNORECASE,
)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def score_complexity(
    messages: list[dict],
    tools:    list | None = None,
    response_format: dict | None = None,
) -> tuple[float, list[str]]:
    """Heurystyka 0–1. Tanio i deterministycznie — bez dodatkowego wywołania LLM."""
    reasons: list[str] = []
    score = 0.2

    all_text = " ".join(_text_of(m.get("content")) for m in messages)
    last_user = next(
        (_text_of(m.get("content")) for m in reversed(messages) if m.get("role") == "user"),
        "",
    )

    # Długość kontekstu: 0 przy ~500 znakach, +0.3 przy ~50k
    length_bonus = min(max(math.log10(max(len(all_text), 1) / 500) * 0.15, 0), 0.3)
    if length_bonus > 0.05:
        reasons.append(f"long context (+{length_bonus:.2f})")
    score += length_bonus

    complex_hits = len(set(m.lower() for m in _COMPLEX.findall(last_user)))
    if complex_hits:
        bonus = min(complex_hits * 0.12, 0.4)
        reasons.append(f"reasoning keywords x{complex_hits} (+{bonus:.2f})")
        score += bonus

    simple_hits = len(set(m.lower() for m in _SIMPLE.findall(last_user)))
    if simple_hits:
        malus = min(simple_hits * 0.1, 0.3)
        reasons.append(f"simple-task keywords x{simple_hits} (-{malus:.2f})")
        score -= malus

    if "```" in last_user:
        reasons.append("code block (+0.15)")
        score += 0.15

    if tools:
        reasons.append("tool use (+0.15)")
        score += 0.15

    if len(messages) > 10:
        reasons.append("long conversation (+0.10)")
        score += 0.1

    if response_format and response_format.get("type") in ("json_object", "json_schema"):
        reasons.append("structured output (-0.05)")
        score -= 0.05

    return round(min(max(score, 0.0), 1.0), 3), reasons


# ─── Plan routingu ────────────────────────────────────────────────────────

def resolve_plan(
    *,
    model:           str | None,
    strategy:        str | None,
    messages:        list[dict],
    tools:           list | None = None,
    response_format: dict | None = None,
    force_strategy:  str | None = None,
) -> RoutingPlan:
    cat = get_catalog()
    requested = model
    model = cat.aliases.get(model, model) if model else model

    # Konkretny model → on + jego odpowiedniki (chyba że wymuszono tańszy tier)
    if model and model not in AUTO_MODEL_NAMES and not force_strategy:
        spec = cat.models.get(model)
        if spec is None:
            raise KeyError(model)
        chain = [spec] + [cat.models[e] for e in spec.equivalents if e in cat.models]
        return RoutingPlan(candidates=chain, strategy="explicit", requested=requested)

    tier = force_strategy or strategy or "auto"
    complexity = None
    reasons: list[str] = []
    if force_strategy:
        reasons.append(f"soft quota exceeded → {force_strategy}")

    if tier == "auto":
        complexity, reasons = score_complexity(messages, tools, response_format)
        if complexity >= cat.smart_threshold:
            tier = "smart"
        elif complexity >= cat.balanced_threshold:
            tier = "balanced"
        else:
            tier = "cheap"

    names = cat.strategies.get(tier)
    if not names:
        raise ValueError(f"Unknown strategy: {tier}")
    return RoutingPlan(
        candidates=[cat.models[n] for n in names if n in cat.models],
        strategy=tier,
        requested=requested,
        complexity=complexity,
        reasons=reasons,
    )
