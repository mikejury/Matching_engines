from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from itertools import combinations
from math import inf
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml
from pydantic import BaseModel, Field, model_validator


# ============================================================
# Lotus Core
#
# Standalone matching kernel for Tribed VYB.
#
# Design goal:
#   Data goes in -> evaluations and groups come out.
#
# This module has no database dependency. It is intended to be
# portable across simulation and production integration layers.
# Any storage, scheduling, locking, or side effects should live
# outside this file.
# ============================================================


# ------------------------------------------------------------
# Enums
# ------------------------------------------------------------


class Environment(str, Enum):
    SIMULATION = "simulation"
    PRODUCTION = "production"


class ConfigStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class FriendshipAcceptedMode(str, Enum):
    RECIPROCAL_REQUIRED = "reciprocal_required"
    SINGLE_EDGE_ALLOWED = "single_edge_allowed"


class MutedEdgeBehavior(str, Enum):
    NO_BONUS = "no_bonus"
    SOFT_PENALTY = "soft_penalty"
    IGNORE = "ignore"


class DegradedTravelBehavior(str, Enum):
    EXCLUDE = "exclude"
    PENALTY = "penalty"
    NEUTRAL_WITH_FLAG = "neutral_with_flag"


class SeedStrategy(str, Enum):
    SCARCITY_FIRST = "scarcity_first"
    HIGHEST_COMPATIBILITY_FIRST = "highest_compatibility_first"
    RANDOM = "random"


class MatchRunStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class ExclusionReason(str, Enum):
    REQUEST_NOT_QUEUED = "request_not_queued"
    REQUEST_EXPIRED = "request_expired"
    PARTICIPANT_MISSING = "participant_missing"
    PARTICIPANT_MATCHING_DISABLED = "participant_matching_disabled"
    PARTICIPANT_SAFETY_EXCLUDED = "participant_safety_excluded"
    LIVE_LOCATION_MISSING = "live_location_missing"
    LIVE_LOCATION_EXPIRED = "live_location_expired"
    INVALID_GROUP_SIZE_BOUNDS = "invalid_group_size_bounds"


# ------------------------------------------------------------
# Config schema
# ------------------------------------------------------------


class MetadataConfig(BaseModel):
    created_by: str
    created_at: datetime | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class EligibilityConfig(BaseModel):
    require_live_location: bool = True
    live_location_max_age_seconds: int = 1800
    require_matching_enabled: bool = True
    require_request_status: str = "queued"
    allow_degraded_travel: bool = True
    reciprocal_friendship_required: bool = True
    cross_window_blending_enabled: bool = False
    exclude_expired_live_location: bool = False
    allow_geohash_travel_fallback: bool = True


class WeightsConfig(BaseModel):
    compatibility: float = 0.40
    distance: float = 0.22
    energy: float = 0.18
    schedule: float = 0.05
    friend_graph: float = 0.10
    demographic: float = 0.05

    @model_validator(mode="after")
    def validate_non_negative(self) -> "WeightsConfig":
        for name, value in self.model_dump().items():
            if value < 0:
                raise ValueError(f"Weight '{name}' cannot be negative.")
        return self


class ThresholdsConfig(BaseModel):
    target_coverage: float = 0.95
    fallback_coverage_floor: float = 0.80
    min_avg_group_score: float = 0.72
    min_pair_score: float = 0.55
    absolute_min_group_score: float = 0.58
    max_travel_burden: float = 0.70
    max_group_travel_imbalance: float = 0.25
    hard_pair_score_floor: float = 0.40
    max_degraded_travel_ratio: float = 0.50

    @model_validator(mode="after")
    def validate_ranges(self) -> "ThresholdsConfig":
        for name, value in self.model_dump().items():
            if not 0 <= value <= 1:
                raise ValueError(f"Threshold '{name}' must be between 0 and 1.")
        return self


class OptimizerConfig(BaseModel):
    seed_strategy: SeedStrategy = SeedStrategy.SCARCITY_FIRST
    local_improvement_enabled: bool = True
    local_improvement_passes: int = 2
    target_group_size: int = 4
    min_group_size: int = 3
    max_group_size: int = 5
    weak_link_penalty_weight: float = 0.20
    travel_imbalance_penalty_weight: float = 0.10
    size_mismatch_penalty_weight: float = 0.08
    prefer_target_group_size: bool = True

    @model_validator(mode="after")
    def validate_group_bounds(self) -> "OptimizerConfig":
        if self.min_group_size <= 0:
            raise ValueError("min_group_size must be positive.")
        if self.min_group_size > self.target_group_size:
            raise ValueError("min_group_size cannot exceed target_group_size.")
        if self.target_group_size > self.max_group_size:
            raise ValueError("target_group_size cannot exceed max_group_size.")
        return self


class SelectionConfig(BaseModel):
    early_stop_enabled: bool = True
    require_best_cycle_selection: bool = True
    publish_partial_if_no_target_coverage: bool = True
    tie_break_order: list[str] = Field(
        default_factory=lambda: [
            "coverage_desc",
            "avg_group_score_desc",
            "fallback_depth_asc",
            "unmatched_count_asc",
        ]
    )


class FeaturesConfig(BaseModel):
    demographic_balance_enabled: bool = False
    familiarity_bonus_enabled: bool = True
    novelty_bonus_enabled: bool = True
    degraded_travel_penalty_enabled: bool = True
    mute_edge_soft_penalty_enabled: bool = False
    verbose_candidate_reason_logging: bool = True


class FriendshipRulesConfig(BaseModel):
    accepted_mode: FriendshipAcceptedMode = FriendshipAcceptedMode.RECIPROCAL_REQUIRED
    familiarity_bonus_strength: float = 0.08
    novelty_bonus_strength: float = 0.05
    muted_edge_behavior: MutedEdgeBehavior = MutedEdgeBehavior.NO_BONUS


class TravelRulesConfig(BaseModel):
    preferred_target_type: str = "vyb_request"
    require_non_expired_metrics: bool = True
    choose_most_recent_metric: bool = True
    degraded_travel_behavior: DegradedTravelBehavior = DegradedTravelBehavior.PENALTY
    degraded_travel_penalty: float = 0.10


class GroupRulesConfig(BaseModel):
    enforce_request_group_bounds: bool = True
    enforce_participant_group_bounds: bool = True
    invalid_if_effective_min_exceeds_max: bool = True
    balance_internal_cohesion: bool = True


class FallbackTierConfig(BaseModel):
    tier: int
    name: str
    description: str
    weight_overrides: dict[str, float] = Field(default_factory=dict)
    threshold_overrides: dict[str, float] = Field(default_factory=dict)
    feature_overrides: dict[str, bool] = Field(default_factory=dict)
    stop_on_accept: bool = True


class RuntimeConfig(BaseModel):
    max_cycles_per_run: int = 6
    max_runtime_ms: int = 5000
    fail_closed_on_invalid_config: bool = True
    persist_cycle_diagnostics: bool = True
    persist_rejected_candidate_reasons: bool = True


class SimulationMetadataConfig(BaseModel):
    scenario_name: str | None = None
    scenario_density_label: str | None = None
    scenario_notes: str | None = None
    synthetic_population_tag: str | None = None


class LotusConfig(BaseModel):
    profile_name: str
    profile_type: str
    algorithm_version: str
    ruleset_version: str
    environment: Environment
    status: ConfigStatus
    metadata: MetadataConfig
    eligibility: EligibilityConfig
    weights: WeightsConfig
    thresholds: ThresholdsConfig
    optimizer: OptimizerConfig
    selection: SelectionConfig
    features: FeaturesConfig
    friendship_rules: FriendshipRulesConfig
    travel_rules: TravelRulesConfig
    group_rules: GroupRulesConfig
    fallback_ladder: list[FallbackTierConfig]
    runtime: RuntimeConfig
    simulation: SimulationMetadataConfig | None = None

    @model_validator(mode="after")
    def validate_fallback_ladder(self) -> "LotusConfig":
        tiers = [tier.tier for tier in self.fallback_ladder]
        if not tiers or tiers[0] != 0:
            raise ValueError("Fallback ladder must start at tier 0.")
        if tiers != sorted(tiers):
            raise ValueError("Fallback ladder tiers must be sorted ascending.")
        return self


class LotusConfigLoader:
    @staticmethod
    def load_from_yaml_file(path: str | Path) -> LotusConfig:
        with Path(path).open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return LotusConfig.model_validate(data)


# ------------------------------------------------------------
# Input contracts
# ------------------------------------------------------------


class TraitScore(BaseModel):
    trait_key: str
    value: float
    confidence: float | None = None


class ParticipantRecord(BaseModel):
    participant_id: UUID
    matching_enabled: bool
    safety_state: str
    social_state: str | None = None
    availability_mode: str | None = None
    live_geohash: str | None = None
    live_location_updated_at: datetime | None = None
    participant_min_group_size: int | None = None
    participant_max_group_size: int | None = None
    energy_score: float | None = None
    demographic_fields: dict[str, Any] = Field(default_factory=dict)
    traits: list[TraitScore] = Field(default_factory=list)


class RequestRecord(BaseModel):
    request_id: int
    participant_id: UUID
    status: str
    time_option: Literal["today", "tomorrow", "day_after", "custom"]
    requested_at: datetime
    expires_at: datetime | None = None
    mood_tags: list[str] = Field(default_factory=list)
    request_group_min_size: int | None = None
    request_group_max_size: int | None = None


class TravelMetricRecord(BaseModel):
    participant_id: UUID
    request_id: int | None = None
    target_type: str
    travel_burden_score: float | None = None
    arrival_sync_score: float | None = None
    calculated_at: datetime | None = None
    expires_at: datetime | None = None


class FriendshipRecord(BaseModel):
    participant_id: UUID
    friend_participant_id: UUID
    friendship_status: Literal["pending", "accepted", "blocked", "muted"]


class LotusInput(BaseModel):
    requests: list[RequestRecord]
    participants: list[ParticipantRecord]
    travel_metrics: list[TravelMetricRecord] = Field(default_factory=list)
    friendships: list[FriendshipRecord] = Field(default_factory=list)
    run_label: str | None = None
    supplied_at: datetime | None = None


# ------------------------------------------------------------
# Output contracts
# ------------------------------------------------------------


@dataclass(slots=True)
class ExcludedRequest:
    request_id: int
    participant_id: UUID | None
    reasons: list[ExclusionReason]


@dataclass(slots=True)
class CompatibilityResult:
    score: float
    confidence: float
    personality_component: float
    vibe_component: float
    preference_component: float


@dataclass(slots=True)
class CandidatePair:
    left_request_id: int
    right_request_id: int
    left_participant_id: UUID
    right_participant_id: UUID
    compatibility_score: float
    compatibility_confidence: float
    distance_score: float
    energy_score: float
    schedule_score: float
    friend_graph_score: float
    demographic_score: float
    overall_score: float
    degraded_travel: bool = False
    rejected: bool = False
    rejection_reason: str | None = None


@dataclass(slots=True)
class GroupResult:
    group_index: int
    request_ids: list[int]
    participant_ids: list[UUID]
    pair_scores: list[float]
    average_pair_score: float
    weak_link_score: float
    group_score: float
    fallback_tier: int


@dataclass(slots=True)
class CycleResult:
    tier: int
    tier_name: str
    accepted: bool
    coverage: float
    matched_count: int
    unmatched_count: int
    average_group_score: float
    lowest_group_score: float | None
    groups: list[GroupResult] = field(default_factory=list)
    unmatched_request_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class LotusOutput:
    run_status: MatchRunStatus
    profile_name: str
    ruleset_version: str
    selected_tier: int | None
    selected_tier_name: str | None
    cycle_results: list[CycleResult]
    final_groups: list[GroupResult]
    candidate_pairs: list[CandidatePair]
    exclusions: list[ExcludedRequest]
    started_at: datetime
    completed_at: datetime


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def jaccard_overlap(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.5
    union = left | right
    if not union:
        return 0.5
    return len(left & right) / len(union)


# ------------------------------------------------------------
# Standalone engine
# ------------------------------------------------------------


class LotusCore:
    def __init__(self, config: LotusConfig) -> None:
        self.config = config

    def run(self, payload: LotusInput) -> LotusOutput:
        started_at = utcnow()
        participant_map = {p.participant_id: p for p in payload.participants}

        eligible, exclusions = self._resolve_eligibility(payload.requests, participant_map)
        if not eligible:
            return LotusOutput(
                run_status=MatchRunStatus.FAILED,
                profile_name=self.config.profile_name,
                ruleset_version=self.config.ruleset_version,
                selected_tier=None,
                selected_tier_name=None,
                cycle_results=[],
                final_groups=[],
                candidate_pairs=[],
                exclusions=exclusions,
                started_at=started_at,
                completed_at=utcnow(),
            )

        candidate_pairs_all: list[CandidatePair] = []
        cycle_results: list[CycleResult] = []
        accepted_cycles: list[CycleResult] = []

        for tier in self.config.fallback_ladder[: self.config.runtime.max_cycles_per_run]:
            pairs = self._build_candidate_pairs(
                eligible=eligible,
                travel_metrics=payload.travel_metrics,
                friendships=payload.friendships,
                tier=tier,
            )
            candidate_pairs_all.extend(pairs)

            groups = self._build_groups(eligible=eligible, pairs=pairs, tier=tier)
            cycle = self._evaluate_cycle(eligible=eligible, groups=groups, tier=tier)
            cycle_results.append(cycle)

            if cycle.accepted:
                accepted_cycles.append(cycle)
                if tier.stop_on_accept and self.config.selection.early_stop_enabled:
                    break

        selected = self._select_best_cycle(accepted_cycles, cycle_results)
        completed_at = utcnow()

        if selected is None:
            return LotusOutput(
                run_status=MatchRunStatus.FAILED,
                profile_name=self.config.profile_name,
                ruleset_version=self.config.ruleset_version,
                selected_tier=None,
                selected_tier_name=None,
                cycle_results=cycle_results,
                final_groups=[],
                candidate_pairs=candidate_pairs_all,
                exclusions=exclusions,
                started_at=started_at,
                completed_at=completed_at,
            )

        return LotusOutput(
            run_status=MatchRunStatus.COMPLETED,
            profile_name=self.config.profile_name,
            ruleset_version=self.config.ruleset_version,
            selected_tier=selected.tier,
            selected_tier_name=selected.tier_name,
            cycle_results=cycle_results,
            final_groups=selected.groups,
            candidate_pairs=candidate_pairs_all,
            exclusions=exclusions,
            started_at=started_at,
            completed_at=completed_at,
        )

    # --------------------------------------------------------
    # Eligibility
    # --------------------------------------------------------

    def _resolve_eligibility(
        self,
        requests: list[RequestRecord],
        participant_map: dict[UUID, ParticipantRecord],
    ) -> tuple[list[tuple[RequestRecord, ParticipantRecord]], list[ExcludedRequest]]:
        now = utcnow()
        eligible: list[tuple[RequestRecord, ParticipantRecord]] = []
        exclusions: list[ExcludedRequest] = []

        for request in requests:
            reasons: list[ExclusionReason] = []
            participant = participant_map.get(request.participant_id)

            if request.status != self.config.eligibility.require_request_status:
                reasons.append(ExclusionReason.REQUEST_NOT_QUEUED)

            if request.expires_at is not None and request.expires_at < now:
                reasons.append(ExclusionReason.REQUEST_EXPIRED)

            if participant is None:
                reasons.append(ExclusionReason.PARTICIPANT_MISSING)
            else:
                if self.config.eligibility.require_matching_enabled and not participant.matching_enabled:
                    reasons.append(ExclusionReason.PARTICIPANT_MATCHING_DISABLED)

                if participant.safety_state not in {"clear", "ok", "eligible"}:
                    reasons.append(ExclusionReason.PARTICIPANT_SAFETY_EXCLUDED)

                if self.config.eligibility.require_live_location:
                    if not participant.live_geohash or participant.live_location_updated_at is None:
                        reasons.append(ExclusionReason.LIVE_LOCATION_MISSING)
                    else:
                        age_seconds = (now - participant.live_location_updated_at).total_seconds()
                        if age_seconds > self.config.eligibility.live_location_max_age_seconds:
                            if self.config.eligibility.exclude_expired_live_location:
                                reasons.append(ExclusionReason.LIVE_LOCATION_EXPIRED)

                effective_min = max(
                    value
                    for value in [
                        participant.participant_min_group_size,
                        request.request_group_min_size,
                        self.config.optimizer.min_group_size,
                    ]
                    if value is not None
                )
                effective_max = min(
                    value
                    for value in [
                        participant.participant_max_group_size,
                        request.request_group_max_size,
                        self.config.optimizer.max_group_size,
                    ]
                    if value is not None
                )
                if effective_min > effective_max:
                    reasons.append(ExclusionReason.INVALID_GROUP_SIZE_BOUNDS)

            if reasons:
                exclusions.append(
                    ExcludedRequest(
                        request_id=request.request_id,
                        participant_id=request.participant_id,
                        reasons=reasons,
                    )
                )
            else:
                eligible.append((request, participant))

        return eligible, exclusions

    # --------------------------------------------------------
    # Pair building
    # --------------------------------------------------------

    def _build_candidate_pairs(
        self,
        eligible: list[tuple[RequestRecord, ParticipantRecord]],
        travel_metrics: list[TravelMetricRecord],
        friendships: list[FriendshipRecord],
        tier: FallbackTierConfig,
    ) -> list[CandidatePair]:
        thresholds = self._effective_thresholds(tier)
        weights = self._effective_weights(tier)

        travel_map = self._resolve_travel_metric_map(travel_metrics)
        accepted_edges, blocked_edges, muted_edges = self._resolve_friendship_edges(friendships)

        pairs: list[CandidatePair] = []

        for (left_request, left_participant), (right_request, right_participant) in combinations(eligible, 2):
            pair_key = (left_participant.participant_id, right_participant.participant_id)
            reverse_key = (right_participant.participant_id, left_participant.participant_id)

            if pair_key in blocked_edges or reverse_key in blocked_edges:
                pairs.append(
                    CandidatePair(
                        left_request_id=left_request.request_id,
                        right_request_id=right_request.request_id,
                        left_participant_id=left_participant.participant_id,
                        right_participant_id=right_participant.participant_id,
                        compatibility_score=0.0,
                        compatibility_confidence=0.0,
                        distance_score=0.0,
                        energy_score=0.0,
                        schedule_score=0.0,
                        friend_graph_score=0.0,
                        demographic_score=0.0,
                        overall_score=0.0,
                        rejected=True,
                        rejection_reason="blocked_edge",
                    )
                )
                continue

            compatibility = self._score_compatibility(
                left_participant,
                right_participant,
                left_request,
                right_request,
            )
            distance_score, degraded = self._score_distance(
                left_request.request_id,
                right_request.request_id,
                travel_map,
            )
            energy_score = self._score_energy(left_participant, right_participant)
            schedule_score = self._score_schedule(left_request, right_request)
            friend_graph_score = self._score_friend_graph(
                left_participant.participant_id,
                right_participant.participant_id,
                accepted_edges,
                muted_edges,
            )
            demographic_score = self._score_demographic(left_participant, right_participant)

            overall_score = (
                weights.compatibility * compatibility.score
                + weights.distance * distance_score
                + weights.energy * energy_score
                + weights.schedule * schedule_score
                + weights.friend_graph * friend_graph_score
                + weights.demographic * demographic_score
            )

            rejected = False
            rejection_reason = None
            if compatibility.score < thresholds.min_pair_score:
                rejected = True
                rejection_reason = "below_min_pair_score"
            if overall_score < thresholds.hard_pair_score_floor:
                rejected = True
                rejection_reason = "below_hard_pair_floor"

            pairs.append(
                CandidatePair(
                    left_request_id=left_request.request_id,
                    right_request_id=right_request.request_id,
                    left_participant_id=left_participant.participant_id,
                    right_participant_id=right_participant.participant_id,
                    compatibility_score=compatibility.score,
                    compatibility_confidence=compatibility.confidence,
                    distance_score=distance_score,
                    energy_score=energy_score,
                    schedule_score=schedule_score,
                    friend_graph_score=friend_graph_score,
                    demographic_score=demographic_score,
                    overall_score=overall_score,
                    degraded_travel=degraded,
                    rejected=rejected,
                    rejection_reason=rejection_reason,
                )
            )

        return pairs

    # --------------------------------------------------------
    # Compatibility scoring
    # --------------------------------------------------------

    def _score_compatibility(
        self,
        left_participant: ParticipantRecord,
        right_participant: ParticipantRecord,
        left_request: RequestRecord,
        right_request: RequestRecord,
    ) -> CompatibilityResult:
        personality_score, personality_conf = self._score_personality(left_participant, right_participant)
        vibe_score = self._score_vibe(left_participant, right_participant)
        preference_score = self._score_preferences(left_request, right_request)

        compatibility_score = clamp(
            0.60 * personality_score + 0.25 * vibe_score + 0.15 * preference_score,
            0.0,
            1.0,
        )

        request_signal_presence = 1.0 if (left_request.mood_tags or right_request.mood_tags) else 0.4
        confidence = clamp(
            0.70 * personality_conf + 0.20 * (1.0 if left_participant.energy_score is not None and right_participant.energy_score is not None else 0.5) + 0.10 * request_signal_presence,
            0.0,
            1.0,
        )

        return CompatibilityResult(
            score=compatibility_score,
            confidence=confidence,
            personality_component=personality_score,
            vibe_component=vibe_score,
            preference_component=preference_score,
        )

    def _score_personality(
        self,
        left: ParticipantRecord,
        right: ParticipantRecord,
    ) -> tuple[float, float]:
        left_map = {t.trait_key: t for t in left.traits}
        right_map = {t.trait_key: t for t in right.traits}
        overlap = sorted(set(left_map) & set(right_map))
        if not overlap:
            return 0.5, 0.2

        weighted_scores: list[float] = []
        weights: list[float] = []
        for key in overlap:
            left_trait = left_map[key]
            right_trait = right_map[key]
            similarity = 1.0 - abs(left_trait.value - right_trait.value)
            combined_confidence = average([
                left_trait.confidence if left_trait.confidence is not None else 0.5,
                right_trait.confidence if right_trait.confidence is not None else 0.5,
            ])
            weighted_scores.append(clamp(similarity, 0.0, 1.0) * combined_confidence)
            weights.append(combined_confidence)

        score = sum(weighted_scores) / sum(weights) if sum(weights) > 0 else 0.5
        coverage_confidence = clamp(len(overlap) / max(len(set(left_map) | set(right_map)), 1), 0.0, 1.0)
        confidence_strength = average(weights)
        confidence = clamp(0.6 * coverage_confidence + 0.4 * confidence_strength, 0.0, 1.0)
        return score, confidence

    def _score_vibe(self, left: ParticipantRecord, right: ParticipantRecord) -> float:
        if left.energy_score is not None and right.energy_score is not None:
            return clamp(1.0 - abs(left.energy_score - right.energy_score), 0.0, 1.0)

        if left.social_state and right.social_state:
            if left.social_state == right.social_state:
                return 1.0
            return 0.6

        return 0.5

    def _score_preferences(self, left: RequestRecord, right: RequestRecord) -> float:
        tag_score = jaccard_overlap(set(left.mood_tags), set(right.mood_tags))

        left_min = left.request_group_min_size or self.config.optimizer.min_group_size
        left_max = left.request_group_max_size or self.config.optimizer.max_group_size
        right_min = right.request_group_min_size or self.config.optimizer.min_group_size
        right_max = right.request_group_max_size or self.config.optimizer.max_group_size
        overlap_exists = max(left_min, right_min) <= min(left_max, right_max)
        size_score = 1.0 if overlap_exists else 0.0

        return clamp(0.75 * tag_score + 0.25 * size_score, 0.0, 1.0)

    def _score_distance(
        self,
        left_request_id: int,
        right_request_id: int,
        travel_map: dict[int, TravelMetricRecord],
    ) -> tuple[float, bool]:
        left_metric = travel_map.get(left_request_id)
        right_metric = travel_map.get(right_request_id)

        if left_metric is None or right_metric is None:
            if self.config.travel_rules.degraded_travel_behavior == DegradedTravelBehavior.EXCLUDE:
                return 0.0, True
            if self.config.travel_rules.degraded_travel_behavior == DegradedTravelBehavior.NEUTRAL_WITH_FLAG:
                return 0.5, True
            penalty = self.config.travel_rules.degraded_travel_penalty
            return clamp(1.0 - penalty, 0.0, 1.0), True

        left_burden = left_metric.travel_burden_score if left_metric.travel_burden_score is not None else 0.5
        right_burden = right_metric.travel_burden_score if right_metric.travel_burden_score is not None else 0.5
        return clamp(1.0 - average([left_burden, right_burden]), 0.0, 1.0), False

    def _score_energy(self, left: ParticipantRecord, right: ParticipantRecord) -> float:
        if left.energy_score is not None and right.energy_score is not None:
            return clamp(1.0 - abs(left.energy_score - right.energy_score), 0.0, 1.0)
        return 0.5

    def _score_schedule(self, left: RequestRecord, right: RequestRecord) -> float:
        return 1.0 if left.time_option == right.time_option else 0.0

    def _score_friend_graph(
        self,
        left_participant_id: UUID,
        right_participant_id: UUID,
        accepted_edges: set[tuple[UUID, UUID]],
        muted_edges: set[tuple[UUID, UUID]],
    ) -> float:
        pair = (left_participant_id, right_participant_id)
        reverse = (right_participant_id, left_participant_id)

        if pair in muted_edges or reverse in muted_edges:
            if self.config.friendship_rules.muted_edge_behavior == MutedEdgeBehavior.SOFT_PENALTY:
                return 0.4
            if self.config.friendship_rules.muted_edge_behavior == MutedEdgeBehavior.IGNORE:
                return 0.5
            return 0.5

        if pair in accepted_edges or reverse in accepted_edges:
            if self.config.features.familiarity_bonus_enabled:
                return clamp(0.5 + self.config.friendship_rules.familiarity_bonus_strength, 0.0, 1.0)
            return 0.5

        if self.config.features.novelty_bonus_enabled:
            return clamp(0.5 + self.config.friendship_rules.novelty_bonus_strength, 0.0, 1.0)
        return 0.5

    def _score_demographic(self, left: ParticipantRecord, right: ParticipantRecord) -> float:
        # Deliberately conservative. Demographics are a soft shaping term only.
        if not self.config.features.demographic_balance_enabled:
            return 0.5
        return 0.5

    # --------------------------------------------------------
    # Group builder
    # --------------------------------------------------------

    def _build_groups(
        self,
        eligible: list[tuple[RequestRecord, ParticipantRecord]],
        pairs: list[CandidatePair],
        tier: FallbackTierConfig,
    ) -> list[GroupResult]:
        request_lookup = {request.request_id: (request, participant) for request, participant in eligible}
        viable_pairs = [pair for pair in pairs if not pair.rejected]
        adjacency = self._build_adjacency(viable_pairs)

        unassigned = {request.request_id for request, _ in eligible}
        groups: list[GroupResult] = []
        group_index = 0

        while unassigned:
            seed_request_id = self._pick_seed(unassigned, adjacency)
            if seed_request_id is None:
                break

            seed_neighbors = [rid for rid in adjacency.get(seed_request_id, {}) if rid in unassigned]
            if not seed_neighbors:
                unassigned.remove(seed_request_id)
                continue

            group_request_ids = [seed_request_id]
            best_neighbor = max(
                seed_neighbors,
                key=lambda rid: adjacency[seed_request_id][rid].overall_score,
            )
            group_request_ids.append(best_neighbor)

            for candidate_request_id in list(unassigned):
                if candidate_request_id in group_request_ids:
                    continue
                if len(group_request_ids) >= self.config.optimizer.max_group_size:
                    break
                if self._can_add_to_group(candidate_request_id, group_request_ids, adjacency):
                    trial_members = group_request_ids + [candidate_request_id]
                    if self._group_size_preference_score(len(trial_members)) >= self._group_size_preference_score(len(group_request_ids)):
                        group_request_ids.append(candidate_request_id)

            if len(group_request_ids) < self.config.optimizer.min_group_size:
                for rid in group_request_ids:
                    if rid in unassigned:
                        unassigned.remove(rid)
                continue

            group = self._score_group(group_index, group_request_ids, request_lookup, adjacency, tier.tier)
            groups.append(group)

            for rid in group_request_ids:
                unassigned.discard(rid)
            group_index += 1

        if self.config.optimizer.local_improvement_enabled and groups:
            groups = self._local_improvement(groups, adjacency, request_lookup)

        return groups

    def _build_adjacency(self, viable_pairs: list[CandidatePair]) -> dict[int, dict[int, CandidatePair]]:
        adjacency: dict[int, dict[int, CandidatePair]] = {}
        for pair in viable_pairs:
            adjacency.setdefault(pair.left_request_id, {})[pair.right_request_id] = pair
            adjacency.setdefault(pair.right_request_id, {})[pair.left_request_id] = pair
        return adjacency

    def _pick_seed(self, unassigned: set[int], adjacency: dict[int, dict[int, CandidatePair]]) -> int | None:
        if not unassigned:
            return None

        if self.config.optimizer.seed_strategy == SeedStrategy.SCARCITY_FIRST:
            return min(unassigned, key=lambda rid: len([n for n in adjacency.get(rid, {}) if n in unassigned]))

        if self.config.optimizer.seed_strategy == SeedStrategy.HIGHEST_COMPATIBILITY_FIRST:
            best_request_id = None
            best_score = -inf
            for rid in unassigned:
                scores = [pair.overall_score for nid, pair in adjacency.get(rid, {}).items() if nid in unassigned]
                score = max(scores) if scores else -inf
                if score > best_score:
                    best_score = score
                    best_request_id = rid
            return best_request_id

        return next(iter(unassigned))

    def _can_add_to_group(
        self,
        candidate_request_id: int,
        existing_group_request_ids: list[int],
        adjacency: dict[int, dict[int, CandidatePair]],
    ) -> bool:
        for existing_request_id in existing_group_request_ids:
            pair = adjacency.get(candidate_request_id, {}).get(existing_request_id)
            if pair is None or pair.rejected:
                return False
        return True

    def _score_group(
        self,
        group_index: int,
        request_ids: list[int],
        request_lookup: dict[int, tuple[RequestRecord, ParticipantRecord]],
        adjacency: dict[int, dict[int, CandidatePair]],
        fallback_tier: int,
    ) -> GroupResult:
        pair_scores: list[float] = []
        travel_components: list[float] = []

        for left_id, right_id in combinations(request_ids, 2):
            pair = adjacency[left_id][right_id]
            pair_scores.append(pair.overall_score)
            travel_components.append(pair.distance_score)

        avg_pair = average(pair_scores)
        weak_link = min(pair_scores) if pair_scores else 0.0
        weak_link_penalty = self.config.optimizer.weak_link_penalty_weight * (1.0 - weak_link)
        travel_imbalance_penalty = 0.0
        if travel_components:
            travel_imbalance_penalty = self.config.optimizer.travel_imbalance_penalty_weight * (
                max(travel_components) - min(travel_components)
            )
        size_penalty = self.config.optimizer.size_mismatch_penalty_weight * (
            1.0 - self._group_size_preference_score(len(request_ids))
        )

        group_score = clamp(avg_pair - weak_link_penalty - travel_imbalance_penalty - size_penalty, 0.0, 1.0)
        participant_ids = [request_lookup[rid][1].participant_id for rid in request_ids]

        return GroupResult(
            group_index=group_index,
            request_ids=request_ids,
            participant_ids=participant_ids,
            pair_scores=pair_scores,
            average_pair_score=avg_pair,
            weak_link_score=weak_link,
            group_score=group_score,
            fallback_tier=fallback_tier,
        )

    def _group_size_preference_score(self, size: int) -> float:
        target = self.config.optimizer.target_group_size
        max_distance = max(target - self.config.optimizer.min_group_size, self.config.optimizer.max_group_size - target, 1)
        return clamp(1.0 - abs(size - target) / max_distance, 0.0, 1.0)

    def _local_improvement(
        self,
        groups: list[GroupResult],
        adjacency: dict[int, dict[int, CandidatePair]],
        request_lookup: dict[int, tuple[RequestRecord, ParticipantRecord]],
    ) -> list[GroupResult]:
        improved = groups[:]
        for _ in range(self.config.optimizer.local_improvement_passes):
            improved.sort(key=lambda g: g.group_score)
            changed = False
            for i in range(len(improved)):
                for j in range(i + 1, len(improved)):
                    g1 = improved[i]
                    g2 = improved[j]
                    candidate = self._try_swap(g1, g2, adjacency, request_lookup)
                    if candidate is not None:
                        improved[i], improved[j] = candidate
                        changed = True
                        break
                if changed:
                    break
            if not changed:
                break
        return improved

    def _try_swap(
        self,
        g1: GroupResult,
        g2: GroupResult,
        adjacency: dict[int, dict[int, CandidatePair]],
        request_lookup: dict[int, tuple[RequestRecord, ParticipantRecord]],
    ) -> tuple[GroupResult, GroupResult] | None:
        current_total = g1.group_score + g2.group_score
        best: tuple[GroupResult, GroupResult] | None = None
        best_total = current_total

        for r1 in g1.request_ids:
            for r2 in g2.request_ids:
                new_g1_ids = [r2 if rid == r1 else rid for rid in g1.request_ids]
                new_g2_ids = [r1 if rid == r2 else rid for rid in g2.request_ids]
                if not self._group_is_fully_connected(new_g1_ids, adjacency):
                    continue
                if not self._group_is_fully_connected(new_g2_ids, adjacency):
                    continue
                new_g1 = self._score_group(g1.group_index, new_g1_ids, request_lookup, adjacency, g1.fallback_tier)
                new_g2 = self._score_group(g2.group_index, new_g2_ids, request_lookup, adjacency, g2.fallback_tier)
                new_total = new_g1.group_score + new_g2.group_score
                if new_total > best_total:
                    best_total = new_total
                    best = (new_g1, new_g2)
        return best

    def _group_is_fully_connected(
        self,
        request_ids: list[int],
        adjacency: dict[int, dict[int, CandidatePair]],
    ) -> bool:
        for left_id, right_id in combinations(request_ids, 2):
            if right_id not in adjacency.get(left_id, {}):
                return False
        return True

    # --------------------------------------------------------
    # Cycle evaluation and selection
    # --------------------------------------------------------

    def _evaluate_cycle(
        self,
        eligible: list[tuple[RequestRecord, ParticipantRecord]],
        groups: list[GroupResult],
        tier: FallbackTierConfig,
    ) -> CycleResult:
        thresholds = self._effective_thresholds(tier)
        eligible_request_ids = {request.request_id for request, _ in eligible}
        matched_request_ids = {rid for group in groups for rid in group.request_ids}
        unmatched_request_ids = sorted(eligible_request_ids - matched_request_ids)

        matched_count = len(matched_request_ids)
        unmatched_count = len(unmatched_request_ids)
        coverage = matched_count / len(eligible_request_ids) if eligible_request_ids else 0.0
        average_group_score = average([group.group_score for group in groups])
        lowest_group_score = min([group.group_score for group in groups], default=None)

        accepted = (
            coverage >= thresholds.fallback_coverage_floor
            and average_group_score >= thresholds.min_avg_group_score
            and (lowest_group_score is None or lowest_group_score >= thresholds.absolute_min_group_score)
        )

        return CycleResult(
            tier=tier.tier,
            tier_name=tier.name,
            accepted=accepted,
            coverage=coverage,
            matched_count=matched_count,
            unmatched_count=unmatched_count,
            average_group_score=average_group_score,
            lowest_group_score=lowest_group_score,
            groups=groups,
            unmatched_request_ids=unmatched_request_ids,
        )

    def _select_best_cycle(
        self,
        accepted_cycles: list[CycleResult],
        cycle_results: list[CycleResult],
    ) -> CycleResult | None:
        candidates = accepted_cycles
        if not candidates and self.config.selection.publish_partial_if_no_target_coverage:
            candidates = cycle_results
        if not candidates:
            return None

        return max(
            candidates,
            key=lambda cycle: (
                cycle.coverage,
                cycle.average_group_score,
                -cycle.tier,
                -cycle.unmatched_count,
            ),
        )

    # --------------------------------------------------------
    # Internals
    # --------------------------------------------------------

    def _effective_weights(self, tier: FallbackTierConfig) -> WeightsConfig:
        data = self.config.weights.model_dump()
        data.update(tier.weight_overrides)
        return WeightsConfig.model_validate(data)

    def _effective_thresholds(self, tier: FallbackTierConfig) -> ThresholdsConfig:
        data = self.config.thresholds.model_dump()
        data.update(tier.threshold_overrides)
        return ThresholdsConfig.model_validate(data)

    def _resolve_travel_metric_map(self, metrics: list[TravelMetricRecord]) -> dict[int, TravelMetricRecord]:
        now = utcnow()
        selected: dict[int, TravelMetricRecord] = {}
        for metric in metrics:
            if metric.request_id is None:
                continue
            if self.config.travel_rules.require_non_expired_metrics and metric.expires_at is not None and metric.expires_at < now:
                continue
            existing = selected.get(metric.request_id)
            if existing is None:
                selected[metric.request_id] = metric
                continue
            if self.config.travel_rules.choose_most_recent_metric:
                current_time = metric.calculated_at or datetime.min.replace(tzinfo=timezone.utc)
                existing_time = existing.calculated_at or datetime.min.replace(tzinfo=timezone.utc)
                if current_time > existing_time:
                    selected[metric.request_id] = metric
        return selected

    def _resolve_friendship_edges(
        self,
        friendships: list[FriendshipRecord],
    ) -> tuple[set[tuple[UUID, UUID]], set[tuple[UUID, UUID]], set[tuple[UUID, UUID]]]:
        accepted_edges_raw = {
            (f.participant_id, f.friend_participant_id)
            for f in friendships
            if f.friendship_status == "accepted"
        }
        if self.config.friendship_rules.accepted_mode == FriendshipAcceptedMode.RECIPROCAL_REQUIRED:
            accepted_edges = {
                edge
                for edge in accepted_edges_raw
                if (edge[1], edge[0]) in accepted_edges_raw
            }
        else:
            accepted_edges = accepted_edges_raw

        blocked_edges = {
            (f.participant_id, f.friend_participant_id)
            for f in friendships
            if f.friendship_status == "blocked"
        }
        muted_edges = {
            (f.participant_id, f.friend_participant_id)
            for f in friendships
            if f.friendship_status == "muted"
        }
        return accepted_edges, blocked_edges, muted_edges


# ------------------------------------------------------------
# Simple convenience entry point
# ------------------------------------------------------------


def run_lotus(payload: LotusInput, config: LotusConfig) -> LotusOutput:
    """Standalone convenience wrapper."""
    engine = LotusCore(config=config)
    return engine.run(payload)
