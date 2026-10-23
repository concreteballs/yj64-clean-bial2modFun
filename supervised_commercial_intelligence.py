"""YJ-64 supervised commercial intelligence — conservative design core.

This module evaluates candidate strategies only. It does not perform payments,
trades, purchases, network calls, or real-world execution.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Iterable, Protocol


POLICY_VERSION = "yj64-supervised-commercial-intelligence/0.1"


class Decision(str, Enum):
    REJECT = "REJECT"
    NEED_EVIDENCE = "NEED_EVIDENCE"
    NEED_APPROVAL = "NEED_APPROVAL"
    READY = "READY"
    STOP = "STOP"


class ExecutionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    BLOCKED = "BLOCKED"
    APPROVED_NOT_EXECUTED = "APPROVED_NOT_EXECUTED"


@dataclass(frozen=True)
class EvidenceSource:
    source_id: str
    uri: str
    publisher: str
    retrieved_at: str
    claim_supported: str
    source_type: str
    independently_verified: bool = False


@dataclass(frozen=True)
class EvidenceReport:
    sources: tuple[EvidenceSource, ...] = ()
    critical_claims_verified: bool = False
    model_reported_quality: float = 0.0
    uncertainty: float = 1.0

    @property
    def verified_source_count(self) -> int:
        # This is a claimed status, not proof by itself. Production integration
        # must verify sources outside the proposing model's control.
        return sum(1 for source in self.sources if source.independently_verified)


@dataclass(frozen=True)
class MarketStrategy:
    strategy_id: str
    name: str
    category: str
    description: str
    startup_cost: float
    estimated_weekly_revenue: float
    estimated_weekly_costs: float
    estimated_hours_per_week: float
    time_to_first_revenue_days: int
    estimated_failure_probability: float
    estimated_worst_case_loss: float
    reversibility: float
    evidence: EvidenceReport
    proposer_model: str
    proposer_model_version: str
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class SafetyLimits:
    initial_tokens: float = 10.0
    protected_reserve: float = 5.0
    research_budget_per_cycle: float = 1.0
    max_experiment_budget: float = 2.0
    max_loss_per_experiment: float = 1.0
    require_user_approval: bool = True
    minimum_verified_sources: int = 2
    maximum_uncertainty: float = 0.5
    maximum_failure_probability: float = 0.35
    minimum_reversibility: float = 0.5


@dataclass(frozen=True)
class ReviewResult:
    decision: Decision
    reason: str
    score: float
    strategy_hash: str
    decision_id: str
    policy_version: str = POLICY_VERSION


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def canonical_json(value: Any) -> str:
    """Stable JSON representation for hashing structured strategy content."""
    def normalize(item: Any) -> Any:
        if hasattr(item, "__dataclass_fields__"):
            return normalize(asdict(item))
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, dict):
            return {str(k): normalize(v) for k, v in sorted(item.items(), key=lambda pair: str(pair[0]))}
        if isinstance(item, (list, tuple)):
            return [normalize(v) for v in item]
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("non-finite numeric value cannot be fingerprinted")
            return item
        return item
    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def strategy_fingerprint(strategy: MarketStrategy) -> str:
    return hashlib.sha256(canonical_json(strategy).encode("utf-8")).hexdigest()


@dataclass
class AuditRecord:
    timestamp_utc: str
    decision_id: str
    strategy_hash: str
    proposer_model: str
    proposer_model_version: str
    decision: str
    reason: str
    score: float
    policy_version: str
    requested_budget: float
    budget_before: float
    budget_after: float
    previous_record_hash: str
    record_hash: str = ""


class AuditTrail:
    """Hash-linked in-memory audit chain; not durable or tamper-proof storage."""
    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> AuditRecord:
        if self._records and not self.verify_chain():
            raise RuntimeError("audit chain integrity check failed")
        record.previous_record_hash = self._records[-1].record_hash if self._records else "GENESIS"
        record.record_hash = ""
        payload = asdict(record)
        record.record_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        self._records.append(record)
        return record

    def records(self) -> tuple[AuditRecord, ...]:
        # Return copies so callers cannot mutate stored records by reference.
        import copy
        return tuple(copy.deepcopy(record) for record in self._records)

    def verify_chain(self) -> bool:
        previous = "GENESIS"
        for record in self._records:
            if record.previous_record_hash != previous:
                return False
            payload = asdict(record)
            claimed = payload.pop("record_hash")
            expected = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
            if claimed != expected:
                return False
            previous = claimed
        return True


@dataclass
class LedgerEntry:
    timestamp_utc: str
    operation: str
    amount: float
    balance_after: float
    reserved_after: float
    reference: str


class TokenLedger:
    """Single accounting ledger for internal research tokens, not real money."""
    def __init__(self, initial_tokens: float, protected_reserve: float = 0.0) -> None:
        if not _finite_number(initial_tokens) or initial_tokens < 0:
            raise ValueError("initial_tokens must be finite and non-negative")
        if not _finite_number(protected_reserve) or not 0 <= protected_reserve <= initial_tokens:
            raise ValueError("protected_reserve must be within the initial balance")
        self.balance = float(initial_tokens)
        self.protected_reserve = float(protected_reserve)
        self.reserved = 0.0
        self._reservations: dict[str, float] = {}
        self.entries: list[LedgerEntry] = []

    @property
    def available(self) -> float:
        return self.balance - self.reserved - self.protected_reserve

    def _record(self, operation: str, amount: float, reference: str) -> None:
        self.entries.append(LedgerEntry(
            datetime.now(timezone.utc).isoformat(), operation, float(amount),
            self.balance, self.reserved, reference,
        ))

    def reserve(self, reference: str, amount: float) -> None:
        if not reference or reference in self._reservations:
            raise ValueError("reservation reference must be unique and non-empty")
        if not _finite_number(amount) or amount <= 0:
            raise ValueError("reservation amount must be finite and positive")
        if amount > self.available:
            raise ValueError("insufficient available tokens after protected reserve")
        self._reservations[reference] = float(amount)
        self.reserved += float(amount)
        self._record("reserve", amount, reference)

    def settle(self, reference: str, actual_cost: float) -> None:
        if reference not in self._reservations:
            raise ValueError("unknown reservation")
        if not _finite_number(actual_cost) or actual_cost < 0:
            raise ValueError("actual_cost must be finite and non-negative")
        reserved_amount = self._reservations[reference]
        if actual_cost > reserved_amount:
            raise ValueError("actual cost exceeds reservation")
        self.balance -= float(actual_cost)
        self.reserved -= reserved_amount
        del self._reservations[reference]
        self._record("settle", actual_cost, reference)

    def release(self, reference: str) -> None:
        if reference not in self._reservations:
            raise ValueError("unknown reservation")
        amount = self._reservations.pop(reference)
        self.reserved -= amount
        self._record("release", amount, reference)


class Validator(Protocol):
    def validate(self, strategy: MarketStrategy, limits: SafetyLimits) -> tuple[bool, str]: ...


class BudgetValidator:
    def validate(self, strategy: MarketStrategy, limits: SafetyLimits) -> tuple[bool, str]:
        numbers = (
            strategy.startup_cost, strategy.estimated_weekly_revenue,
            strategy.estimated_weekly_costs, strategy.estimated_hours_per_week,
            strategy.estimated_failure_probability, strategy.estimated_worst_case_loss,
            strategy.reversibility,
        )
        if not all(_finite_number(value) for value in numbers):
            return False, "financial and risk estimates must be finite numbers"
        if min(strategy.startup_cost, strategy.estimated_weekly_revenue,
               strategy.estimated_weekly_costs, strategy.estimated_hours_per_week,
               strategy.estimated_worst_case_loss) < 0:
            return False, "costs, revenue, hours, and loss cannot be negative"
        if not 0 <= strategy.estimated_failure_probability <= 1:
            return False, "failure probability must be in [0, 1]"
        if not 0 <= strategy.reversibility <= 1:
            return False, "reversibility must be in [0, 1]"
        if strategy.estimated_worst_case_loss > limits.max_loss_per_experiment:
            return False, "maximum loss limit exceeded"
        if strategy.startup_cost > limits.max_experiment_budget:
            return False, "startup cost exceeds experiment budget"
        if strategy.estimated_failure_probability > limits.maximum_failure_probability:
            return False, "failure probability exceeds policy limit"
        if strategy.reversibility < limits.minimum_reversibility:
            return False, "strategy reversibility is below policy minimum"
        if strategy.time_to_first_revenue_days < 0:
            return False, "time_to_first_revenue_days cannot be negative"
        return True, "budget and risk checks passed"


class EvidenceValidator:
    def validate(self, strategy: MarketStrategy, limits: SafetyLimits) -> tuple[bool, str]:
        evidence = strategy.evidence
        if not _finite_number(evidence.model_reported_quality) or not 0 <= evidence.model_reported_quality <= 1:
            return False, "model-reported evidence quality is invalid"
        if not _finite_number(evidence.uncertainty) or not 0 <= evidence.uncertainty <= 1:
            return False, "evidence uncertainty is invalid"
        if not evidence.critical_claims_verified:
            return False, "critical claims are not verified"
        if evidence.verified_source_count < limits.minimum_verified_sources:
            return False, "no verified sources or too few independently verified sources"
        source_ids = [source.source_id for source in evidence.sources]
        if len(source_ids) != len(set(source_ids)):
            return False, "duplicate evidence source identifiers"
        for source in evidence.sources:
            if not source.source_id or not source.uri.startswith(("https://", "http://")):
                return False, "evidence source is missing an identifier or valid URI"
            if not source.publisher or not source.claim_supported or not source.retrieved_at:
                return False, "evidence source provenance is incomplete"
        if evidence.uncertainty > limits.maximum_uncertainty:
            return False, "evidence uncertainty exceeds policy limit"
        return True, "evidence checks passed"


class CategoryValidator:
    def __init__(self, category: str) -> None:
        self.category = category

    def validate(self, strategy: MarketStrategy, limits: SafetyLimits) -> tuple[bool, str]:
        if strategy.category.strip().lower() != self.category:
            return False, "category validator mismatch"
        if self.category in {"crypto", "financial_markets"}:
            if strategy.estimated_worst_case_loss > limits.max_loss_per_experiment:
                return False, "financial-market loss limit exceeded"
        if self.category == "freelance" and strategy.estimated_hours_per_week <= 0:
            return False, "freelance strategy must estimate positive work hours"
        return True, "category checks passed"


class ContextAwareValidatorRouter:
    """Mandatory validators always run; category checks can only add restrictions."""
    def __init__(self, extra_validators: Iterable[Validator] = ()) -> None:
        self._mandatory: tuple[Validator, ...] = (BudgetValidator(), EvidenceValidator())
        self._category_validators: dict[str, tuple[Validator, ...]] = {
            "crypto": (CategoryValidator("crypto"),),
            "financial_markets": (CategoryValidator("financial_markets"),),
            "freelance": (CategoryValidator("freelance"),),
            "ecommerce": (CategoryValidator("ecommerce"),),
            "digital_products": (CategoryValidator("digital_products"),),
        }
        self._extra = tuple(extra_validators)

    def validate(self, strategy: MarketStrategy, limits: SafetyLimits) -> tuple[bool, str]:
        validators = list(self._mandatory)
        category = strategy.category.strip().lower()
        if category not in self._category_validators:
            return False, f"unknown strategy category requires review: {category or '(empty)'}"
        validators.extend(self._category_validators[category])
        validators.extend(self._extra)
        for validator in validators:
            passed, reason = validator.validate(strategy, limits)
            if not passed:
                return False, reason
        return True, "all validators passed"


class AdaptivePolicy:
    """May tighten uncertainty tolerance based on outcomes; never raises risk limits."""
    def __init__(self, limits: SafetyLimits) -> None:
        self.limits = limits
        self._trials: dict[str, int] = {}
        self._failures: dict[str, int] = {}

    def record_outcome(self, category: str, success: bool) -> None:
        key = category.strip().lower()
        self._trials[key] = self._trials.get(key, 0) + 1
        if not success:
            self._failures[key] = self._failures.get(key, 0) + 1

    def uncertainty_threshold(self, category: str) -> float:
        key = category.strip().lower()
        trials = self._trials.get(key, 0)
        failures = self._failures.get(key, 0)
        if trials >= 10 and failures / trials > 0.5:
            return max(0.1, self.limits.maximum_uncertainty * 0.75)
        return self.limits.maximum_uncertainty


class SynergyScorer:
    """Disabled by default; accepts measured gains rather than fixed multipliers."""
    def score(self, independently_verified_gain: float, enabled: bool = False) -> float:
        if not enabled or not _finite_number(independently_verified_gain):
            return 0.0
        return max(-1.0, min(1.0, float(independently_verified_gain)))


class CommercialAgent:
    """Produces a conservative ranking; it does not approve or execute."""
    def assess(self, strategy: MarketStrategy) -> tuple[float, str]:
        net_weekly = strategy.estimated_weekly_revenue - strategy.estimated_weekly_costs
        evidence_credit = min(1.0, max(0.0, strategy.evidence.model_reported_quality))
        if strategy.evidence.verified_source_count == 0:
            evidence_credit = min(evidence_credit, 0.25)
        risk_penalty = max(0.0, min(1.0, strategy.estimated_failure_probability))
        reversibility_credit = max(0.0, min(1.0, strategy.reversibility))
        score = net_weekly * 0.01 + evidence_credit * 0.4 + reversibility_credit * 0.2 - risk_penalty * 0.5
        return score, "ranking only; final decision belongs to supervisor"


class YJ64Supervisor:
    def __init__(
        self,
        limits: SafetyLimits,
        ledger: TokenLedger,
        validators: ContextAwareValidatorRouter,
        adaptive_policy: AdaptivePolicy,
        audit: AuditTrail,
    ) -> None:
        self.limits = limits
        self.ledger = ledger
        self.validators = validators
        self.adaptive_policy = adaptive_policy
        self.audit = audit
        self._rejection_streak = 0

    def review(self, strategy: MarketStrategy, requested_budget: float, score: float,
               user_approved: bool = False) -> ReviewResult:
        decision_id = hashlib.sha256(
            f"{datetime.now(timezone.utc).isoformat()}:{strategy.strategy_id}".encode()
        ).hexdigest()[:24]
        fingerprint = "UNAVAILABLE"
        decision, reason = Decision.STOP, "uninitialized fail-closed decision"
        budget_before = self.ledger.available
        try:
            fingerprint = strategy_fingerprint(strategy)
            if not _finite_number(requested_budget) or requested_budget <= 0:
                decision, reason = Decision.REJECT, "requested budget must be finite and positive"
            elif requested_budget > self.limits.max_experiment_budget:
                decision, reason = Decision.REJECT, "requested budget exceeds experiment budget"
            elif requested_budget > self.ledger.available:
                decision, reason = Decision.REJECT, "insufficient available tokens after protected reserve"
            else:
                valid, validation_reason = self.validators.validate(strategy, self.limits)
                if not valid:
                    if "evidence" in validation_reason or "source" in validation_reason or "claims" in validation_reason:
                        decision = Decision.NEED_EVIDENCE
                    else:
                        decision = Decision.REJECT
                    reason = validation_reason
                elif strategy.evidence.uncertainty > self.adaptive_policy.uncertainty_threshold(strategy.category):
                    decision, reason = Decision.NEED_EVIDENCE, "adaptive uncertainty threshold not met"
                elif self.limits.require_user_approval and not user_approved:
                    decision, reason = Decision.NEED_APPROVAL, "explicit user approval required"
                else:
                    decision, reason = Decision.READY, "Eligible for controlled test; not executed"
            if decision in (Decision.REJECT, Decision.NEED_EVIDENCE, Decision.STOP):
                self._rejection_streak += 1
            else:
                self._rejection_streak = 0
        except Exception as exc:
            decision, reason = Decision.STOP, f"fail-closed internal error: {type(exc).__name__}"
        finally:
            record = AuditRecord(
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                decision_id=decision_id,
                strategy_hash=fingerprint,
                proposer_model=strategy.proposer_model,
                proposer_model_version=strategy.proposer_model_version,
                decision=decision.value,
                reason=reason,
                score=float(score) if _finite_number(score) else 0.0,
                policy_version=POLICY_VERSION,
                requested_budget=float(requested_budget) if _finite_number(requested_budget) else 0.0,
                budget_before=budget_before,
                budget_after=self.ledger.available,
                previous_record_hash="",
            )
            self.audit.append(record)
        return ReviewResult(decision, reason, float(score) if _finite_number(score) else 0.0, fingerprint, decision_id)

    def next_analysis_action(self) -> str:
        if self._rejection_streak >= 3:
            return "stop broad search; report best safe candidate and missing evidence; do not execute or spend"
        return "continue bounded evidence gathering"


class YJ64ExecutionPipeline:
    """Evaluation gateway. A READY result is not execution or budget settlement."""
    def __init__(self, agent: CommercialAgent, supervisor: YJ64Supervisor, ledger: TokenLedger) -> None:
        if ledger is not supervisor.ledger:
            raise ValueError("pipeline and supervisor must share one authoritative ledger")
        self.agent = agent
        self.supervisor = supervisor
        self.ledger = ledger

    def evaluate(self, strategy: MarketStrategy, requested_budget: float,
                 user_approved: bool = False) -> dict[str, Any]:
        try:
            score, _ = self.agent.assess(strategy)
            result = self.supervisor.review(strategy, requested_budget, score, user_approved)
            return {
                "status": result.decision.value,
                "reason": result.reason,
                "score": result.score,
                "strategy_hash": result.strategy_hash,
                "decision_id": result.decision_id,
                "execution_status": ExecutionStatus.NOT_STARTED.value,
                "policy_version": result.policy_version,
            }
        except Exception as exc:
            return {
                "status": Decision.STOP.value,
                "reason": f"pipeline fail-closed error: {type(exc).__name__}",
                "execution_status": ExecutionStatus.BLOCKED.value,
                "policy_version": POLICY_VERSION,
            }


@dataclass(frozen=True)
class SandboxSummary:
    sample_count: int
    mean: float | None
    minimum: float | None
    maximum: float | None
    note: str = "descriptive statistics only; not a forecast or guarantee"


class SandboxTester:
    def summarize(self, observed_values: Iterable[float]) -> SandboxSummary:
        values = [float(value) for value in observed_values if _finite_number(value)]
        if not values:
            return SandboxSummary(0, None, None, None)
        return SandboxSummary(len(values), sum(values) / len(values), min(values), max(values))


class CalibrationGround:
    """Stores forecasts and outcomes for later out-of-sample calibration analysis."""
    def __init__(self) -> None:
        self._records: list[tuple[float, bool, float]] = []

    def record(self, predicted_success_probability: float, observed_success: bool,
               realized_net: float) -> None:
        if not _finite_number(predicted_success_probability) or not 0 <= predicted_success_probability <= 1:
            raise ValueError("predicted probability must be in [0, 1]")
        if not _finite_number(realized_net):
            raise ValueError("realized_net must be finite")
        self._records.append((float(predicted_success_probability), bool(observed_success), float(realized_net)))

    def brier_score(self) -> float | None:
        if not self._records:
            return None
        return sum((probability - float(outcome)) ** 2
                   for probability, outcome, _net in self._records) / len(self._records)

    def records(self) -> tuple[tuple[float, bool, float], ...]:
        return tuple(self._records)
