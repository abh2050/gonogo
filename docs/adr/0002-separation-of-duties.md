# ADR 0002. Separation of duties for approvals

**Status:** Accepted, 2026-10-25
**Scope:** `authz/`, `kg/actions.py`, `kg/governance.py`, and every action that changes the approved graph

## Context

Gate 2 shipped a loop in which a steward approves a proposed fact and the verdicts rerun. A demo candidate
showed the weakness. A licensee-supplied ownership summary left out a co-owner that the approved record lists.
One steward's approval of it turned COUNSEL into GO, and nothing in the engine stopped it. The record showed
who approved the fact, which helps after the mistake and does nothing before it.

Three controls were possible:

1. **Warn and trust.** Show the conflict in the queue and let the steward decide. This is what Gate 2 did.
2. **Always require two approvers.** Safe, but it doubles the work for every fact, and most approvals complete
   a missing record and put nobody at risk.
3. **Require a second approver when the approval is risky.** The engine defines "risky" from the graph, and a
   policy decides who must act.

## Decision

GoNoGo takes option 3, and Cedar holds the policy.

**Two flags make an approval risky.** `kg/governance.py` computes them from the graph before the approval takes
effect:

- *Conflict.* The proposed fact contradicts a fact that is already approved. It omits a co-owner that the
  approved ownership record lists, or classifies a patent differently from the approved classification, or
  assigns a field of use that differs from the one on record.
- *Upgrade to GO.* The engine applies the approval to a copy of the store and reruns every question it knows
  about on the same patent: the 43 in the request book and the ones the steward's own session has asked. If any
  verdict moves from COUNSEL or NO GO to GO, the flag is set. A link between two company names gets the same
  test.

**Cedar decides what each flag means.** The engine builds the change, applies it to the copy, computes the flags,
and asks Cedar whether this principal may do `ApproveFact`. The policy permits a steward to approve alone
only when neither flag is set. When a flag is set, the steward may do `SubmitForSecondReview` instead. A
submitted approval is held in `PENDING_SECOND_REVIEW`. It writes a record of the submission and no fact, so no
rule can read it and no verdict can change. Counsel then does `SecondReview` and approves or denies. On
approval the fact enters the approved graph, recorded at counsel's time, with both approvers on it
(`gng:approvedBy` and `gng:secondApprovedBy`).

**Four rules no permit can override** (`forbid` policies in `authz/policies/gonogo.cedar`):

| Rule | Policy id |
|---|---|
| Nobody approves, submits, or second-reviews a fact they proposed | `no-self-approval` |
| The counsel who second-reviews is never the steward who approved first | `no-second-review-of-own-approval` |
| Counsel never approves a fact alone, so counsel is always the second person | `counsel-approves-only-after-a-steward` |
| The owner who proposed a release cannot approve its impact report | `no-self-approved-impact-report` |

**What counts as the proposer.** Every candidate carries `gng:proposedBy`: a steward who used `propose_fact`, a
licensee who supplied a summary, a data feed, or a language model's `gng:ModelAgent`. A model can propose and
can never approve, because it holds no role.

**The log stays honest.** Each event records its route and the policies that decided it. Replaying a log
recomputes the route from the graph, and a log whose recorded route no longer matches the policy is
rejected. A client that edits `pending_second_review` to `immediate` in its own log gets an error.

## Consequences

**What improves.**

- The decoy that failed in Gate 2 now stops. The injected case INJ-045 replays the whole script and passes only
  when the approval cannot produce GO without a second approver.
- The policy is a text file that a reviewer reads in a pull request, and the same file runs in Amazon Verified
  Permissions. Tests check every role against every action (`tests/authz/`).
- A malformed Cedar request raises an error. It does not return a denial, so a wiring mistake cannot pass as a
  refusal.

**What it costs.**

- A flagged approval takes two people. A legitimate correction of an old record will trip the conflict flag, and
  counsel's queue will grow with it. If counsel approves nearly every held item, the flag is too sensitive.
  The route is recorded on every event, so this can be measured.
- The upgrade flag sees only questions the engine knows: the request book and the session's own. A steward who
  approves a fact that moves some other user's question to GO is not caught. The conflict flag catches the
  common case, a fact that contradicts the record, and the second flag narrows the gap without closing it.
- Two flags are a heuristic for "this approval is risky". They do not cover a wrong fact that contradicts
  nothing on record, such as a field of use that a model misreads. For model proposals the queue shows the
  notice's own words, so a steward can check them.
- In the public demo a visitor picks a name and a role, so a single visitor can play both people. The demo shows
  how the policy works. In the AWS deployment the principal and role come from the signed-in user's Cognito
  group, and a second person has to sign in.

## Alternatives rejected

- **Two approvers on every fact.** Doubles the cost to guard against a risk that a few approvals carry.
- **Put the rule in Python.** The rule would work, and a reviewer would have to read the code to learn it. A
  Cedar file states who may do what in one place, and Verified Permissions runs it unchanged.
- **Let counsel approve alone.** Counsel then becomes one more single point of failure. Counsel's role is the
  second look.
