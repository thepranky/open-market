"""
Threshold screening engine.

Evaluates a deal's parameters against jurisdiction rules loaded from YAML,
returning a per-jurisdiction screening result with status, triggering test,
confidence, and gap-to-trigger for non-triggered conditions.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import yaml
from pydantic import ValidationError

from app.models.jurisdiction import JurisdictionRule, MetricType, PartyType, RelationshipType, ScopeType, ThresholdTest

# ---------------------------------------------------------------------------
# Deal intake model
# ---------------------------------------------------------------------------

@dataclass
class RevenueByScope:
    """Party revenues keyed by ScopeType string."""
    worldwide: Optional[float] = None
    domestic: Optional[float] = None
    eu_eea: Optional[float] = None
    uk: Optional[float] = None
    us: Optional[float] = None
    # Per-member-state revenues: {"DE": 1_200_000, "FR": 800_000, ...}
    by_country: dict[str, float] = field(default_factory=dict)

    def get(self, scope: str) -> Optional[float]:
        return getattr(self, scope, None)


@dataclass
class DealParameters:
    """Structured intake for a single transaction."""
    # Revenues in the deal's base currency (converted to each jurisdiction's currency externally)
    acquirer: RevenueByScope = field(default_factory=RevenueByScope)
    target: RevenueByScope = field(default_factory=RevenueByScope)

    # Separately provided total assets (used for revenue_or_assets metric)
    acquirer_assets: Optional[float] = None
    target_assets: Optional[float] = None

    deal_value: Optional[float] = None
    deal_currency: str = "EUR"

    # Transaction structure — used for scope pre-filtering
    deal_type: Optional[str] = None          # merger | share_acquisition | asset_acquisition | joint_venture | minority_stake
    pct_shares_acquired: Optional[float] = None   # 0–100
    post_closing_control: Optional[str] = None    # sole_control | joint_control | material_influence | no_control
    relationship_type: Optional[str] = None  # horizontal | vertical | conglomerate

    # Market shares (0.0–1.0) keyed by scope
    combined_market_share: dict[str, float] = field(default_factory=dict)
    acquirer_market_share: dict[str, float] = field(default_factory=dict)
    incremental_share: dict[str, float] = field(default_factory=dict)

    # Currency the revenues are denominated in; engine applies FX below
    revenue_currency: str = "EUR"

    # Exchange rates to the jurisdiction's currency (populated by caller if needed)
    fx_rates: dict[str, float] = field(default_factory=dict)   # e.g. {"GBP": 0.86, "USD": 1.08}


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class ScreeningStatus(str, Enum):
    triggered = "triggered"
    not_triggered = "not_triggered"
    unclear = "unclear"
    data_insufficient = "data_insufficient"
    pending_commencement = "pending_commencement"


@dataclass
class ConditionResult:
    condition_id: str
    met: Optional[bool]           # None = could not evaluate (missing data)
    actual_value: Optional[float]
    threshold_value: float
    gap: Optional[float]          # positive = how far below threshold; negative = exceeded by this much
    note: Optional[str] = None
    missing_data: Optional[str] = None   # human-readable: which field is missing


@dataclass
class TestResult:
    test_id: str
    fired: Optional[bool]         # None = data insufficient
    description: Optional[str] = None   # human-readable test description
    conditions: list[ConditionResult] = field(default_factory=list)
    excluded: bool = False
    exclusion_reason: Optional[str] = None


@dataclass
class LegalCitation:
    citation: str
    url: Optional[str] = None


@dataclass
class JurisdictionScreeningResult:
    jurisdiction_id: str
    jurisdiction_name: str
    status: ScreeningStatus
    triggered_by: list[str] = field(default_factory=list)   # test_ids
    confidence: str = "high"                                  # high | medium | low
    filing_type: Optional[str] = None                         # mandatory | voluntary
    suspensory: Optional[bool] = None
    test_results: list[TestResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    legal_basis: list[LegalCitation] = field(default_factory=list)
    authority_url: Optional[str] = None


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

_jurisdiction_cache: dict[str, JurisdictionRule] = {}


def load_jurisdiction(jurisdiction_id: str, data_dir: str) -> JurisdictionRule:
    if jurisdiction_id in _jurisdiction_cache:
        return _jurisdiction_cache[jurisdiction_id]

    path = os.path.join(data_dir, f"{jurisdiction_id}.yaml")
    with open(path) as f:
        raw = yaml.safe_load(f)

    rule = JurisdictionRule.model_validate(raw)
    _jurisdiction_cache[jurisdiction_id] = rule
    return rule


def load_all_jurisdictions(data_dir: str) -> list[JurisdictionRule]:
    rules = []
    for path in sorted(glob.glob(os.path.join(data_dir, "*.yaml"))):
        basename = os.path.basename(path)
        # Skip verification sidecars and underscore-prefixed config files.
        if basename.endswith(".verification.yaml"):
            continue
        name = basename.replace(".yaml", "")
        if name.startswith("_"):
            continue
        with open(path) as f:
            raw = yaml.safe_load(f)
        try:
            rules.append(JurisdictionRule.model_validate(raw))
        except ValidationError as e:
            raise ValueError(f"Invalid jurisdiction YAML at {path}: {e}") from e
    return rules


# ---------------------------------------------------------------------------
# Value resolution
# ---------------------------------------------------------------------------

def _resolve_value(
    deal: DealParameters,
    metric: MetricType,
    scope: ScopeType,
    party: PartyType,
    jur_currency: str,
) -> Optional[float]:
    """Return the deal parameter value for a given condition metric/scope/party.

    Returns None if the required data is not present in the deal parameters.
    Applies FX conversion from deal.revenue_currency to jur_currency using deal.fx_rates.
    """
    fx = deal.fx_rates.get(jur_currency, 1.0) if deal.revenue_currency != jur_currency else 1.0

    if metric == MetricType.deal_value:
        if deal.deal_value is None:
            return None
        deal_fx = deal.fx_rates.get(jur_currency, 1.0) if deal.deal_currency != jur_currency else 1.0
        return deal.deal_value * deal_fx

    if metric == MetricType.market_share:
        scope_key = scope.value
        if party == PartyType.combined:
            return deal.combined_market_share.get(scope_key)
        if party in (PartyType.acquirer_group, PartyType.each_party):
            return deal.acquirer_market_share.get(scope_key)
        return None

    if metric == MetricType.incremental_share:
        return deal.incremental_share.get(scope.value)

    if metric == MetricType.assets:
        if party in (PartyType.acquirer_group, PartyType.each_party):
            v = deal.acquirer_assets
            return v * fx if v is not None else None
        if party == PartyType.target_group:
            v = deal.target_assets
            return v * fx if v is not None else None
        if party == PartyType.combined:
            a = deal.acquirer_assets or 0
            t = deal.target_assets or 0
            return (a + t) * fx if (deal.acquirer_assets is not None or deal.target_assets is not None) else None
        if party == PartyType.either_party:
            vals = [v for v in [deal.acquirer_assets, deal.target_assets] if v is not None]
            return max(vals) * fx if vals else None
        return None

    if metric == MetricType.revenue_or_assets:
        # Larger of annual net sales or total assets (HSR-style metric).
        # For 'combined': sum of each party's individual max(rev, assets).
        if party == PartyType.acquirer_group:
            rev = deal.acquirer.get(scope.value)
            assets = deal.acquirer_assets
            candidates = [v for v in [rev, assets] if v is not None]
            return max(candidates) * fx if candidates else None
        if party == PartyType.target_group:
            rev = deal.target.get(scope.value)
            assets = deal.target_assets
            candidates = [v for v in [rev, assets] if v is not None]
            return max(candidates) * fx if candidates else None
        if party == PartyType.combined:
            a_rev = deal.acquirer.get(scope.value)
            t_rev = deal.target.get(scope.value)
            a_assets = deal.acquirer_assets
            t_assets = deal.target_assets
            a_candidates = [v for v in [a_rev, a_assets] if v is not None]
            t_candidates = [v for v in [t_rev, t_assets] if v is not None]
            if not a_candidates and not t_candidates:
                return None
            a_val = max(a_candidates) if a_candidates else 0
            t_val = max(t_candidates) if t_candidates else 0
            return (a_val + t_val) * fx
        if party in (PartyType.either_party,):
            # Max of either party's revenue_or_assets
            a_rev = deal.acquirer.get(scope.value)
            t_rev = deal.target.get(scope.value)
            a_assets = deal.acquirer_assets
            t_assets = deal.target_assets
            a_candidates = [v for v in [a_rev, a_assets] if v is not None]
            t_candidates = [v for v in [t_rev, t_assets] if v is not None]
            a_val = max(a_candidates) if a_candidates else None
            t_val = max(t_candidates) if t_candidates else None
            vals = [v for v in [a_val, t_val] if v is not None]
            return max(vals) * fx if vals else None
        return None

    if metric == MetricType.revenue:
        scope_str = scope.value
        if party == PartyType.combined:
            a = deal.acquirer.get(scope_str)
            t = deal.target.get(scope_str)
            if a is None and t is None:
                return None
            return ((a or 0) + (t or 0)) * fx

        if party == PartyType.acquirer_group:
            v = deal.acquirer.get(scope_str)
            return v * fx if v is not None else None

        if party == PartyType.target_group:
            v = deal.target.get(scope_str)
            return v * fx if v is not None else None

        if party == PartyType.either_party:
            # At least one party exceeds the threshold — use max(acquirer, target).
            # Pair with each_party (min) on the companion condition to test the "other" party.
            a = deal.acquirer.get(scope_str)
            t = deal.target.get(scope_str)
            vals = [v for v in [a, t] if v is not None]
            return max(vals) * fx if vals else None

        if party in (PartyType.each_of_at_least_two, PartyType.each_party):
            # Return the minimum of the two individual values (weakest link).
            # If the minimum meets the condition, BOTH parties meet it, which is the
            # correct test for "each of [at least two / all] parties".
            a = deal.acquirer.get(scope_str)
            t = deal.target.get(scope_str)
            if a is None or t is None:
                return None
            return min(a, t) * fx

    return None


def _resolve_count_qualifier_value(
    deal: DealParameters,
    metric: MetricType,
    party: PartyType,
    qualifier_count: int,
    country_set: str,
    jur_currency: str,
) -> Optional[float]:
    """
    For conditions with count qualifiers (e.g. 'in each of at least 3 Member States'),
    return the Nth-largest country value where N = qualifier_count.

    If we have at least N countries meeting the value, the condition can be evaluated.
    Returns the value at the Nth position (the weakest qualifying country).
    """
    fx = deal.fx_rates.get(jur_currency, 1.0) if deal.revenue_currency != jur_currency else 1.0

    if country_set == "eu_member_states":
        eu_ms = {
            "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI",
            "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
            "NL", "PL", "PT", "RO", "SE", "SI", "SK",
        }
        filter_fn = lambda c: c in eu_ms
    else:
        filter_fn = lambda c: True

    if metric == MetricType.revenue:
        if party == PartyType.combined:
            source = {
                c: ((deal.acquirer.by_country.get(c, 0) + deal.target.by_country.get(c, 0)) * fx)
                for c in set(deal.acquirer.by_country) | set(deal.target.by_country)
                if filter_fn(c)
            }
        elif party in (PartyType.each_of_at_least_two, PartyType.each_party):
            # For each country, return the minimum of the two parties (weakest link)
            countries = set(deal.acquirer.by_country) | set(deal.target.by_country)
            source = {
                c: min(
                    deal.acquirer.by_country.get(c, 0),
                    deal.target.by_country.get(c, 0),
                ) * fx
                for c in countries
                if filter_fn(c)
            }
        elif party == PartyType.acquirer_group:
            source = {c: v * fx for c, v in deal.acquirer.by_country.items() if filter_fn(c)}
        elif party == PartyType.target_group:
            source = {c: v * fx for c, v in deal.target.by_country.items() if filter_fn(c)}
        else:
            return None

        if not source:
            return None

        sorted_values = sorted(source.values(), reverse=True)
        if len(sorted_values) < qualifier_count:
            # Fewer countries than required — return the smallest available value
            # so the engine knows it's below the count requirement
            return sorted_values[-1] if sorted_values else None

        return sorted_values[qualifier_count - 1]

    return None


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

def _compare(actual: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return actual > threshold
    if operator == ">=":
        return actual >= threshold
    if operator == "<":
        return actual < threshold
    if operator == "<=":
        return actual <= threshold
    return False


def _evaluate_condition(
    deal: DealParameters,
    condition,
    jur_currency: str,
) -> ConditionResult:
    if condition.qualifier and condition.qualifier.type == "count_of_countries":
        actual = _resolve_count_qualifier_value(
            deal,
            condition.metric,
            condition.party,
            condition.qualifier.count,
            condition.qualifier.country_set,
            jur_currency,
        )
    else:
        actual = _resolve_value(deal, condition.metric, condition.scope, condition.party, jur_currency)

    if actual is None:
        # Build a human-readable explanation of what data is missing
        scope_label = condition.scope.value if hasattr(condition, "scope") else "?"
        metric_label = condition.metric.value if hasattr(condition, "metric") else "?"
        party_label = condition.party.value if hasattr(condition, "party") else "?"

        scope_readable = {
            "worldwide": "worldwide", "domestic": "in-country/domestic",
            "eu_eea": "EU/EEA", "uk": "UK", "us": "US",
        }.get(scope_label, scope_label)
        metric_readable = {
            "revenue": "revenue", "assets": "assets",
            "deal_value": "deal value", "revenue_or_assets": "revenue or assets",
            "market_share": "market share",
        }.get(metric_label, metric_label)
        party_readable = {
            "combined": "combined", "acquirer_group": "acquirer",
            "target_group": "target", "each_of_at_least_two": "each party",
            "each_party": "each party",
        }.get(party_label, party_label)

        missing = f"{party_readable} {scope_readable} {metric_readable}"
        return ConditionResult(
            condition_id=condition.condition_id,
            met=None,
            actual_value=None,
            threshold_value=condition.value,
            gap=None,
            missing_data=missing,
        )

    met = _compare(actual, condition.operator, condition.value)
    gap = condition.value - actual  # positive = below threshold

    return ConditionResult(
        condition_id=condition.condition_id,
        met=met,
        actual_value=actual,
        threshold_value=condition.value,
        gap=gap,
    )


# ---------------------------------------------------------------------------
# Test evaluation
# ---------------------------------------------------------------------------

def _evaluate_test(
    deal: DealParameters,
    test: ThresholdTest,
    jur_currency: str,
) -> TestResult:
    desc = test.description

    if test.status == "pending_commencement":
        return TestResult(test_id=test.test_id, fired=None, description=desc, excluded=False,
                          exclusion_reason="Test not yet in force — pending commencement order")

    condition_results = [
        _evaluate_condition(deal, c, jur_currency)
        for c in test.conditions
    ]

    # If any condition definitively fails (met=False), the AND-test cannot fire
    # regardless of missing data for other conditions.
    any_definitive_fail = any(r.met is False for r in condition_results)
    if any_definitive_fail:
        return TestResult(test_id=test.test_id, fired=False, description=desc, conditions=condition_results)

    data_missing = any(r.met is None for r in condition_results)

    if data_missing:
        return TestResult(test_id=test.test_id, fired=None, description=desc, conditions=condition_results)

    fired = all(r.met is True for r in condition_results)

    return TestResult(test_id=test.test_id, fired=fired, description=desc, conditions=condition_results)


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _confidence(test_results: list[TestResult], triggered_tests: list[TestResult]) -> str:
    """
    low    — a threshold is within 10% of being met (close call)
    medium — data was missing for some conditions
    high   — all data present and no threshold is close
    """
    if any(r.fired is None for r in test_results):
        return "medium"

    for t in triggered_tests:
        for c in t.conditions:
            if c.actual_value is not None and c.threshold_value > 0:
                ratio = abs(c.actual_value - c.threshold_value) / c.threshold_value
                if ratio < 0.10:
                    return "low"

    for t in [r for r in test_results if not r.fired]:
        for c in t.conditions:
            if c.met is False and c.actual_value is not None and c.threshold_value > 0:
                ratio = abs(c.threshold_value - c.actual_value) / c.threshold_value
                if ratio < 0.10:
                    return "low"

    return "high"


# ---------------------------------------------------------------------------
# Transaction-scope pre-filter
# ---------------------------------------------------------------------------

def _scope_pre_filter(
    deal: DealParameters,
    rule: JurisdictionRule,
) -> Optional[JurisdictionScreeningResult]:
    """Return an early not_triggered / unclear result if the transaction is clearly out of scope.

    Returns None if the transaction should proceed to threshold evaluation.
    Decision logic is driven entirely by YAML data (minority_thresholds block).
    """
    jid = rule.jurisdiction_id

    def _not_triggered(note: str, confidence: str = "high") -> JurisdictionScreeningResult:
        legal_basis = [
            LegalCitation(citation=lb.citation, url=str(lb.url) if lb.url else None)
            for lb in (rule.legal_basis or [])[:1]
        ]
        return JurisdictionScreeningResult(
            jurisdiction_id=jid,
            jurisdiction_name=rule.jurisdiction_name,
            status=ScreeningStatus.not_triggered,
            triggered_by=[],
            confidence=confidence,
            filing_type="mandatory" if rule.regime.mandatory else "voluntary",
            suspensory=rule.regime.suspensory,
            test_results=[],
            notes=[note],
            legal_basis=legal_basis,
            authority_url=str(rule.authority.url) if rule.authority and rule.authority.url else None,
        )

    # 1. Transaction type not in scope (e.g. minority_stake not listed as trigger event)
    if deal.deal_type and rule.scope and rule.scope.trigger_events:
        if deal.deal_type not in rule.scope.trigger_events:
            return _not_triggered(
                f"Transaction type '{deal.deal_type}' is not a notifiable trigger event in this jurisdiction "
                f"(covered: {', '.join(rule.scope.trigger_events)})."
            )

    # 2. Minority stake / no-control transactions: data-driven evaluation from YAML
    is_minority = (
        deal.deal_type == "minority_stake"
        or deal.post_closing_control == "no_control"
    )
    if is_minority and rule.minority_thresholds is not None:
        mt = rule.minority_thresholds
        return _evaluate_minority_thresholds(deal, rule, mt, _not_triggered)

    return None


def _relationship_matches(rule_rel: RelationshipType, deal_rel: Optional[str]) -> bool:
    """Return True if the YAML rule's relationship_type covers this deal's relationship."""
    if rule_rel == RelationshipType.any:
        return True
    if deal_rel is None:
        return True  # unknown relationship — assume applies (conservative)
    if rule_rel.value == deal_rel:
        return True
    if rule_rel == RelationshipType.non_horizontal and deal_rel in ("vertical", "conglomerate"):
        return True
    return False


def _evaluate_minority_thresholds(
    deal: DealParameters,
    rule: JurisdictionRule,
    mt,
    not_triggered_fn,
) -> Optional[JurisdictionScreeningResult]:
    """Evaluate minority_thresholds block. Returns not_triggered if clearly out of scope;
    None if the transaction should proceed to revenue threshold evaluation."""

    if not mt.applies:
        return not_triggered_fn(
            "This jurisdiction does not apply merger control to minority stakes that do not "
            "confer decisive influence or control. A purely passive minority acquisition is "
            "not a notifiable concentration."
        )

    if mt.standard == "any_acquisition":
        # SLC-style — any share acquisition may be reviewable; proceed to revenue tests
        return None

    if mt.standard == "control_based":
        if deal.post_closing_control == "no_control":
            return not_triggered_fn(
                "No control or decisive influence acquired; transaction does not constitute "
                "a notifiable concentration under this jurisdiction's control standard."
            )
        return None

    if mt.standard == "material_influence":
        # A minority with board representation or veto rights over strategic decisions
        # may still be caught. Without knowing the exact rights granted, we cannot
        # definitively clear — return None to let revenue tests run and flag uncertainty.
        if deal.post_closing_control == "no_control":
            return not_triggered_fn(
                "No material influence acquired; transaction does not meet this jurisdiction's "
                "control standard for notifiable concentrations.",
                confidence="medium",
            )
        return None

    if mt.standard == "percentage_based":
        if not mt.rules:
            # No rules defined yet — cannot evaluate; proceed conservatively
            return None

        pct = deal.pct_shares_acquired
        rel = deal.relationship_type

        # Check if any rule is triggered for the deal's relationship type
        for r in mt.rules:
            if not _relationship_matches(r.relationship_type, rel):
                continue
            if r.pct_threshold is None:
                # Any stake in this relationship type triggers
                return None
            if pct is None:
                # Percentage unknown — cannot clear
                return None
            op = r.operator
            if (op == ">=" and pct >= r.pct_threshold) or (op == ">" and pct > r.pct_threshold):
                return None  # threshold met — proceed to revenue tests

        # No rule triggered for this relationship type / percentage
        if pct is not None:
            relevant_rules = [r for r in mt.rules if _relationship_matches(r.relationship_type, rel)]
            if relevant_rules:
                thresholds = ", ".join(
                    f"{r.relationship_type.value} {r.operator}{r.pct_threshold}%"
                    for r in relevant_rules if r.pct_threshold is not None
                )
                return not_triggered_fn(
                    f"Acquisition of {pct:.1f}% does not meet the minority notification thresholds "
                    f"for this jurisdiction ({thresholds}). Filing not required solely on ownership percentage."
                )

        return not_triggered_fn(
            "Minority stake does not meet the notification thresholds for this jurisdiction."
        )

    # Unknown standard — proceed conservatively
    return None


# ---------------------------------------------------------------------------
# Main screening function
# ---------------------------------------------------------------------------

def screen_jurisdiction(
    deal: DealParameters,
    rule: JurisdictionRule,
) -> JurisdictionScreeningResult:
    """Screen a deal against a single jurisdiction's rules."""
    # Scope pre-filter: check transaction type / control before running revenue tests
    pre_filter = _scope_pre_filter(deal, rule)
    if pre_filter is not None:
        return pre_filter

    jur_currency = _infer_currency(rule)

    test_results: list[TestResult] = []
    for test in rule.threshold_tests:
        result = _evaluate_test(deal, test, jur_currency)
        test_results.append(result)

    triggered = [r for r in test_results if r.fired is True]
    data_insufficient = all(r.fired is None for r in test_results)

    if data_insufficient:
        status = ScreeningStatus.data_insufficient
    elif triggered:
        status = ScreeningStatus.triggered
    elif any(r.fired is None for r in test_results):
        status = ScreeningStatus.unclear
    else:
        status = ScreeningStatus.not_triggered

    confidence = _confidence(test_results, triggered)

    legal_basis = [
        LegalCitation(citation=lb.citation, url=str(lb.url) if lb.url else None)
        for lb in (rule.legal_basis or [])
    ]

    return JurisdictionScreeningResult(
        jurisdiction_id=rule.jurisdiction_id,
        jurisdiction_name=rule.jurisdiction_name,
        status=status,
        triggered_by=[r.test_id for r in triggered],
        confidence=confidence,
        filing_type="mandatory" if rule.regime.mandatory else "voluntary",
        suspensory=rule.regime.suspensory,
        test_results=test_results,
        notes=rule.notes,
        legal_basis=legal_basis,
        authority_url=str(rule.authority.url) if rule.authority and rule.authority.url else None,
    )


def screen_all(
    deal: DealParameters,
    rules: list[JurisdictionRule],
) -> list[JurisdictionScreeningResult]:
    """Screen a deal against all loaded jurisdiction rules."""
    return [screen_jurisdiction(deal, rule) for rule in rules]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_currency(rule: JurisdictionRule) -> str:
    """Infer the jurisdiction's primary currency from its threshold conditions."""
    for test in rule.threshold_tests:
        for condition in test.conditions:
            if condition.currency:
                return condition.currency
    return "EUR"
