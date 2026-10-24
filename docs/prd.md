# RightsGraph PRD

> Reference input. GoNoGo follows its own build spec where the two differ; docs/status.md lists each
> resolution. Apart from the omitted sections 2 and 22 and one removed line in section 18, this file is kept verbatim, so the style test in
> tests/unit/test_docs_style.py skips it.

**Version:** 2.1, revised after the Claude, Abacus, and ChatGPT architecture reviews

## 1. Summary

RightsGraph is an ontology‑grounded agentic AI system that answers patent license clearance questions. A deterministic rule engine evaluates each constraint against a W3C knowledge graph, and a versioned decision combiner turns the rule results into a verdict. An LLM parses requests, extracts candidate facts from legal text, maps free text to taxonomy concepts, and explains verdicts, but it never decides one. Every state change runs through a governed action with permissions, validation, and provenance. The system runs on AWS with Amazon Bedrock, Amazon Neptune, Step Functions, and Snowflake, and it uses real NASA patent and license notice data with transparent synthetic augmentation.

The implementation concentrates on one core loop. A user asks a question, the rules evaluate it, the verdict card shows every finding with its evidence, a steward approves a new fact, and the rerun shows why the verdict changed. Enterprise integrations follow only after that loop works end to end.

## 2. Omitted

This public copy omits section 2. The other section numbers stay unchanged, so the cross-references in the text still work.

## 3. Problem

A licensing manager must confirm several facts before offering license terms. The patent must be legally in force. No executed grant can conflict with the requested field of use, territory, term, and exclusivity. Export restrictions cannot block the licensee. Co‑owners must consent where joint ownership exists. Exclusive licenses require a public notice and legal review. These facts live in patent records, Federal Register notices, signed agreements, and technical reports. The manager checks them by hand, which takes hours per request, misses conflicts, and leaves no reproducible decision record. This PRD treats that manual process as the assumed current state, because NASA does not publish its internal workflow.

## 4. Users and roles

1. A **licensing manager** submits clearance questions and reads verdicts.
2. **Patent counsel** reviews findings that require legal judgment and can override a verdict with a written justification.
3. A **data steward** approves, edits, or rejects facts that the LLM extracts.
4. An **ontology owner** proposes changes to the ontology, taxonomies, shapes, rules, and combiner policy, and publishes releases after review.
5. A **finance analyst** reads verdicts and royalty terms in Snowflake and cannot query the graph.
6. An **auditor** reads decision records and release history and cannot change anything.

## 5. Goals and non‑goals

**Goals**

1. The system returns a verdict with every rule finding and its evidence in under 10 seconds at p95.
2. The system produces zero false Clear verdicts on the high risk test suite.
3. The system detects every conflict and every missing fact case that the synthetic generator injects.
4. Every approved fact records its source span, extraction model, approving steward, business effective period, and recording time.
5. Every past verdict reruns to the same result from its stored decision context.
6. The evaluation measures what the LLM adds, separately from what the rule engine guarantees.
7. No role can read a graph outside its permissions, and leakage tests prove it.

**Non‑goals**

1. The system does not give legal advice or replace counsel.
2. The system does not negotiate royalties or draft agreements.
3. The system does not connect to real NASA internal systems.
4. The project does not build a Collibra adapter or a full lineage platform.
5. The project does not exercise a multi AZ failover, although the HLD documents the design.

## 6. Data sources

1. **Federal Register NASA license notices** provide real legal text naming patents, prospective licensees, exclusivity type, territory, and field of use limits. A scheduled job pulls them from the public Federal Register API, filtered to NASA and the phrase "patent license." Each notice announces an intended grant and opens an objection window, so the system records it as a proposed grant and never as an executed one.
2. **The NASA Patents dataset on data.nasa.gov** (identifier gquh‑watm) provides the patent master table with case numbers, patent numbers, application numbers, and center. Snowflake stores it as the system of record.
3. **USPTO patent records** provide legal status, including term adjustments and maintenance fee events where available. Gate 2 confirms which USPTO feed carries these fields before the pipeline depends on it.
4. **The NASA T2 portal API** provides technology descriptions and categories. The categories seed the field of use taxonomy.
5. **NTRS records** provide technical reports for the thin retrieval tool. The index stores only reports linked to patents in the graph.
6. **A synthetic generator** produces executed agreements seeded from real notices, with royalties, effective terms, sublicense rights, ownership records, consent records, and export classifications. It injects documented conflicts, missing facts, explicit negative facts, and retroactive corrections, so every test suite has ground truth. The README marks every synthetic field.

## 7. Ontology

### 7.1 Method

1. The team writes 15 to 20 competency questions before modeling, derived from the rules in section 8.3.
2. The team annotates 20 real notices and turns the nouns the questions need into candidate classes and properties.
3. The model reuses SKOS, PROV‑O, Dublin Core, and ISO 3166 codes. An ADR records that the team evaluated FIBO's agreements module and chose not to import it.
4. The team builds the ontology in Protégé and checks consistency with HermiT.
5. Each competency question becomes a SPARQL query and a pytest test against hand written sample data on Fuseki.
6. pyLODE generates HTML documentation, and a w3id.org persistent IRI resolves the namespace to it.

### 7.2 Design

1. The OWL ontology defines Patent, PatentLegalStatus, NASACenter, Licensee, OwnershipRecord, CoOwner, ConsentRecord, ExportClassification, LicenseNotice, ProposedGrant, ExecutedGrant, Clause, Action, and Decision.
2. ProposedGrant and ExecutedGrant share a parent class, Grant, which carries patent, licensee, field of use, territory, exclusivity type, and effective term. A LicenseNotice creates only a ProposedGrant. Only an executed agreement creates an ExecutedGrant.
3. Every approved fact carries a business effective period through `rg:validFrom` and `rg:validTo`, a recording time through `rg:recordedAt`, and a replacement time through `rg:supersededAt` when a later fact corrects it.
4. An OwnershipRecord states either that ownership is complete with a listed set of co‑owners, which may be empty, or that ownership is incomplete. This structure lets the system tell "no co‑owners" apart from "co‑ownership not recorded."
5. A SKOS concept scheme models fields of use, built from T2 categories with narrower concepts beneath each.
6. A SKOS concept scheme models territories with ISO 3166 codes and broader relations from countries to regions.
7. PROV‑O links each approved fact to its document, clause span, extraction model, steward, and approval action.
8. SHACL shapes validate conformance, covering required properties, datatypes, cardinality, value ranges, and allowed concept schemes. SHACL does not decide verdicts.

### 7.3 Modeling decisions

1. **Grant is a class.** A license relates a patent, licensee, field, territory, term, and exclusivity type at once, so the W3C n‑ary relations pattern turns the relationship into its own node.
2. **Proposed and executed grants are separate classes.** A public notice of intent does not prove that a license exists. Conflict rules treat the two classes differently.
3. **Fields of use are SKOS concepts.** The business edits categories over time, while OWL subclasses would assert logical set membership the business does not intend.
4. **Broader and narrower relations in the field scheme mean rights coverage.** A grant for a broader field covers every narrower field beneath it. The scheme documentation states this rule, and the ontology owner must preserve it when editing the hierarchy, because every hierarchy edit changes legal outcomes.
5. **OWL describes meaning under the open world assumption.** A missing fact means unknown. The rule engine therefore returns UNKNOWN instead of treating an absence as a negative fact.
6. **Explicit negative facts are modeled as facts.** A complete ownership record with no co‑owners lets R6 pass. A missing or incomplete record produces UNKNOWN.
7. **Facts are bitemporal.** The effective period answers whether a grant applies on a date. The recording time answers what the system knew when it decided. Both are required to reproduce past verdicts and to handle retroactive corrections.
8. **The pipeline materializes inference before load.** Neptune does not reason at query time, so owlrl computes subclass and broader closures before loading, and rule templates use SPARQL property paths as a second safeguard.

## 8. Decision engine

### 8.1 Responsibility split

1. SHACL validates that the graph conforms to the model.
2. Rule functions, built from parameterized SPARQL templates plus Python logic, evaluate each constraint and return a status with evidence.
3. The decision combiner turns rule statuses into a verdict under a versioned precedence policy.
4. The LLM performs language tasks only, and section 8.4 bounds each task.

### 8.2 Rule statuses

Each rule returns one status with the fact IDs it read.
1. **PASS** means the constraint holds and the evidence is complete.
2. **FAIL** means the rule established a conflict.
3. **UNKNOWN** means required evidence is missing.
4. **REVIEW** means the constraint requires legal judgment.
5. **PENDING** means a time window must close before the request can proceed.
6. **NOT_APPLICABLE** means the constraint does not apply to this request.

### 8.3 Rules

1. **R1 Legal status.** The rule returns PASS when USPTO legal status shows the patent in force at the requested start date. It returns FAIL when the patent has expired or lapsed before that date. It returns UNKNOWN when legal status is missing. A computed expiry from the filing date appears on the card as an informational hint and never produces PASS.
2. **R2 Exclusivity compatibility.** The rule compares the request with every ExecutedGrant on the same patent whose field, territory, and effective term overlap the request. Overlap uses the field and territory hierarchies in both directions. An exclusive request conflicts with any overlapping executed grant. A partially exclusive or co‑exclusive request conflicts with an overlapping exclusive grant. A nonexclusive request conflicts only with an overlapping exclusive grant. Any conflict returns FAIL. An overlap with a ProposedGrant held by another party returns REVIEW. No overlap returns PASS.
3. **R3 Co‑exclusive cap.** The rule returns FAIL when a co‑exclusive request would exceed the cap stated in existing agreements, PASS when it stays within the cap, UNKNOWN when no cap is recorded, and NOT_APPLICABLE for other exclusivity types.
4. **R4 Notice requirement.** For exclusive, co‑exclusive, and partially exclusive requests, the rule returns PENDING while the matching notice's objection window remains open, PASS after the window closes, and REVIEW when no matching notice exists. It returns NOT_APPLICABLE for nonexclusive requests.
5. **R5 Export classification.** The rule returns PASS when the technology is unrestricted or the licensee's country is permitted, REVIEW when the technology is restricted and the country falls outside the permitted set, and UNKNOWN when no classification exists.
6. **R6 Co‑owner consent.** The rule returns PASS when a complete ownership record lists no co‑owners or when every co‑owner has a consent record. It returns REVIEW when a co‑owner lacks consent. It returns UNKNOWN when the ownership record is missing or incomplete.
7. **R7 Statutory review.** The rule returns REVIEW for every exclusive, co‑exclusive, and partially exclusive request, with a flag for counsel to check the 35 U.S.C. 209 conditions, including the substantial United States manufacturing requirement. It returns NOT_APPLICABLE for nonexclusive requests. The system never evaluates the statutory conditions itself.

The LLD documents each rule as a named function with inputs, outputs, SPARQL template, and the competency questions it answers.

### 8.4 Decision combiner

1. The combiner runs every applicable rule on every request. No rule can skip another.
2. The combiner applies this precedence. Any FAIL produces **Blocked**. Otherwise, any REVIEW produces **Counsel review**. Otherwise, any UNKNOWN produces **Insufficient evidence**. Otherwise, any PENDING produces **Pending**. When every applicable rule returns PASS, the combiner produces **Clear**.
3. Because R7 always returns REVIEW for exclusive requests, an exclusive request can never reach Clear. Only a nonexclusive request with complete evidence can.
4. The verdict card shows the overall verdict and every rule finding beneath it, so a Blocked verdict still displays missing evidence and open windows.
5. The precedence policy is a versioned file in the release bundle, so a policy change goes through the release pipeline like any ontology change.

### 8.5 LLM tasks

1. **L1 Request parsing.** The LLM converts a plain language question into a JSON request. A JSON schema validates the output, and every field of use and territory must resolve to an existing SKOS concept. When a value fails to resolve, the agent asks the user to clarify.
2. **L2 Fact extraction.** The LLM proposes candidate triples from notices and agreements, each with a character span pointing to its clause. SHACL validates the candidates, and a steward approves each one before it enters the approved graph.
3. **L3 Field of use mapping.** The LLM proposes a SKOS concept for free text field language. Proposals below a confidence threshold go to the steward queue.
4. **L4 Explanation.** The LLM writes the explanation from the rule findings and cited facts only. A deterministic checker confirms that every rule ID and fact ID in the explanation exists in the decision record and that every quoted clause matches an approved source span. Bedrock Guardrails runs its contextual grounding check as a secondary filter. When either check fails, the card shows the structured findings without the narrative.
5. **L5 Technical context.** A thin retrieval tool answers questions about a patented technology from NTRS passages with citations. The card labels these answers as informational, and they never feed a rule.

## 9. Action types

Every state change runs as an action with typed inputs, a Cedar permission, SHACL validation, a named graph as its writeback target, and a PROV‑O activity that SPARQL can query.

1. **SubmitClearanceRequest** lets a licensing manager create a request and receive a verdict.
2. **ProposeFacts** lets the ingestion pipeline write candidate triples to the candidate graph.
3. **ApproveFact** and **RejectFact** let a steward promote or discard a candidate with a reason.
4. **CorrectFact** lets a steward supersede an approved fact with a new one, recording the correction time without deleting the original.
5. **OverrideVerdict** lets counsel record a different outcome with a justification, without altering the original decision.
6. **PublishRelease** lets the ontology owner publish a release after the release gate passes.

## 10. Functional requirements

1. **FR‑01** The system accepts a clearance question in plain language through the web UI and the REST API.
2. **FR‑02** The system returns one of five verdicts from section 8.4 with every rule finding.
3. **FR‑03** Each finding shows its status, the facts it read, the source clauses behind those facts, and any missing evidence.
4. **FR‑04** The system ingests a notice or agreement and runs extraction, validation, and steward approval before any fact affects a verdict.
5. **FR‑05** A steward approves, edits, rejects, or corrects facts, and the system records each action and reason.
6. **FR‑06** Counsel overrides a verdict only with a written justification.
7. **FR‑07** The system reruns open requests when an approved fact, a correction, or a new release affects their patent, and shows what changed and why.
8. **FR‑08** The system reruns any past decision from its stored decision context and returns the original result.
9. **FR‑09** The ontology owner publishes a release only after the release gate passes and a reviewer approves the impact report.
10. **FR‑10** The system loads patent data from Snowflake, exposes exploration data through Ontop, and writes verdicts back to Snowflake.
11. **FR‑11** The system publishes events for document ingested, fact approved, fact corrected, verdict issued, and release published.
12. **FR‑12** The agent answers technical questions from NTRS passages with citations and an informational label.

## 11. Architecture

### 11.1 Clearance path

1. The user signs in through Amazon Cognito and receives a JWT that carries the user's role group.
2. Amazon API Gateway validates the JWT and forwards the request to the agent service.
3. The agent service on ECS Fargate runs Strands Agents and calls Claude on Bedrock to parse the request.
4. The agent calls the query service Lambda with the parsed request and the user's identity.
5. The query service asks Amazon Verified Permissions which named graphs the user may read.
6. The query service fills each rule template with the request parameters, the allowlisted graph IRIs, the current release version, and the recording cutoff time, then runs the templates against Neptune.
7. The combiner Lambda applies the precedence policy and returns the verdict with every finding.
8. The agent sends the findings to Bedrock for the explanation, and the citation checker and Guardrails validate it.
9. The agent service writes the decision record to DynamoDB and a copy to S3 with Object Lock, then returns the verdict card.

### 11.2 Ingestion path

1. An EventBridge schedule triggers a Lambda function that pulls new NASA notices from the Federal Register API into S3. Synthetic agreements land in the same bucket.
2. Each upload starts a Step Functions workflow.
3. Amazon Textract extracts text from PDF agreements. Notices skip this step because the API returns structured text.
4. A Lambda function calls Bedrock with structured output to produce candidate triples with clause spans.
5. A Lambda container image runs pySHACL against the candidates.
6. Step Functions pauses on a waitForTaskToken callback until a steward acts.
7. On approval, a Lambda function writes the approved triples to the approved graph through SPARQL UPDATE, stamping recording time and provenance.
8. EventBridge publishes a fact approved event, and a consumer reruns affected open requests.

### 11.3 Bulk loading

1. The Neptune bulk loader handles the initial load and the nightly patent snapshot from Snowflake.
2. SPARQL UPDATE handles individual steward approvals and corrections.

### 11.4 Snowflake path

1. A nightly Snowflake task unloads the patent master and licensee tables to S3 as Parquet. A mapping Lambda applies R2RML mappings from the repo and bulk loads the result with recording timestamps, so rule facts stay materialized and reproducible.
2. Ontop on ECS Fargate exposes Snowflake tables that no rule depends on as a virtual SPARQL endpoint through the same R2RML mappings. Ontop has supported Snowflake since version 5.0.0, and the mappings declare missing integrity constraints through lenses and avoid special characters in column aliases, as the Ontop documentation advises.
3. A Lambda function writes each verdict to a Snowflake table through the Snowflake Python connector for finance reporting.

### 11.5 Semantic release path

1. The ontology, SKOS schemes, SHACL shapes, rule templates, combiner policy, and R2RML mappings form one versioned bundle in S3.
2. A pull request to the bundle starts a GitHub Actions pipeline. ROBOT runs HermiT to check consistency, rdflib checks syntax, and pySHACL validates the sample data.
3. The pipeline runs the regression, high risk, and counterfactual suites against the current and proposed bundles and writes an impact report listing every changed verdict, every changed finding, and the cause.
4. Step Functions routes the impact report to the ontology owner and counsel for approval.
5. On approval, PublishRelease activates the bundle and emits a release published event.
6. A consumer reruns every pending request under the new release before any steward or counsel action completes.

### 11.6 Decision context and reproducibility

1. Each decision record stores the canonical request, user, role, release version, rule versions, combiner policy version, evaluation time, recording cutoff time, every finding, every fact ID read, model ID, prompt hash, checker and guardrail results, verdict, and any override.
2. Rule templates select only facts recorded at or before the cutoff and not superseded by then.
3. A rerun of any decision uses its stored release and cutoff and must return the original findings, which the reproducibility suite verifies.

## 12. Tech stack

1. **Amazon Bedrock with Claude** handles parsing, extraction, mapping, explanation, and retrieval answers. The audit log records the pinned model ID.
2. **Strands Agents on ECS Fargate** runs orchestration as a long running service.
3. **Amazon Neptune Serverless with RDF and SPARQL 1.1** stores the knowledge graph.
4. **Amazon Bedrock Knowledge Bases with Amazon S3 Vectors** index NTRS passages, and each chunk carries its patent IRI as metadata.
5. **Amazon Bedrock Guardrails** filters PII, blocks a denied topic for legal advice, and runs contextual grounding checks.
6. **AWS Step Functions** runs ingestion and release review with human approval steps.
7. **AWS Lambda** runs the query service, combiner, validation, mapping, loading, and sync jobs.
8. **Amazon API Gateway** fronts the REST API with a Cognito authorizer, request validation, and throttling.
9. **Amazon Cognito** handles sign in and role groups.
10. **Amazon Verified Permissions with Cedar** decides graph and action permissions.
11. **Amazon Textract** extracts text from agreement PDFs.
12. **Amazon EventBridge** carries domain events and schedules.
13. **Amazon DynamoDB** stores decision records, the steward queue, and release metadata.
14. **Amazon S3 with versioning and Object Lock** stores documents, release bundles, load files, and audit copies.
15. **AWS KMS** encrypts data at rest with customer managed keys.
16. **Amazon CloudWatch, AWS X‑Ray, Bedrock model invocation logging, and AWS CloudTrail** provide metrics, traces, prompt logs, and control plane audit.
17. **Snowflake** stores the patent master, licensee, and verdict tables.
18. **Ontop 5** serves the virtual endpoint over Snowflake.
19. **Protégé, HermiT, and ROBOT** support ontology authoring and consistency checks.
20. **rdflib, owlrl, and pySHACL** handle graph processing, inference materialization, and validation in Python.
21. **Apache Jena Fuseki in Docker** runs the graph locally so the core loop works before any AWS spend.
22. **pyLODE and w3id.org** publish ontology documentation at a persistent IRI.
23. **AWS CDK in Python** defines all infrastructure, and **GitHub Actions with OIDC federation** deploys it without stored keys.
24. **React with Vite on S3 and CloudFront** provides the verdict card, steward queue, and release review screen.
25. **Python 3.12 with pytest** runs services and every test suite.

## 13. Architecture decision records

1. **Rules decide, the combiner aggregates, and the LLM assists.** This split keeps every legally consequential outcome deterministic and reproducible.
2. **The combiner applies a versioned precedence policy.** The policy resolves simultaneous findings without hiding any of them.
3. **The graph stores decision facts and the vector index stores context.** Clearance needs exact relationships, hierarchy traversal, explicit treatment of missing evidence, repeatable answers, and graph level access control. NTRS prose has no structure worth modeling, so similarity search fits it. The ADR rejects vector only RAG because it cannot enforce exclusivity or represent missing evidence, and it rejects LLM generated SPARQL because the model would write the queries that decide verdicts.
4. **Proposed and executed grants stay separate.** A notice of intent does not prove a license.
5. **Facts are bitemporal.** Reproducibility and retroactive corrections both require recording time alongside effective time.
6. **SHACL validates and rule functions decide.** Each concern has one owner.
7. **Neptune Database fits better than Neptune Analytics.** The steward workflow needs transactional updates.
8. **Inference is materialized before load.** Neptune does not reason at query time.
9. **Rule facts are materialized and exploration data stays virtual.** Rules need low latency and fixed recording times, and exploration does not.
10. **Bulk loads and steward updates use different write paths.** The bulk loader suits large imports, and SPARQL UPDATE suits single approvals.
11. **Authorization lives in the query service.** Named graphs organize facts, but the service enforces access.
12. **Explanations pass a deterministic citation check before Guardrails.** Guardrails detects likely unsupported text and does not prove correctness.
13. **Strands on Fargate fits the orchestration need.** The ADR compares it with Bedrock Agents and Bedrock AgentCore Runtime.
14. **S3 Vectors fits the low traffic retrieval workload.** The ADR compares it with OpenSearch Serverless.
15. **The W3C model carries semantics and the Palantir action pattern governs writeback.**
16. **FIBO stays out of the import list.** Its agreements module adds structure that clearance does not need.

## 14. Security, RBAC, and audit

1. Neptune, Lambda functions, Ontop, and the agent service run in private subnets, and VPC endpoints reach AWS services without public internet.
2. Neptune requires IAM database authentication. Only the query service role and the ingestion write role can reach Neptune, and no application user can reach the SPARQL endpoint.
3. Neptune treats its default graph as the union of all named graphs. The query service therefore inserts allowlisted graph IRIs into every template through FROM and GRAPH clauses, and rejects any template without them.
4. Cedar policies give licensing managers the approved graph without royalty terms, give finance royalty terms through Snowflake only, give stewards the candidate graph, give the ontology owner release actions, and give counsel all graphs.
5. The leakage suite attempts reads through default graph queries, DESCRIBE, CONSTRUCT, SERVICE federation, and graph store operations for every role, and fails the build on any leak.
6. Ingested text enters extraction prompts inside delimited data blocks. Schema and SHACL validation filter the output, so planted instructions cannot change a verdict.
7. Decision records follow section 11.6, and S3 Object Lock keeps audit copies tamper evident.
8. A STRIDE threat model covers prompt injection through documents, graph leakage, privilege escalation through actions, audit tampering, and unauthorized releases.

## 15. Non‑functional requirements

1. **Latency.** Verdicts return in under 10 seconds at p95, and rule evaluation with the combiner returns in under 1 second at p95.
2. **Throughput.** The service sustains 20 concurrent clearance requests in a load test.
3. **Availability.** The demo targets 99.5 percent, and the HLD documents the multi AZ design for 99.9 percent.
4. **Ingestion.** A document reaches the steward queue within 2 minutes of upload.
5. **Release.** The release pipeline produces an impact report within 15 minutes.
6. **Reproducibility.** Every sampled past decision reruns to identical findings.
7. **Recoverability.** A Neptune snapshot and the S3 load files rebuild the graph in under 30 minutes.
8. **Cost.** An AWS Budgets alarm caps build spend, and the team destroys the stack between sessions because Neptune Serverless bills at minimum capacity while idle.

## 16. Evaluation

### 16.1 Risk metric

False clearance rate is the primary metric. A Clear verdict on a request that should be Blocked, Counsel review, Insufficient evidence, or Pending counts as a false clearance. The high risk suite must produce zero false clearances before any release or demo.

### 16.2 AI value metrics

1. **Request parsing.** The team scores accuracy on 100 ambiguous questions against hand labeled structured requests and compares it with a keyword matching baseline.
2. **Field of use mapping.** The team scores accuracy on 100 free text descriptions against hand labeled SKOS concepts and compares it with an embedding nearest neighbor baseline.
3. **Extraction.** The team targets precision of at least 0.90 and recall of at least 0.85 on 50 hand labeled documents.
4. **Steward effort.** The team measures review minutes per document with LLM extraction against manual entry on the same 20 documents.
5. **Explanation faithfulness.** The team reports how often the citation checker and Guardrails block explanations and audits a sample of passed explanations by hand.

### 16.3 Correctness suites

1. **Regression.** A set of 150 questions confirms rule and combiner behavior on every merge. The team presents it as proof of rule correctness, never as an AI metric.
2. **Hierarchy.** The suite confirms that a broad field grant conflicts with a narrower request and that sibling fields do not conflict.
3. **Temporal.** The suite covers partial term overlaps, future effective grants, expired grants, and retroactive corrections.
4. **Evidence.** The suite confirms that an explicit "no co‑owners" record passes R6 and that a missing or incomplete record returns UNKNOWN, with matching cases for export classification and legal status.
5. **Combiner.** The suite confirms the precedence policy on requests with multiple simultaneous findings.
6. **Reproducibility.** The suite reruns sampled past decisions after new facts, corrections, and releases, and confirms identical findings.
7. **Counterfactual release.** The team predicts which verdicts a release should change, and the suite compares the prediction with the impact report.
8. **Leakage.** The suite runs section 14 item 5 for every role.
9. **Injection.** The suite plants instructions in documents and confirms that no verdict changes.

## 17. Governance

1. A mapping document shows how each class and SKOS concept would export to Collibra as a business term, how PROV‑O provenance would map to Collibra lineage, and how SHACL reports would map to data quality results, with the matching Collibra REST endpoints.
2. PROV‑O in the graph serves as the system's lineage record.

## 18. Architecture deliverables

1. The HLD contains context, container, and deployment diagrams, including the documented multi AZ design.
2. The LLD specifies rule functions, the combiner policy, SPARQL templates, Cedar policies, action types, the decision record schema, and the ingestion and release state machines.
3. The ADRs in section 13 live in the docs folder.
4. The competency questions document links each question to its query and test.
5. The modeling decisions document explains section 7.3 in plain language.
6. The NFR matrix lists each target, the design that meets it, and the test that proves it.
7. The STRIDE threat model lists threats, mitigations, and residual risk.
8. A 10 slide deck presents the architecture to a customer security board.
9. A five minute demo video follows section 19.4.

## 19. Build plan

### 19.1 Phase A: core loop

1. **Gate 0.** The team completes the two week ontology study plan and writes the competency questions.
2. **Gate 1.** The ontology, SKOS schemes, SHACL shapes, rule functions, combiner, and synthetic generator run on Fuseki. Every competency question, plus the hierarchy, temporal, evidence, combiner, and high risk suites, passes locally. pyLODE documentation resolves at the w3id IRI.
3. **Gate 2.** The data pipeline pulls notices, patents, T2 records, and USPTO legal status, and reports the patent match rate. A thin Ontop endpoint over a Snowflake trial table answers one SPARQL query.
4. **Gate 3.** CDK deploys the VPC, Neptune, KMS, and IAM. The bulk loader loads the graph, and the query service passes every Gate 1 suite on Neptune.
5. **Gate 4.** The ingestion workflow runs with Textract, extraction, SHACL, steward approval through SPARQL UPDATE, and automatic rerun of affected requests.
6. **Gate 5.** The agent service, verdict card, citation checker, Guardrails, and decision records run end to end, and the reproducibility suite passes. The core loop is complete at this gate.

### 19.2 Phase B: enterprise integration

1. **Gate 6.** Cognito, Verified Permissions, and the query service enforce roles, and the leakage suite passes.
2. **Gate 7.** Snowflake integration runs nightly loads, the Ontop exploration endpoint, and verdict writeback.
3. **Gate 8.** The semantic release pipeline produces impact reports, reruns pending requests, and passes the counterfactual suite.

### 19.3 Phase C: evidence and presentation

1. **Gate 9.** The AI value evaluation, load test, and injection suite pass, and the thin NTRS retrieval tool answers with citations.
2. **Gate 10.** The docs folder is complete and the demo video is recorded.

### 19.4 Demo script

1. A licensing manager asks for an exclusive license that overlaps an executed grant, and the card shows Blocked with the R2 finding, the conflicting grant, and its source clause, plus secondary findings for R5 and R7.
2. The manager asks for a nonexclusive license on a patent whose ownership record is incomplete, and the card shows Insufficient evidence from R6.
3. A steward approves a complete ownership record with no co‑owners, the system reruns the request, and the card shows Clear with the changed finding highlighted.
4. The ontology owner narrows a field of use concept, the impact report predicts and confirms one verdict change, and the release reruns a pending request.
5. An agreement containing a planted instruction passes through ingestion, and no verdict changes.
6. The auditor reruns the first decision from its stored context and receives the identical result.

## 20. Scope decisions

1. **Built in full:** the ontology, SKOS schemes, SHACL shapes, rule functions, combiner, Neptune, Bedrock with Strands, steward approval with provenance, bitemporal facts, decision context, the verdict UI, Verified Permissions, Snowflake integration, and the release pipeline.
2. **Built thin:** the Ontop exploration endpoint and the NTRS retrieval tool.
3. **Documented only:** the Collibra mapping, extended lineage, and multi AZ recovery.

## 21. Risks and mitigations

1. **Notices may match few patents.** Notices cite patent and application numbers in mixed formats. The pipeline normalizes both and reports unmatched notices, and Gate 2 sets corpus size from the measured match rate.
2. **USPTO legal status may be incomplete for some patents.** R1 returns UNKNOWN in those cases, which keeps false clearances at zero, and Gate 2 measures how often it happens.
3. **Notices lack terms and royalties.** The synthetic generator fills those fields, and the README marks the boundary.
4. **Extraction may miss or invent facts.** Clause spans, SHACL validation, and steward approval stop bad facts before they reach the approved graph.
5. **Hierarchy edits may change legal outcomes silently.** The release pipeline's impact report and counterfactual suite catch every changed verdict before publication.
6. **Ontology skill gaps may slow Gate 1.** Gate 0 front loads the study plan, and Gate 1 runs entirely on Fuseki before any AWS work.
7. **Neptune idle cost may exceed budget.** Phase A runs locally through Gate 2, and teardown after each AWS session plus a budget alarm control spend afterward.
8. **The Snowflake trial expires after 30 days.** The team starts the trial at Gate 2 for the Ontop proof, completes Gate 7 within the trial window, and records evidence before expiry.

## 22. Omitted

This public copy omits section 22.
