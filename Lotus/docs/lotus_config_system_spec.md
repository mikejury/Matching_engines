# Lotus Config System Spec

## Status
Final draft for implementation

## Purpose

The Lotus Config System governs all **tunable matching behavior** for the Lotus Engine without requiring backend redeploys for ordinary parameter changes.

Its purpose is to make Lotus:
- easy to tune during simulation and early product development
- safe to operate in production
- auditable and reversible
- compatible with future Admin UI editing
- compatible with future agent-assisted analysis and recommendation workflows

The config system is not a sidecar convenience. It is part of Lotus’s core operating model.

---

## Core Design Principle

**Lotus logic is stable in code. Lotus behavior is tunable in config.**

- scoring formulas, optimizers, and safety guardrails live in code
- weights, thresholds, feature toggles, and fallback tiers live in config

The engine is the machine. The config is the control panel.

---

## Key Architectural Decisions

1. **YAML is the canonical authoring format** (human-readable, supports comments)
2. **Simulation and production run separate Lotus instances**
3. Both environments use the **same schema and table structure**, but **different databases**
4. Config promotion from simulation → production is **manual (initially)**
5. **Scheduler triggers activation**, not the engine itself
6. Configs are **immutable per version**
7. Lotus reads config via a **Config Service abstraction**
8. Validation includes **structural, semantic, and policy layers**
9. Production failures **fail closed**
10. Agent-assisted tuning is **advisory-first**

---

## Environment Model

### Simulation Environment
- sandboxed database
- used for experimentation and parameter discovery
- supports rapid iteration and multiple variants

### Production Environment
- isolated database
- uses validated and promoted configs only
- optimized for stability and safety

### Important Rule
Simulation and production **never share a live config source**.

Promotion is explicit, controlled, and manual.

---

## Config Authoring Format

### YAML (Canonical)

Reasons:
- readable
- supports inline comments
- suitable for documenting experimental intent

Example:
```yaml
# Sparse city baseline profile
profile_name: casual_social_v1
algorithm_version: lotus-v1

weights:
  compatibility: 0.35  # dominant factor
  distance: 0.20       # keep reasonable travel
```

### Runtime Representation

YAML → parsed → validated → normalized → typed config object

Lotus never operates directly on raw YAML.

---

## Config Lifecycle

### Status States
- `draft`
- `validated`
- `active`
- `inactive`
- `archived`

### Lifecycle Flow
1. create draft (simulation)
2. validate
3. simulate and evaluate
4. select candidate
5. manually transfer to production
6. validate in production
7. scheduler activates

---

## Activation Model

### Principle
**Activation is controlled by the scheduler**

- Lotus engine does not self-activate configs
- configs are selected per run context

### Rules
- one active version per profile per environment
- activation is environment-local
- scheduler selects config at runtime boundary

---

## Config Structure

### Categories

#### Metadata
- profile_name
- algorithm_version
- ruleset_version
- environment
- notes
- tags

#### Eligibility
- location requirements
- request state requirements
- travel degradation rules
- friendship interpretation rules

#### Weights
- compatibility
- distance
- energy
- schedule
- friend_graph
- demographic

#### Thresholds
- coverage targets
- score minimums
- travel limits

#### Optimizer
- group size bounds
- improvement passes
- penalties

#### Selection
- tie-break rules
- early stop

#### Features
- toggles for optional behavior

#### Fallback Ladder
- tiered relaxation strategy

---

## Validation Model

### 1. Structural
- required fields
- correct types

### 2. Semantic
- valid ranges
- consistent constraints

### 3. Policy
- safety rules enforced
- protected behaviors preserved

### Rule
Invalid configs cannot be activated or executed.

---

## Config Storage

### Simulation
- YAML files + optional DB

### Production
- DB-backed versioned storage

### Tables
- `lotus_profiles`
- `lotus_profile_versions`

### Important Detail
Store BOTH:
- raw YAML (with comments)
- parsed config object

---

## Promotion Model

### Manual Transfer (v1)

1. export YAML from simulation
2. import into production
3. validate
4. scheduler activates

### Future
- structured promotion pipeline
- approval workflows

---

## Rollback Model

Rollback = re-activate previous version

- no mutation of existing versions
- full audit preserved

---

## Simulation Workflow

Simulation must support:
- multiple variants
- cloning configs
- parameter sweeps
- scenario tagging

Each run should log:
- config version
- scenario
- results

---

## Admin UI (Future)

Capabilities:
- view configs
- edit drafts
- validate
- activate via scheduler
- rollback
- import/export YAML

Modes:
- standard
- advanced
- protected

---

## Security Model

Roles:
- viewer
- editor
- validator
- activator
- protected admin

All actions logged with:
- user
- timestamp
- change note

---

## Agent Compatibility

Agents may:
- propose configs
- analyze results
- suggest improvements

Agents may NOT:
- auto-activate production configs

---

## Failure Behavior

### Invalid Config
- rejected

### Missing Production Config
- fail closed

### Simulation Error
- fail with diagnostics

---

## Implementation Layout

```text
lotus/config/
  loader.py
  validator.py
  normalizer.py
  service.py
```

---

## Build Phases

### Phase 1
- YAML schema
- loader + validator

### Phase 2
- DB storage
- versioning

### Phase 3
- simulation tooling

### Phase 4
- Admin UI

### Phase 5
- agent integration

---

## Final Statement

**The Lotus Config System is the control layer that allows Lotus to evolve safely. It enables experimentation in simulation, controlled deployment in production, and future intelligent tuning without compromising stability or trust.**

