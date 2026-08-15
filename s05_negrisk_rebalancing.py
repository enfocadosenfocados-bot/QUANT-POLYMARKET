"""S05 - Arbitraje multi-resultado por sobreprecio del canasto YES."""
from typing import List, Optional

from core_models import BaseStrategy, Market, Opportunity, Signal


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _token_id(token: dict) -> str:
    return str(token.get("token_id") or token.get("tokenId") or "")


class NegRiskRebalancing(BaseStrategy):
    name = "s05_negrisk_rebalancing"
    tier = "S"
    strategy_id = 5
    required_data = []

    MIN_OUTCOMES = 3
    MIN_OVERPRICE = 0.02  # Detecta cuando la suma de probabilidades > 1.02

    def scan(self, markets: List[Market]) -> List[Opportunity]:
        opportunities: List[Opportunity] = []
        for m in markets:
            priced_tokens = [t for t in m.tokens if _to_float(t.get("price")) > 0]
            if len(priced_tokens) >= self.MIN_OUTCOMES:
                total_yes = sum(_to_float(t.get("price")) for t in priced_tokens)
                if total_yes > 1.0 + self.MIN_OVERPRICE:
                    opportunities.append(Opportunity(
                        market_id=m.condition_id,
                        question=m.question,
                        market_price=total_yes,
                        category=m.category,
                        metadata={
                            "tokens": priced_tokens,
                            "total_yes": total_yes,
                            "overprice": total_yes - 1.0,
                        },
                    ))
        return opportunities

    def analyze(self, opportunity: Opportunity, **kwargs: object) -> Optional[Signal]:
        tokens = opportunity.metadata.get("tokens", [])
        overprice = _to_float(opportunity.metadata.get("overprice"))
        if overprice < self.MIN_OVERPRICE or not tokens:
            return None

        most_overpriced = max(tokens, key=lambda t: _to_float(t.get("price")))
        token_id = _token_id(most_overpriced)
        yes_price = _to_float(most_overpriced.get("price"))
        if not token_id or yes_price <= 0:
            return None

        fair_price = max(0.0, min(1.0, yes_price - (overprice / len(tokens))))
        return Signal(
            market_id=opportunity.market_id,
            token_id=token_id,
            side="buy",  # Comprar el lado infravalorado/NO o arbitrar el canasto completo
            estimated_prob=fair_price,
            market_price=yes_price,
            confidence=0.95,
            strategy_name=self.name,
            metadata={
                "overprice": overprice,
                "total_basket_price": opportunity.market_price,
                "recommendation": "BUY NO / REBALANCE YES BASKET",
                "outcome": most_overpriced.get("outcome", ""),
            },
        )