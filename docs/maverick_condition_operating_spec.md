# Maverick Condition Operating Spec (OST)

This spec defines how Maverick must operate the Conditions workflow in the On-Screen Takeoff Takeoff tab.

## Source References

- [Takeoff Tab: Conditions Window](https://help.constructconnect.com/04-the-takeoff-tab-in-detail-71/on-screen-takeoff-04-04-takeoff-tab-the-conditions-window-681)
- [What Are Conditions?](https://help.constructconnect.com/RD-AA-04235)
- [Conditions List Context Menus](https://help.constructconnect.com/topic/show?tid=683)
- [Conditions Window Toolbar](https://help.constructconnect.com/RD-AA-04231/)

## Core OST Rules (from documentation)

1. Conditions are the measurable takeoff objects and are reused across pages/bid scope.
2. The Conditions tab displays each condition and its page-associated quantities.
3. Reassigning takeoff is a supported operation and must target the currently selected condition.
4. Deleting a condition is destructive and deletes associated takeoff objects; treat deletion actions with caution.
5. Conditions can be duplicated and then edited/reassigned to create similar condition variants.

## Maverick Training Constraints (project-specific)

1. Allowed condition names for this exercise are only:
   - `ceiling`
   - `gwb`
2. Any condition selection outcome outside those names is invalid.
3. `(unassigned)` rows are always invalid.

## Two-Phase Condition Handling Contract

### Phase A: Boost Condition Discovery (before erase)

Goal: identify which condition Boost actually used.

Required checks:

1. Locate a row whose normalized name is `ceiling` or `gwb`.
2. Confirm row quantity is greater than zero.
3. Lock the row index and condition keyword.
4. Persist proof in attempt artifacts:
   - selected condition text
   - selected condition keyword
   - selected row index
   - lock confidence

If no qualifying row exists, fail the attempt as:
- `boost_condition_not_locked_to_ceiling_or_gwb`

### Phase B: Agent Copy Attempt (after erase)

Goal: use the same condition identity, not Boost quantity state.

Required checks:

1. Select by locked condition identity:
   - locked row index
   - locked condition keyword (`ceiling` or `gwb`)
2. Do not require quantity to remain >0 after Boost erase.
3. Selection mode in copy phase must be name/row lock mode.
4. If row/keyword mismatch occurs, fail as condition-lock violation.

## Cleanup Contract

1. Allowed cleanup sequence for training attempts:
   - `Ctrl+A` then `Delete`
2. Do not use copy/paste behavior in cleanup paths.
3. Record cleanup verification and phase timeline evidence.

## Runtime Safety Contract

1. Only one Boost flow may run per project at a time (mutex).
2. If lock owner process is not running, stale lock is recoverable.
3. Each run must emit phase timeline events for:
   - pre-clear
   - boost run
   - population check
   - condition lock
   - erase
   - teacher extraction
   - copy attempt

## Acceptance Gates

1. Condition lock success rate target: >= 95% on active Boost pages.
2. Zero quantity-doubling incidents from duplicate boosts/invalid cleanup.
3. Geometry pass trend must improve over rolling attempts.

## Implementation Note

Maverick must treat `qty > 0` as a discovery signal in Phase A only. During Phase B, Maverick must follow normal condition operation by selecting the locked condition identity (name + row), not by expecting Boost-populated quantity state.

