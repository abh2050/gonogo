# Architecture

GoNoGo answers one question: can this company license this patent for this field, territory, and term. Six
diagrams show how it answers, where it runs, and who may touch what. GitHub draws them from the text. The same
pictures, with hover details, are on the [Architecture page](https://gonogo-livid.vercel.app/#/architecture) of the demo.

## 1. From a question to a verdict

Seven deterministic rules decide. A model never does.

```mermaid
flowchart LR
    Q["Question<br/>in plain words"] --> P["Parser<br/>fixed patterns, no model"]
    P -->|"concepts, dates,<br/>and a patent"| V{"Complete?"}
    V -->|"no: lists what is missing"| Q
    V -->|yes| ER["Entity resolution<br/>who is the licensee?"]
    ER --> R["Seven rules<br/>R1 to R7<br/>fixed SPARQL templates"]
    G[("Knowledge graph<br/>release, approved,<br/>bitemporal")] --> R
    R --> C["Combiner<br/>FAIL > PENDING > REVIEW<br/>> UNKNOWN > GO"]
    C --> D["Decision record<br/>signature, cutoff,<br/>facts read"]
    D --> OUT(["GO / NO GO / HOLD /<br/>COUNSEL / NO DATA"])
    CAND[("Candidate graph<br/>proposed facts")] -. "no rule reads it" .- R
    classDef det fill:#e7ecff,stroke:#2f5bff,color:#13171f;
    classDef store fill:#faf9f6,stroke:#8a93a1,color:#13171f;
    class P,ER,R,C,D det;
    class G,CAND store;
```

## 2. Two places it runs

The Vercel demo costs nothing and stays up. The AWS deployment is the same engine on a graph database, behind real
identities, and is switched on for a session.

```mermaid
flowchart TB
    subgraph demo["Public demo: Vercel free tier, always on"]
        B1["Browser<br/>holds the steward's event log"] --> F1["Static app<br/>React, D3, Chart.js"]
        B1 --> FN["One Python function<br/>FastAPI, the same engine"]
        FN --> SNAP[("Frozen graph snapshot<br/>committed to the repo,<br/>no royalty graph")]
        FN --> CED1["Cedar in process<br/>role is typed by the visitor"]
    end
    subgraph aws["AWS deployment: switched on for a session"]
        B2["Browser<br/>signs in with Cognito"] --> CF["CloudFront<br/>one address, HTTPS"]
        CF --> S3UI[("S3<br/>the same static app")]
        CF --> APIGW["API Gateway<br/>verifies the token"]
        APIGW --> ENG["Engine Lambda<br/>the same FastAPI app"]
        APIGW --> QRY["Query Lambda, in the VPC"]
        QRY --> NEP[("Neptune Serverless<br/>46,276 triples")]
        ENG --> CED2["Cedar in process<br/>role is read from the token"]
    end
    SRC["One repository<br/>one rule engine,<br/>one set of Cedar policies"] --> demo
    SRC --> aws
```

## 3. The AWS deployment

![GoNoGo on AWS: the whole system, drawn in draw.io with the AWS icon set](architecture/gonogo-aws-1-overview.png)

This is the first of seven draw.io views: the whole system, the request path, ingestion, security and network, data
and access, the benchmark, and stacks and cost. See [architecture/README.md](architecture/README.md).

106 resources in four stacks, listed one by one in [aws-resources.md](aws-resources.md). Everything is in
us-east-2. The VPC has no NAT gateway and no route to the internet.

```mermaid
flowchart TB
    USER(["Person<br/>one of six roles"])
    subgraph edge["gonogo-ui"]
        CF["CloudFront<br/>HTTPS, strict CSP,<br/>security headers"]
        SITE[("S3 bucket<br/>the built app<br/>private, via OAC")]
    end
    subgraph front["gonogo-api"]
        GW["API Gateway REST<br/>Cognito authorizer<br/>request validation<br/>20 requests a second"]
        ENG["Engine Lambda<br/>1,536 MB, arm64"]
        subgraph vpc["VPC, isolated subnets, no NAT, S3 gateway endpoint"]
            QRY["Query Lambda<br/>read-only Neptune role"]
            LOAD["Loader Lambda<br/>write role, not on the API"]
            NEP[("Neptune Serverless<br/>IAM auth, encrypted<br/>1 to 4 capacity units")]
        end
    end
    subgraph core["gonogo-core"]
        COG["Cognito<br/>six role groups"]
        AVP["Verified Permissions<br/>21 Cedar policies"]
        DDB[("DynamoDB<br/>one row per decision")]
        AUD[("S3 audit bucket<br/>Object Lock, governance")]
        EVB["EventBridge bus"]
        GR[("S3 graph files")]
        KMS["KMS key<br/>rotates yearly"]
    end
    BUD["gonogo-budget<br/>$10, emails at 50 / 80 / 100 percent<br/>survives teardown"]

    USER --> CF
    CF --> SITE
    CF -->|"/api/*, /decide,<br/>/query, /health"| GW
    GW -->|"token checked"| COG
    GW --> ENG
    GW --> QRY
    QRY --> NEP
    LOAD --> NEP
    GR --> LOAD
    ENG --> DDB
    ENG --> AUD
    ENG --> EVB
    AVP -. "same policy text as the<br/>in-process Cedar, 126 of 126 agree" .- ENG
    KMS -. encrypts .- DDB
    KMS -.- AUD
    KMS -.- NEP
```

## 4. The two-person rule

A wrong approval used to turn COUNSEL into GO. Now an approval that conflicts with the record, or that would
move a verdict to GO, waits for counsel.

```mermaid
sequenceDiagram
    autonumber
    actor S as Steward (Ann)
    participant E as Engine
    participant G as Graph copy
    participant C as Cedar
    actor L as Counsel (Dee)
    S->>E: approve the proposed ownership record
    E->>G: apply it to a copy of the store
    G-->>E: conflict: drops co-owner COO-001<br/>upgrade: COUNSEL would become GO
    E->>C: may Ann ApproveFact? (conflict, upgrade)
    C-->>E: no: a flag is set
    E->>C: may Ann SubmitForSecondReview?
    C-->>E: yes: steward-submits-flagged-fact
    E-->>S: held in PENDING_SECOND_REVIEW<br/>no fact added, verdict still COUNSEL
    L->>E: second review: approve
    E->>C: may Dee SecondReview? firstApprover is Ann
    C-->>E: yes: a different counsel
    E->>G: add the fact, with both approvers
    E-->>L: verdict is now GO, and the record shows two names
```

## 5. Where the data comes from and who may read it

Royalty terms and agreement text live in their own graph, and Cedar decides which roles may read each graph.

```mermaid
flowchart LR
    subgraph src["Sources"]
        NASA["NASA patent dataset"]
        FR["Federal Register<br/>92 notices"]
        USPTO["USPTO legal status"]
        SYN["Synthetic generator<br/>labeled, fixed seed"]
        MOD["Language model<br/>proposes fields of use"]
    end
    NASA --> BUILD
    FR --> BUILD
    USPTO --> BUILD
    SYN --> BUILD
    MOD -->|"quote + span<br/>+ model ID"| CAND
    BUILD["Build<br/>SHACL, OWL-RL,<br/>disjointness check"]
    BUILD --> REL[("release<br/>ontology and vocabularies")]
    BUILD --> APP[("approved<br/>facts, bitemporal")]
    BUILD --> CAND[("candidate<br/>waits for a person")]
    BUILD --> ROY[("royalty<br/>terms, agreement text")]
    REL --> LM["Licensing manager"]
    APP --> LM
    REL --> ST["Steward"]
    APP --> ST
    CAND --> ST
    ROY --> CO["Counsel<br/>reads all four"]
    REL --> CO
    APP --> CO
    CAND --> CO
    FIN["Finance analyst<br/>reads no graph, only<br/>the Snowflake table"]
    AUD["Auditor<br/>decision records only"]
```

## 6. Changing what GoNoGo decides

```mermaid
flowchart LR
    A["Author changes a rule,<br/>template, scheme, shape,<br/>or the combiner"] --> I["python -m release impact<br/>builds both trees,<br/>evaluates 45 cases in each"]
    I --> RPT["Impact report<br/>every moved verdict,<br/>every changed finding,<br/>files that could be the cause"]
    RPT --> GATE{"Regression gate<br/>passes?"}
    GATE -->|no| A
    GATE -->|yes| CO["Counsel approves<br/>this report's digest<br/>Cedar: not the proposer"]
    CO --> CI["CI rebuilds the report<br/>and compares digests"]
    CI --> PUB["Ontology owner publishes<br/>Cedar: gate passed and<br/>counsel approved"]
```
