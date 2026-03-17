# Lotus Engine Blueprint

## Purpose

Lotus is Tribed/VYB’s adaptive matching engine for low-density and growing user populations. Its purpose is to maximize **high-quality group formation** while maintaining a strong **coverage rate** among users who have self-marked as eligible for matching.

Lotus begins with a strict, ideal matching pass and only relaxes lower-priority constraints when required. This allows the system to preserve match quality when supply is healthy, while still producing viable outcomes when user numbers are sparse.

The engine is designed to be:

- adaptive under low user counts
- configurable without redeploying the backend
- resilient to schema and database refactors
- observable and auditable for research and evaluation
- extensible to multiple matching contexts and policies

---

## Core Design Principles

1. **Begin with quality**  
   The first pass should represent the ideal match policy.

2. **Relax only when needed**  
   Constraints should loosen progressively and deliberately, not all at once.

3. **Protect hard boundaries**  
   Safety, legality, and explicit exclusion constraints should not be casually relaxed.

4. **Balance quality and coverage**  
   A system that matches everyone poorly is as bad as one that matches no one.

5. **Separate logic from storage**  
   Data access should be abstracted through a data dictionary so backend schema changes do not break the engine.

6. **Keep policy editable at runtime**  
   Admins should be able to tune weights, thresholds, and relaxation profiles live via Admin UI.

7. **Log every cycle**  
   Each rerun should produce diagnostics for audit, research, evaluation, and future model improvement.

---

## Strategic Value

Lotus directly addresses the early-stage cold-start problem of social matching platforms. In low-density environments, highly selective matching can produce poor coverage. In dense environments, overly relaxed matching can reduce user trust. Lotus solves this with a staged approach:

- strict when density allows it
- flexible when density demands it
- observable enough to learn from every cycle

This makes it suitable not only for production matching, but also for simulation, evaluation, A/B testing, and future model training.

---

## Definitions

### Eligible User
A user who has opted in, is available in the current matching window, and passes all pre-match eligibility checks.

### Matching Cycle
A single full run of the engine under one specific configuration state.

### Relaxation Tier
A predefined set of weight and/or threshold changes applied after a failed cycle.

### Coverage
The proportion of eligible users who are successfully assigned to a group.

### Match Quality
A score that reflects how well assigned groups satisfy compatibility, preference, and operational criteria.

### Accepted Solution
A cycle result that meets the minimum policy thresholds required for production use.

### Best Accepted Solution
The accepted cycle result that maximizes the engine’s final objective function, rather than merely being the last successful cycle.

---

## High-Level Engine Overview

Lotus operates in the following sequence:

1. Load current matching profile and policy config
2. Resolve eligible users for the current window
3. Load required signals through the data dictionary
4. Build candidate pools and compatibility graph
5. Run group optimization for the current cycle
6. Evaluate coverage, quality, fairness, and policy compliance
7. If the result is inadequate, apply the next relaxation tier
8. Repeat until an accepted solution is found or all tiers are exhausted
9. Select the best accepted solution
10. Persist assignments, diagnostics, and audit trail

---

## Matching Objectives

Lotus should optimize for multiple objectives at once.

### Primary Objectives

- maximize eligible-user coverage
- maximize average group quality
- minimize assignment of users to low-confidence or weak-fit groups

### Secondary Objectives

- minimize excessive travel or logistical burden
- maintain healthy group-size distribution
- preserve fairness across user segments
- maintain stability between similar cycles where practical
- encourage novelty or repeat-balance where configured

---

## Constraint Model

Lotus should separate constraints into distinct categories.

### 1. Hard Constraints
These are non-negotiable or only relaxable under tightly controlled policy.

Examples:
- availability overlap
- blocklist / do-not-match rules
- safety-related constraints
- legal age and policy requirements
- event capacity limits
- explicit exclusion preferences
- required city/zone boundaries where applicable

### 2. Soft Constraints
These influence match desirability and can be weighted or relaxed.

Examples:
- location distance
- vibe compatibility
- personality compatibility
- activity preference overlap
- social energy alignment
- language preference
- demographic balancing
- novelty versus familiarity
- attendance confidence

### 3. Optimization Preferences
These are not user-facing constraints but policy preferences used to improve final grouping behavior.

Examples:
- avoid over-concentrating highly social users in one group
- distribute experienced users across groups
- reserve some users for better later grouping if window policy allows
- preserve group-size consistency

---

## Weight Relaxation vs Threshold Relaxation

Lotus should support both.

### Weight Relaxation
A factor matters less in scoring.

Example:
- distance weight changes from 0.20 to 0.10

### Threshold Relaxation
A factor becomes less restrictive in candidate eligibility.

Example:
- preferred travel radius expands from 5 km to 8 km
- minimum compatibility floor drops from 0.75 to 0.68

### Why both are needed
Changing weights alone may not increase candidate availability if filters remain fixed. Changing thresholds alone may allow weak candidates without appropriate scoring balance. Lotus should therefore support a controlled combination of both.

---

## Relaxation Ladder

Lotus should not improvise relaxation dynamically at first. It should use predefined tiers.

### Example Relaxation Ladder

#### Tier 0: Ideal
- default weights
- default thresholds
- standard group sizes
- strict compatibility floor

#### Tier 1: Light Preference Softening
- relax lowest-priority preference weight
- widen optional activity overlap tolerance slightly

#### Tier 2: Light Radius Expansion
- widen distance threshold modestly
- reduce distance penalty weight slightly

#### Tier 3: Compatibility Tolerance Expansion
- lower minimum personality/vibe compatibility floor slightly
- keep hard safety and exclusion rules intact

#### Tier 4: Group Shape Flexibility
- allow broader group-size range
- permit slight asymmetry in ideal balancing rules

#### Tier 5: Strong Soft Constraint Relaxation
- further reduce low-priority preference weights
- widen candidate inclusion further

#### Tier 6: Last Acceptable State
- final bounded relaxation state before fallback behavior
- still governed by hard floors and safety limits

### Notes
- not all profiles need all tiers
- different product contexts can have different ladders
- every tier should be human-readable and explainable

---

## Example Matching Profiles

Lotus should support named policy profiles.

### Casual Social Profile
- high coverage priority
- moderate compatibility floor
- more aggressive relaxation allowed

### High-Intent Event Profile
- stronger quality priority
- limited relaxation
- higher group cohesion floor

### Travel Buddy Profile
- distance and schedule dominate
- compatibility important but secondary
- city and route constraints more central

### Safety-Sensitive Profile
- strict hard constraints
- very limited relaxation
- stronger review logging

### Experimental / Research Profile
- used in simulation or controlled test runs
- may log additional diagnostics
- may compare multiple objective functions

---

## Engine Modules

### 1. Eligibility Resolver
Responsible for identifying which users can participate in the current matching window.

Inputs:
- matching window
- user opt-in state
- availability
- safety / policy status
- city or event scope

Outputs:
- eligible user list
- exclusion reasons for ineligible users

### 2. Signal Loader
Loads all required user, context, and policy signals through the data dictionary abstraction.

Inputs:
- logical field requirements
- data dictionary mappings

Outputs:
- normalized feature objects for matching

### 3. Data Dictionary Resolver
Translates logical field names into physical storage locations.

Purpose:
- decouple engine logic from storage schema
- allow multi-database or refactored storage
- reduce brittleness during backend evolution

### 4. Candidate Graph Builder
Builds pairwise and/or groupwise compatibility relationships between eligible users.

Outputs may include:
- pair compatibility scores
- candidate edge list
- distance penalties
- exclusion edges
- groupability estimates

### 5. Compatibility Scorer
Produces normalized scores used by the optimizer.

Should support:
- modular score components
- explainable weight breakdowns
- profile-specific score functions

### 6. Group Optimizer
Constructs actual groups from the candidate space.

Possible future methods:
- greedy heuristic
- graph clustering
- constrained optimization
- beam search
- ILP or CP-SAT for research mode

Early production recommendation:
- use a practical heuristic method with strong logging
- reserve heavier optimization approaches for evaluation and offline testing

### 7. Relaxation Manager
Applies the predefined tier changes when a cycle fails acceptance.

Responsibilities:
- load next tier
- update active weights and thresholds
- ensure hard floors are not violated
- log what changed between cycles

### 8. Cycle Evaluator
Scores the outcome of each cycle against business and product requirements.

Evaluates:
- coverage
- average quality
- minimum quality floor violations
- fairness metrics
- distribution metrics
- instability signals
- policy compliance

### 9. Solution Selector
Chooses the best accepted cycle rather than blindly using the last cycle.

Responsibilities:
- compare accepted candidates
- apply final objective function
- select best tradeoff between coverage and quality

### 10. Assignment Publisher
Commits selected groups into production tables or queues.

Responsibilities:
- write final assignments
- preserve cycle metadata
- support downstream notifications

### 11. Audit Logger
Stores full cycle telemetry for research and debugging.

Should capture:
- cycle number
- profile used
- thresholds and weights
- matched counts
- unmatched reasons
- quality distributions
- fairness diagnostics
- selected solution flag

### 12. Admin Config Service
Supports live-editable policy control without backend restart.

Responsibilities:
- validate config updates
- version configs
- publish changes safely
- support rollback

---

## Data Architecture

Lotus should be storage-agnostic at the engine level.

### Logical Data Categories
- user identity reference
- availability state
- location or zone data
- personality and vibe features
- dynamic behavioral signals
- activity preferences
- prior match history
- safety and exclusion data
- event/context metadata

### Data Dictionary Structure
A logical mapping layer should define where each signal lives.

Example concept:

- `user_id` -> `core.users.id`
- `match_opt_in` -> `matching.window_status.opted_in`
- `current_zone` -> `geo.user_presence.zone_id`
- `personality_vector` -> `profile.personality.vector`
- `social_energy_score` -> `profile.dynamic.social_energy`
- `activity_preferences` -> `profile.preferences.activities`
- `blocklist_edges` -> `trust.user_blocks`

### Benefits
- schema refactor resilience
- support for split databases
- cleaner engine code
- simpler migrations during rapid product evolution

---

## Config Architecture

Lotus should use runtime-editable configuration with version control.

### Config Layers

#### A. Global Engine Config
Defines generic operating behavior.

Example fields:
- max cycles
- default coverage target
- minimum average quality floor
- fallback behavior
- audit verbosity

#### B. Profile Config
Defines context-specific matching policy.

Example fields:
- profile name
- hard constraints
- default weights
- threshold floors
- relaxation ladder
- objective function coefficients

#### C. Feature Flags
Controls optional behaviors.

Example fields:
- enable novelty bonus
- enable repeat-avoidance
- enable fairness rebalancing
- enable unstable-group penalty

#### D. Environment Overrides
Used for dev, staging, simulation, or city/event-specific policy.

---

## Admin UI Requirements

The Admin UI should make Lotus tunable without code deployment.

### Core Admin Controls
- activate/deactivate profile
- edit soft constraint weights
- edit threshold values
- edit relaxation order and tier values
- define coverage and quality targets
- set group-size preferences
- toggle feature flags

### Operational Requirements
- changes must be versioned
- changes must be auditable by user and timestamp
- previous versions must be restorable
- validation must prevent impossible or unsafe combinations
- production changes should support preview before activation

### UI Recommendation
Use two levels:
- **Standard Controls** for operations/admin
- **Advanced Controls** for research/design teams

This prevents the settings page from becoming a reactor control panel at 3 a.m.

---

## Acceptance Framework

Lotus should not approve a cycle on coverage alone.

### Suggested Acceptance Conditions
A cycle is accepted only if:

- coverage >= target or acceptable fallback band
- average quality >= minimum floor
- no hard constraint violations
- no catastrophic fairness or stability failures
- no group below the absolute minimum compatibility floor unless explicitly permitted by policy

### Example
- coverage target = 95%
- minimum average quality = 0.72
- minimum single-group floor = 0.58
- hard constraint violations = 0

### Fallback Policy
If no cycle reaches the ideal target, Lotus may choose:
- best bounded fallback solution
- partial matching with deferred users
- no-match outcome for the window

This should be configurable per profile.

---

## Scoring Framework

Lotus needs two levels of scoring: group-level and cycle-level.

### Group-Level Score
Example conceptual formula:

`GroupScore = compatibility + preference_overlap + attendance_confidence + novelty_bonus - travel_burden - imbalance_penalty - known_risk_penalty`

### Cycle-Level Score
Example conceptual formula:

`CycleScore = (coverage_weight * coverage) + (quality_weight * avg_group_quality) - (relaxation_penalty * relaxation_depth) - (fairness_penalty * fairness_imbalance) - (instability_penalty * volatility)`

### Design Notes
- these should be normalized and bounded
- coefficients should live in profile config
- score components should be inspectable for analysis

---

## Fairness and Stability

Lotus should explicitly monitor fairness rather than treating it as an accidental side effect.

### Fairness Questions
- are some user segments repeatedly left unmatched?
- are some users only matched under heavily relaxed tiers?
- are certain users consistently assigned to lower-quality groups?
- do some preference types get overruled more often than others?

### Stability Questions
- does a tiny config change cause a dramatic assignment change?
- are users frequently churned between similar candidate groups?
- are repeated cycles generating unpredictable outcomes?

### Recommendation
These should initially be measured and logged, even if not heavily optimized yet.

---

## Fallback Behaviors

If all tiers fail, Lotus needs a graceful end state.

### Option A: Best Bounded Partial Match
Publish the best accepted partial result and defer unmatched users.

### Option B: Best Fallback Match
Publish a final bounded match set even if coverage target is missed, provided quality floors are respected.

### Option C: No-Match Window
Do not force a poor-quality output.

### Option D: Queue Carry-Forward
Carry unmatched users into the next cycle/window where policy allows.

The correct fallback should depend on the product context and user expectations.

---

## Observability and Audit Trail

Each matching run should produce rich telemetry.

### Run Metadata
- run id
- profile id
- config version
- timestamp
- window id
- population count

### Per-Cycle Metadata
- cycle number
- active tier
- active weights
- active thresholds
- matched count
- unmatched count
- coverage
- avg quality
- fairness metrics
- group-size stats
- rejection reason if failed

### Final Selection Metadata
- selected cycle number
- selection reason
- fallback type if applicable
- publication status

This is essential for trust, debugging, and future machine learning augmentation.

---

## Evaluation Layer Integration

Lotus should be built to plug directly into your matching evaluation layer.

### Evaluation Use Cases
- compare two profile configs
- test different relaxation ladders
- simulate cold-start behavior
- evaluate fairness across synthetic populations
- inspect sensitivity to weight changes
- compare optimizer strategies

### Important Design Choice
The production engine and the evaluation environment should share:
- the same profile definitions
- the same scoring components
- the same cycle logging schema where possible

This avoids the classic problem where the lab and the real engine drift into parallel universes.

---

## Suggested Persistence Schema Concepts

Below is a conceptual data model, not a final schema.

### `lotus_profiles`
Stores named matching profiles.

Fields may include:
- profile_id
- name
- description
- active_flag
- created_at
- updated_at

### `lotus_profile_versions`
Stores versioned config payloads.

Fields may include:
- version_id
- profile_id
- version_number
- config_json
- created_by
- created_at
- activation_status

### `lotus_runs`
Stores each matching run.

Fields may include:
- run_id
- profile_version_id
- window_id
- started_at
- completed_at
- final_status
- selected_cycle_number

### `lotus_cycles`
Stores cycle-level diagnostics.

Fields may include:
- cycle_id
- run_id
- cycle_number
- tier_name
- weights_json
- thresholds_json
- coverage
- avg_quality
- fairness_json
- accepted_flag
- rejection_reason

### `lotus_group_assignments`
Stores final published assignments.

Fields may include:
- assignment_id
- run_id
- group_id
- user_id
- group_score
- publication_status

### `lotus_unmatched`
Stores unmatched eligible users and reasons.

Fields may include:
- run_id
- user_id
- cycle_number
- final_reason_code

---

## Pseudocode

```python
def run_lotus(window_id: str, profile_name: str) -> MatchRunResult:
    profile = load_active_profile(profile_name)
    config = load_profile_config(profile)
    eligible_users = resolve_eligible_users(window_id, config)

    signals = load_signals(eligible_users, config.data_requirements)
    context = build_matching_context(eligible_users, signals, config)

    accepted_solutions = []
    cycle_results = []

    for tier in config.relaxation_ladder:
        cycle_context = apply_tier_to_context(context, tier)
        candidate_graph = build_candidate_graph(cycle_context)
        proposal = optimize_groups(candidate_graph, cycle_context)
        evaluation = evaluate_cycle(proposal, cycle_context, tier)

        cycle_results.append(evaluation)
        persist_cycle_diagnostics(evaluation)

        if evaluation.accepted:
            accepted_solutions.append(evaluation)

        if should_stop_early(evaluation, accepted_solutions, config):
            break

    final_solution = select_best_solution(accepted_solutions, cycle_results, config)
    publish_assignments(final_solution)
    persist_run_summary(final_solution, cycle_results)

    return final_solution
```

---

## Recommended Early Implementation Strategy

### Phase 1: Functional MVP
Build Lotus with:
- one profile
- one default relaxation ladder
- simple heuristic optimizer
- config stored in JSON or DB
- cycle logs
- coverage + quality acceptance checks

### Phase 2: Admin Control
Add:
- runtime config editing
- config versioning
- rollback
- profile switching

### Phase 3: Evaluation Integration
Add:
- replay capability
- comparative test harness
- synthetic population experiments
- fairness and stability dashboards

### Phase 4: Advanced Optimization
Explore:
- stronger optimization algorithms
- profile-specific objective functions
- learned scoring adjustments
- predictive no-show handling
- multi-window carry-forward optimization

---

## Risks and Guardrails

### Risk 1: Over-relaxation
Guardrail:
- define hard floors and maximum relaxation depth

### Risk 2: Poor user trust from bad matches
Guardrail:
- require minimum group-quality floors and preserve no-match option

### Risk 3: Config chaos
Guardrail:
- version configs, validate changes, and maintain rollback

### Risk 4: Hidden bias or unfairness
Guardrail:
- log fairness diagnostics and review cohort outcomes regularly

### Risk 5: Fragile storage dependencies
Guardrail:
- route all data access through the dictionary layer

### Risk 6: Research-production drift
Guardrail:
- share scoring/config foundations between evaluation and production

---

## Formal Engine Statement

**Lotus is Tribed/VYB’s adaptive group matching engine. It begins from an ideal, high-quality matching policy and progressively relaxes lower-priority constraints through predefined tiers until an acceptable balance of coverage and quality is reached. Lotus is configuration-driven, storage-agnostic, auditable, and designed to perform reliably in both low-density early-stage conditions and larger-scale future deployments.**

---

## Recommended Next Formalization Pass

Before implementation begins, the next review should finalize:

1. the exact list of hard vs soft constraints
2. the first production profile for VYB
3. the first relaxation ladder with numeric values
4. the cycle acceptance thresholds
5. the scoring formula components
6. the config JSON schema
7. the logging schema for evaluation and admin analytics
8. the first-pass optimizer strategy

---

## Suggested Working Name

**Lotus Engine**

Optional internal subtitle:
**Adaptive Progressive Matching for VYB**

