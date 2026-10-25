// GoNoGo authorization. The same policy text runs in-process (authz/cedar.py) and in Amazon Verified
// Permissions (infra/). Roles are groups: Role::"licensing_manager", "steward", "counsel", "ontology_owner",
// "finance_analyst", and "auditor". Cedar denies by default, so every permit below is a grant that a test
// in tests/authz/ checks, and every forbid is a rule that no permit can override.
//
// Custom annotation @reason is the sentence that GoNoGo shows when the policy denies an action.

// ---- Asking and reading decisions --------------------------------------------------------------------

@id("ask-clearance")
permit (principal, action == Action::"AskClearance", resource)
when { principal in Role::"licensing_manager" || principal in Role::"steward" || principal in Role::"counsel" };

@id("read-decisions")
permit (principal, action in [Action::"ViewDecision", Action::"RerunDecision"], resource)
when { principal in Role::"licensing_manager" || principal in Role::"steward" || principal in Role::"counsel"
       || principal in Role::"auditor" };

// ---- Reading graphs: the query service asks before it fills any FROM clause ------------------------------

@id("read-release-graph")
permit (principal, action == Action::"ReadGraph", resource == Graph::"release")
when { principal in Role::"licensing_manager" || principal in Role::"steward" || principal in Role::"counsel"
       || principal in Role::"ontology_owner" };

@id("read-approved-graph")
permit (principal, action == Action::"ReadGraph", resource == Graph::"approved")
when { principal in Role::"licensing_manager" || principal in Role::"steward" || principal in Role::"counsel"
       || principal in Role::"ontology_owner" };

@id("read-candidate-graph")
permit (principal, action == Action::"ReadGraph", resource == Graph::"candidate")
when { principal in Role::"steward" || principal in Role::"counsel" };

@id("read-royalty-graph")
permit (principal, action == Action::"ReadGraph", resource == Graph::"royalty")
when { principal in Role::"counsel" };

// Finance reads royalty terms in Snowflake and never queries the graph.
@id("read-royalty-table")
permit (principal, action == Action::"ReadRoyaltyTable", resource)
when { principal in Role::"finance_analyst" || principal in Role::"counsel" };

@id("read-release-history")
permit (principal, action == Action::"ReadReleaseHistory", resource)
when { principal in Role::"auditor" || principal in Role::"ontology_owner" || principal in Role::"counsel" };

// ---- Facts and identity links: separation of duties (docs/adr/0002-separation-of-duties.md) -------------

@id("propose-fact")
permit (principal, action == Action::"ProposeFact", resource)
when { principal in Role::"steward" || principal in Role::"licensing_manager" };

// A steward approves a fact alone only when it neither conflicts with an approved fact nor moves a verdict
// from COUNSEL or NO GO to GO.
@id("steward-approves-clean-fact")
permit (principal, action in [Action::"ApproveFact", Action::"LinkIdentity"], resource)
when { principal in Role::"steward" && context.conflict == false && context.upgradesToGo == false };

// Otherwise the steward's approval waits for counsel and changes no verdict until counsel agrees.
@id("steward-submits-flagged-fact")
permit (principal, action == Action::"SubmitForSecondReview", resource)
when { principal in Role::"steward" && (context.conflict == true || context.upgradesToGo == true) };

@id("counsel-second-review")
permit (principal, action == Action::"SecondReview", resource)
when { principal in Role::"counsel" };

@id("reject-fact")
permit (principal, action in [Action::"RejectFact", Action::"RejectLink"], resource)
when { principal in Role::"steward" || principal in Role::"counsel" };

@id("override-verdict")
permit (principal, action == Action::"OverrideVerdict", resource)
when { principal in Role::"counsel" };

@id("no-self-approval")
@reason("You proposed this fact, so someone else must approve it.")
forbid (principal, action in [Action::"ApproveFact", Action::"SubmitForSecondReview", Action::"SecondReview",
                              Action::"LinkIdentity"], resource)
when { context.proposer == principal.name };

@id("no-second-review-of-own-approval")
@reason("You made the first approval, so a different counsel must make the second.")
forbid (principal, action == Action::"SecondReview", resource)
when { context.firstApprover == principal.name };

@id("counsel-approves-only-after-a-steward")
@reason("Counsel reviews an approval that a steward submitted. Counsel does not approve a fact alone.")
forbid (principal, action in [Action::"ApproveFact", Action::"LinkIdentity"], resource)
when { principal in Role::"counsel" };

// ---- Ontology releases ---------------------------------------------------------------------------------

@id("propose-release")
permit (principal, action == Action::"ProposeRelease", resource)
when { principal in Role::"ontology_owner" };

@id("approve-impact-report")
permit (principal, action == Action::"ApproveImpactReport", resource)
when { principal in Role::"counsel" || principal in Role::"ontology_owner" };

@id("publish-release")
permit (principal, action == Action::"PublishRelease", resource)
when { principal in Role::"ontology_owner" && context.gatePassed == true && context.counselApproved == true };

@id("no-self-approved-impact-report")
@reason("You proposed this release, so someone else must approve its impact report.")
forbid (principal, action == Action::"ApproveImpactReport", resource)
when { context.proposer == principal.name };
