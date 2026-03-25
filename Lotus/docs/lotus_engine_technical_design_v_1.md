# Lotus Engine Technical Design v1

## Status
Draft for review

## Purpose

Lotus is the **matching mechanism** for VYB. Its responsibility is to take a supplied pool of eligible participant requests and produce the best feasible set of groups under the active ruleset.

Lotus is **not** the higher-order scheduler or orchestrator. It does not decide when matching rounds should occur, which windows should be opened, or how many participants should be held back for later rounds. Those concerns belong to a future upstream orchestration layer.

This separation is intentional.

- **Scheduling / inclusion layer** decides *when to run*, *which requests to include*, and *what matching objective applies to the round*
- **Lotus** decides *how to match the supplied pool*

Lotus must therefore expose a clean interface that allows the orchestration layer to pass in a bounded request set, profile, and context, while Lotus remains deterministic, modular, and storage-resilient.

---

## Design Boundaries

### Lotus Owns
- validating and loading the supplied matching pool
- resolving required Layer 2 signals
- constructing candidates
- scoring participants and candidate groupings
- running progressive fallback / relaxation
- selecting the best accepted solution
- persisting match runs, candidates, groups, and members
- returning diagnostics and result metadata

### Lotus Does Not Own
- deciding which queued requests should be included in a round
- deciding whether a request should be deferred to a later round
- long-horizon scheduling optimization
- venue assignment logic beyond coarse-location compatibility inputs
- messaging, reminders, or downstream notifications
- post-match learning loops beyond telemetry persistence

### Upstream Future Layer Responsibilities
The future scheduling layer may later handle:
- round timing
- density-aware batching
- participant inclusion/exclusion before a run
- city- or event-specific round policy
- carry-forward of deferred requests
- round-level objective selection

Lotus should be built now so that this future layer can call it without requiring Lotus to be redesigned.

---

## Architectural Position

Lotus lives fully inside **Layer 2** and must not depend on Layer 1 identity tables or user-facing application logic.

It reads Layer 2 participant, state, presence, location, personality, friendship, request, and travel data, and writes Layer 2 match results.

This keeps the engine:
- modular
- privacy-aware
- refactor-resilient
- testable against synthetic data

---

## Core Engine Principle

Lotus begins with the strictest acceptable matching policy and only relaxes lower-priority constraints when necessary to achieve an acceptable balance of quality and coverage.

The engine should:
- protect hard constraints
- favor quality first
- widen flexibility gradually
- stop once an acceptable solution is found
- select the best accepted solution, not merely the last one

---

## Read/Write Contract

### Primary Read Tables
- `participants`
- `participant_state`
- `participant_presence`
- `participant_live_location`
- `personality_profiles`
- `personality_trait_scores`
- `participant_friendships`
- `vyb_requests`
- `travel_metrics`

### Primary Write Tables
- `vyb_match_runs`
- `vyb_match_candidates`
- `vyb_groups`
- `vyb_group_members`

### Secondary Observational Tables
Not required for core matching execution, but relevant to future refinement:
- `vyb_outcomes`
- `vyb_feedback`
- `personality_trait_history`

---

## Logical Input Contract

Lotus should not hardcode raw SQL column names throughout the scoring and optimization layers. Instead, it should operate on a logical input contract resolved through a data dictionary.

### Required Logical Fields

#### Request-Level
- request_id
- request_participant_id
- request_time_option
- request_status
- request_mood_tags
- request_group_min_size
- request_group_max_size
- request_requested_at
- request_expires_at

#### Participant-Level
- participant_id
- participant_status
- matching_enabled
- safety_state
- social_state
- availability_mode
- participant_min_group_size
- participant_max_group_size
- city_id or city-like scope identifier if available

#### Presence / Location-Level
- live_geohash
- live_location_expires_at
- coarse_location
- presence_state if present

#### Personality-Level
- overall_personality_confidence
- trait_scores map
- trait_confidence map

#### Social Graph-Level
- friendship edges
- block edges
- mute edges

#### Travel-Level
- distance_km
- travel_time_min
- travel_mode
- travel_burden_score
- arrival_sync_score
- travel_metric_expiry

---

## Data Dictionary Layer

Lotus should include a data dictionary resolver that maps logical engine fields to physical tables/columns.

### Why
- protects the engine from schema refactors
- allows migration across databases or views
- supports test doubles and synthetic datasets
- keeps optimization code independent from storage details

### Design
The dictionary should support:
- single-column mappings
- multi-table joins
- derived fields
- fallback field resolution

### Example Concept
```json
{
  "request_id": "public.vyb_requests.id",
  "request_time_option": "public.vyb_requests.time_option",
  "matching_enabled": "public.participants.matching_enabled",
  "social_state": "public.participant_state.social_state",
  "live_geohash": "public.participant_live_location.geohash_coarse",
  "trait_scores": "derived.personality_trait_map",
  "friendship_edges": "derived.accepted_friendships",
  "travel_burden_score": "public.travel_metrics.travel_burden_score"
}
```

The first implementation may keep this dictionary in code, but the design should allow migration to config or database-backed mapping later.

---

## Invocation Model

Lotus should be callable as a pure service module.

### Suggested Internal Interface
```python
run_lotus_match(
    request_ids: list[int],
    profile_name: str,
    context: dict | None = None,
    trigger_request_id: int | None = None,
) -> LotusRunResult
```

### Invocation Assumptions
- the request pool is supplied by the caller
- the caller has already decided these requests belong in the current round
- Lotus may validate and discard invalid or expired requests
- Lotus may return unmatched requests with reasons

This keeps Lotus compatible with both:
- direct trigger-based matching today
- scheduler-driven round matching later

---

## Eligibility Rules

Eligibility must be evaluated inside Lotus even if the upstream caller preselects requests.

A request is eligible for a Lotus run only if all required hard conditions pass.

### Mandatory Eligibility Conditions
- `vyb_requests.status = 'queued'`
- request is not expired, or expiry policy explicitly allows it
- participant is active/eligible in `participants`
- `matching_enabled = true`
- safety state allows matching
- live location is present and not expired, unless profile permits degraded geographic matching
- request group-size bounds are internally valid

### Recommended Additional Conditions
- participant social state is not in a do-not-match state
- availability mode is compatible with the supplied matching round
- participant is not globally blocked from VYB

### Exclusion Reasons Should Be Logged
Examples:
- request_expired
- request_not_queued
- participant_matching_disabled
- participant_safety_excluded
- live_location_missing
- live_location_expired
- invalid_group_size_bounds

---

## Friendship Interpretation Rules

`participant_friendships` is structurally directional. Lotus must normalize it into usable relationship semantics.

### Proposed Interpretation
- `blocked` in either direction = hard exclusion edge
- `muted` in either direction = no friendship bonus and optional soft separation penalty
- `accepted` = familiarity edge
- `pending` = ignored for positive scoring

### Reciprocity Rule
Unless the application guarantees mirrored friendship rows, Lotus should support one of two configurable modes:

#### Mode A: Reciprocal Required
Treat friendship as valid only when both directions are `accepted`.

#### Mode B: Single Accepted Edge Allowed
Treat a single `accepted` row as familiarity.

### Recommendation for v1
Use **reciprocal required** for familiarity bonus and **either-direction block** for hard exclusion.

---

## Travel Interpretation Rules

`travel_metrics` may contain multiple rows and multiple target types. Lotus must use a strict resolution rule.

### Proposed Resolution for VYB Matching
- use only non-expired metrics
- prefer `target_type = 'vyb_request'`
- when multiple valid rows exist, use the most recent `calculated_at`
- if no valid row exists, fall back to geohash heuristic if enabled
- if neither metric nor heuristic is available, mark travel scoring as degraded

### Travel Degraded Behavior
Configurable options:
- exclude candidate pair
- apply neutral distance score with penalty
- route pair into lower fallback acceptance only

### Recommendation for v1
Use **heuristic fallback** where possible and otherwise assign a degraded penalty rather than hard-failing immediately.

---

## Group Size Resolution Rules

Group size preferences may come from both participant state and request.

### Proposed Precedence
1. request-level min/max if supplied
2. participant-level min/max as defaults
3. profile default group size bounds as final fallback

### Effective Pair/Group Bounds
For any candidate grouping:
- effective minimum = max(all applicable mins)
- effective maximum = min(all applicable maxes)
- if effective minimum > effective maximum, the grouping is invalid

This rule is clean, predictable, and easy to log.

---

## Time Option Semantics

Lotus should treat time semantics as part of the supplied matching context rather than owning global scheduling behavior.

### Request Values
Current schema supports:
- `today`
- `tomorrow`
- `day_after`
- `custom`

### v1 Rule
Lotus only matches requests that are compatible with the current round context supplied by the caller.

Example:
- a `today` round should not automatically consume `tomorrow` requests unless the upstream caller intentionally included them and the active profile permits cross-window blending

### Recommendation
Make cross-window blending **disabled by default** in Lotus v1.

---

## Candidate Construction Model

Lotus should construct a candidate graph from the supplied eligible pool.

### Step 1: Pool Validation
Validate all supplied requests and collapse to eligible request nodes.

### Step 2: Hard Pair Filtering
For each possible pair, exclude if:
- hard friendship block exists
- incompatible group-size overlap exists
- time compatibility fails
- travel exceeds hard max threshold
- safety rule fails

### Step 3: Pair Scoring
Score remaining pair candidates across the active dimensions.

### Step 4: Group Assembly
Assemble groups from the pair graph using the optimizer.

### Candidate Persistence
Persist considered candidates in `vyb_match_candidates` at least for:
- shortlisted candidates
- selected candidates
- rejected candidates where rejection reason is useful

For performance, v1 may choose not to persist every mathematically possible pair if pool size grows.

---

## Scoring Model Execution

Lotus should separate:
- pairwise scoring
- group-level scoring
- cycle-level scoring

### Pairwise Score Dimensions
Based on current schema and model direction, v1 should support:
- compatibility score
- distance score
- energy alignment score
- schedule fit score
- social graph familiarity / novelty adjustment

### Suggested Normalized Pair Formula
```text
pair_score =
  w_compatibility * compatibility_score
+ w_distance * distance_score
+ w_energy * energy_alignment_score
+ w_schedule * schedule_fit_score
+ w_friend_graph * friend_graph_score
+ w_demographic * demographic_balance_proxy
```

All sub-scores should be normalized to [0, 1].

### Group-Level Score
A group score should be derived from:
- average pair score within group
- minimum pair floor within group
- size fit bonus
- travel fairness / burden penalty
- novelty or familiarity shaping

Suggested concept:
```text
group_score =
  avg_pair_score
- weak_link_penalty
+ size_fit_bonus
- travel_imbalance_penalty
+ familiarity_or_novelty_adjustment
```

### Cycle-Level Score
Used to compare fallback cycles:
```text
cycle_score =
  a * coverage
+ b * average_group_score
- c * fallback_depth_penalty
- d * fairness_penalty
- e * instability_penalty
```

---

## Personality Scoring Rules

The personality schema supports confidence-aware trait scoring. Lotus should use that rather than treating all traits equally.

### v1 Recommended Method
For overlapping trait keys between two participants:
- compute trait similarity as inverse normalized distance
- weight each trait by combined confidence
- optionally weight by trait importance in profile config

### Missing Trait Handling
Configurable options:
- ignore missing trait
- impute neutral value
- apply uncertainty penalty

### Recommendation for v1
Ignore missing traits but reduce final compatibility confidence when too many required traits are absent.

---

## Social Energy Alignment Rules

Use participant state signals where available. If social energy is a derived trait rather than explicit state, treat it as a configurable logical field.

### v1 Rule
- close energy alignment yields higher score
- mild mismatch allowed
- severe mismatch penalized but not always hard-excluded

This should remain profile-tunable.

---

## Demographic Balance

Demographic balance should be a **soft shaping factor**, not a dominant or unsafe rule.

### v1 Recommendation
- allow it as a low-weight bonus for balanced groups where such balancing is aligned with product goals
- do not use it to create hard exclusions unless legally and ethically reviewed
- make the feature easy to disable in config

---

## Optimizer Strategy

Lotus needs a practical v1 optimizer that is explainable and stable.

### Recommended v1 Approach
Use a **greedy seeded group builder with local improvement pass**.

### Why
- easier to implement and debug
- deterministic enough for production
- fast enough for early low-density conditions
- compatible with future replacement by stronger optimization methods

### Proposed Flow
1. rank seed requests by scarcity / compatibility opportunity
2. create tentative groups around strongest available seeds
3. add members who improve group score and satisfy bounds
4. stop when group reaches effective size target or no improving members remain
5. run a local improvement pass to swap or reassign borderline participants
6. publish only groups passing minimum quality floor

### Future Upgrade Paths
- beam search
- graph clustering
- CP-SAT / ILP offline evaluator
- hybrid heuristic + search refinement

---

## Fallback / Relaxation Ladder

Lotus should implement bounded progressive relaxation.

### Design Rule
Only relax soft constraints and soft thresholds. Never relax hard safety or block constraints.

### Suggested v1 Ladder

#### Tier 0: Ideal
- default weights
- strict compatibility floor
- default travel threshold
- standard group size bounds
- no degraded travel scoring preference

#### Tier 1: Light Preference Relaxation
- slightly reduce low-priority preference weights
- allow softer novelty/familiarity shaping

#### Tier 2: Travel Flexibility
- widen travel threshold modestly
- reduce distance penalty weight slightly
- allow more heuristic travel fallback

#### Tier 3: Compatibility Softening
- lower minimum compatibility floor slightly
- widen acceptable social-energy mismatch band

#### Tier 4: Group Shape Flexibility
- allow broader target size tolerance
- permit more asymmetric but still acceptable groups

#### Tier 5: Last Acceptable State
- bounded low-priority relaxation only
- still enforce hard exclusion and absolute quality floor

### Stop Conditions
Stop if:
- accepted solution found and early-stop policy allows it
- max tier reached
- request pool exhausted
- caller imposes hard runtime cap

---

## Acceptance Framework

A cycle result is accepted only if it satisfies both coverage and quality requirements.

### Required Acceptance Checks
- hard constraint violations = 0
- average group score >= configured minimum
- no published group below absolute weak-link floor
- coverage >= target coverage or fallback band

### Recommendation for v1
Use both:
- **target coverage**
- **minimum quality floor**

This avoids matching everyone into socially dubious soup.

---

## Best-Solution Selection

Lotus should not automatically publish the last cycle that passes.

### Selection Rule
Among accepted cycles, select the cycle with the best cycle-level score.

### Tie-Break Preference
1. higher coverage
2. higher average group score
3. lower fallback depth
4. lower fairness penalty
5. lower unmatched count

---

## Run Lifecycle

### `vyb_match_runs`
A Lotus invocation creates one run record.

### Recommended Lifecycle
1. create run with `run_status = running`
2. validate supplied request set
3. compute cycle 0
4. persist cycle artifacts / candidate states
5. continue through fallback tiers as needed
6. select final solution
7. create groups and group members
8. update request statuses
9. mark run `completed` or `failed`

### Failure Conditions
- no valid eligible requests remain
- candidate graph empty after hard filtering
- optimizer internal failure
- write transaction failure

---

## Request Status Rules

### Recommended v1 Behavior
- `queued` -> eligible input state
- `matching` -> optional transient state while a run is in progress
- `matched` -> request assigned to a published group
- `expired` -> no longer eligible due to expiry
- `cancelled` -> excluded from consideration

### Recommendation
Lotus should set `matching` only if the surrounding service model requires request locking visibility. Otherwise, request locking can be handled transactionally without status churn.

---

## Concurrency and Idempotency

Lotus must protect against duplicate consumption of the same requests.

### v1 Concurrency Rule
A request must not participate in more than one active run at a time.

### Recommended Mechanisms
- transactional request locking when run begins
- `FOR UPDATE SKIP LOCKED`-style pool acquisition if the service architecture supports it
- verify request still eligible at commit time

### Idempotency
Lotus should accept an optional idempotency key from the caller for retry-safe invocation.

### Recommendation
The future orchestration layer should own round-level idempotency, but Lotus should support it cleanly.

---

## Persistence Rules

### `vyb_match_candidates`
Use to persist scored candidate information relevant to the final run and diagnostics.

Minimum v1 persistence:
- shortlisted candidates
- selected candidates
- rejected candidates with meaningful rejection reason

### `vyb_groups`
Persist one row per formed group, including:
- originating run
- time option
- scheduled time if supplied by caller/context
- coarse location if derived
- target group size
- formation confidence
- fallback level used

### `vyb_group_members`
Persist one row per assigned participant including:
- source request
- source candidate if applicable
- membership status
- invitation timestamp

---

## Scheduler Compatibility

Because a future scheduling layer will sit above Lotus, Lotus should support these caller-supplied controls from day one.

### Caller Context Inputs
- `round_id` or external correlation id
- `time_window_label`
- `profile_name`
- `city_scope`
- `max_group_count` if needed
- `allow_partial_publish`
- `cross_window_blending_enabled`

### Design Benefit
This allows Lotus to remain a matching kernel while the future scheduler becomes the conductor rather than forcing Lotus to play both violin and traffic police.

---

## Config Schema

Lotus should use a versioned config object with runtime loading.

### Top-Level Sections
```json
{
  "profile_name": "casual_social_v1",
  "algorithm_version": "lotus-v1",
  "eligibility": {},
  "weights": {},
  "thresholds": {},
  "fallback_ladder": [],
  "optimizer": {},
  "selection": {},
  "features": {}
}
```

### Suggested Sections

#### `eligibility`
- require_live_location
- allow_degraded_travel
- require_matching_enabled
- reciprocal_friendship_required

#### `weights`
- compatibility
- distance
- energy
- schedule
- friend_graph
- demographic

#### `thresholds`
- target_coverage
- min_avg_group_score
- min_pair_score
- absolute_min_group_score
- max_travel_burden

#### `fallback_ladder`
Array of tier configs containing per-tier overrides.

#### `optimizer`
- seed_strategy
- local_improvement_enabled
- max_group_size
- min_group_size

#### `selection`
- early_stop_enabled
- tie_break_order

#### `features`
- demographic_balance_enabled
- familiarity_bonus_enabled
- novelty_bonus_enabled
- degraded_travel_penalty_enabled

---

## Observability

Lotus should emit structured telemetry for both operations and research.

### Run-Level Metrics
- run id
- profile
- ruleset version
- algorithm version
- supplied request count
- eligible request count
- formed group count
- matched participant count
- unmatched participant count
- final fallback tier
- runtime duration

### Cycle-Level Metrics
- tier number
- accepted flag
- coverage
n- average group score
- weak-link floor violations
- travel degradation count
- hard filter rejection counts by reason

### Participant-Level Diagnostics
For unmatched requests, log reason codes such as:
- expired
- blocked_edge
- no_candidate_after_hard_filter
- insufficient_group_fit
- group_size_conflict
- quality_floor_failure

---

## Service Module Layout

### Suggested Package Structure
```text
services/api/app/matching/lotus/
  __init__.py
  service.py
  contracts.py
  config.py
  dictionary.py
  eligibility.py
  loaders.py
  friendships.py
  travel.py
  scoring.py
  candidates.py
  optimizer.py
  fallback.py
  selector.py
  persistence.py
  diagnostics.py
  models.py
```

### Module Roles
- `service.py` orchestrates a single Lotus invocation
- `contracts.py` defines request/result models
- `dictionary.py` handles logical field resolution
- `eligibility.py` validates pool membership
- `loaders.py` fetches and normalizes Layer 2 inputs
- `friendships.py` resolves graph semantics
- `travel.py` resolves valid travel metrics and fallbacks
- `scoring.py` computes pair/group/cycle scores
- `candidates.py` builds candidate graph
- `optimizer.py` assembles groups
- `fallback.py` applies tier changes
- `selector.py` chooses final accepted solution
- `persistence.py` writes run, candidate, group, member state
- `diagnostics.py` structures telemetry and reason codes

---

## Execution Flow

```text
Caller supplies request IDs + profile + context
  -> Lotus validates and locks request pool
  -> Lotus loads normalized Layer 2 features
  -> Lotus resolves friendship and travel semantics
  -> Lotus builds candidate graph
  -> Lotus runs tier 0 scoring + optimization
  -> Lotus evaluates acceptance
  -> If needed, Lotus applies next fallback tier and reruns
  -> Lotus selects best accepted solution
  -> Lotus persists groups and member assignments
  -> Lotus returns diagnostics and run summary
```

---

## Pseudocode

```python
def run_lotus_match(request_ids, profile_name, context=None, trigger_request_id=None):
    config = load_profile_config(profile_name)
    run = create_match_run(trigger_request_id=trigger_request_id,
                           ruleset_version=config.ruleset_version,
                           algorithm_version=config.algorithm_version)

    locked_requests = lock_requests(request_ids)
    eligible_pool, exclusions = resolve_eligibility(locked_requests, config, context)
    persist_exclusions(run.id, exclusions)

    if not eligible_pool:
        fail_run(run.id, "no_eligible_requests")
        return build_empty_result(run.id, exclusions)

    features = load_normalized_features(eligible_pool, config)
    friendship_graph = resolve_friendship_graph(features, config)
    travel_state = resolve_travel_state(features, config)

    accepted_cycles = []
    cycle_results = []

    for tier in config.fallback_ladder:
        tier_features = apply_tier(features, travel_state, friendship_graph, tier)
        candidate_graph = build_candidate_graph(tier_features, config, tier)
        proposal = optimize_groups(candidate_graph, tier_features, config, tier)
        evaluation = evaluate_cycle(proposal, tier_features, config, tier)

        persist_cycle(run.id, evaluation)
        cycle_results.append(evaluation)

        if evaluation.accepted:
            accepted_cycles.append(evaluation)

        if should_stop(accepted_cycles, evaluation, config):
            break

    final_solution = select_best_solution(accepted_cycles, cycle_results, config)

    if final_solution is None:
        fail_run(run.id, "no_accepted_solution")
        return build_failed_result(run.id, cycle_results)

    publish_groups(run.id, final_solution, context)
    complete_run(run.id, final_solution)
    return build_success_result(run.id, final_solution, cycle_results)
```

---

## Implementation Phases

### Phase 1: Functional Core
- config loader
- request locking and eligibility
- feature loading
- friendship + travel resolution
- pair scoring
- greedy group builder
- persistence of runs/groups/members

### Phase 2: Fallback Intelligence
- full tier ladder
- candidate diagnostics
- best-solution selector
- structured rejection reasons

### Phase 3: Admin / Runtime Config
- DB-backed config versions
- activation and rollback
- admin preview / dry run

### Phase 4: Scheduler Integration
- external round context support
- round correlation ids
- inclusion-policy-aware invocation
- replay support for research and simulations

### Phase 5: Advanced Optimization
- stronger search methods
- fairness analytics
- simulation benchmarking
- post-event feedback-informed calibration

---

## Key Design Decisions Locked In

1. Lotus is the **matching kernel**, not the scheduler.
2. Lotus works on a **caller-supplied bounded pool**.
3. Lotus remains entirely within **Layer 2**.
4. Lotus uses a **data dictionary abstraction** to reduce schema brittleness.
5. Lotus uses **progressive bounded fallback tiers**.
6. Lotus uses **coverage + quality** acceptance, not coverage alone.
7. Lotus selects the **best accepted** solution, not just the last passing cycle.
8. Lotus v1 uses a **greedy seeded optimizer with local improvement**.
9. Friendship blocks are **hard exclusions**.
10. The future scheduling layer can later sit above Lotus without requiring a redesign.

---

## Open Review Questions

These are policy questions rather than architectural blockers.

1. Should accepted friendship require reciprocity in production v1?
2. Should missing live travel metrics penalize or exclude by default?
3. Should demographic balancing be enabled at launch or remain off initially?
4. Should Lotus mark requests as `matching` during active runs, or rely purely on transactional locking?
5. Should cross-window blending remain fully disabled in v1?
6. What exact numeric defaults should define each fallback tier?

---

## Formal Statement

**Lotus Engine v1 is Tribed/VYB’s modular Layer 2 matching kernel. It consumes a caller-supplied pool of eligible requests, resolves the required social, personality, location, and travel signals, constructs candidates, forms groups under a configurable scoring policy, and progressively relaxes lower-priority constraints through bounded fallback tiers until the best acceptable solution is found and persisted. A separate future orchestration layer will decide round timing and participant inclusion, while Lotus remains responsible only for the matching mechanism itself.**

