import { useEffect, useState } from "react";
import { api, ROLE_LABEL, VERDICT_CLASS, type AuthzMatrix, type Role, type Verdict } from "../api";
import Diagram, { type DEdge, type DGroup, type DNode } from "../components/Diagram";

// ---- 1. From a question to a verdict -------------------------------------------------------------------------------

const VERDICT_NODES: DNode[] = [
  { id: "q", x: 10, y: 150, w: 120, label: "Question", sub: "plain words", kind: "person", detail: "A licensing manager types who wants which patent, for what field, where, and when." },
  { id: "parse", x: 165, y: 150, w: 140, label: "Parser", sub: "fixed patterns", kind: "step", detail: "Reads concepts, dates, and a patent out of the words, and keeps the span each came from. A part it cannot find is listed as missing, and two different license types are reported, never guessed. No model is involved.", where: "agent/parser.py" },
  { id: "er", x: 340, y: 150, w: 140, label: "Who is the licensee?", sub: "entity resolution", kind: "step", detail: "Compares the typed name with every company in the graph after removing legal suffixes. It proposes matches and links nothing: only a steward's approval writes owl:sameAs.", where: "er/resolver.py" },
  { id: "rules", x: 515, y: 80, w: 160, h: 200, label: "Seven rules", sub: "R1 to R7", kind: "step", detail: "R1 patent in force. R2 overlapping grants. R3 co-exclusive cap. R4 notice window. R5 export control. R6 co-owner consent. R7 statutory review. Each fills fixed SPARQL templates, and every rule runs on every request.", where: "rules/, rules/templates/" },
  { id: "graph", x: 515, y: 335, w: 160, label: "Knowledge graph", sub: "release + approved", kind: "store", detail: "The ontology, the SKOS vocabularies, and the approved facts, each with a recording time, a source clause, and an approver. A rule sees the graph as it stood at the decision's cutoff.", where: "kg/build.py, ontology/" },
  { id: "cand", x: 300, y: 335, w: 160, label: "Candidate graph", sub: "waits for a person", kind: "store", dashed: true, detail: "Proposed facts, including a model's proposals. No rule reads this graph, so a proposal cannot change a verdict until a person approves it.", where: "kg/actions.py" },
  { id: "comb", x: 725, y: 150, w: 130, label: "Combiner", sub: "versioned policy", kind: "step", detail: "FAIL gives NO GO. Otherwise PENDING gives HOLD, REVIEW gives COUNSEL, UNKNOWN gives NO DATA. Only when every applicable rule passes is the verdict GO.", where: "config/precedence.yaml" },
  { id: "rec", x: 890, y: 150, w: 140, label: "Decision record", sub: "reproducible", kind: "step", detail: "Stores the request, the recording cutoff, the release, every rule version, the facts each rule read, and a signature over the findings. Rerunning it from the cutoff gives the same answer.", where: "rules/decision.py" },
  { id: "out", x: 890, y: 30, w: 140, label: "Verdict", sub: "five outcomes", kind: "person", detail: "GO, NO GO, HOLD, COUNSEL, or NO DATA, with the rule that decided and the clause behind each fact." },
];
const VERDICT_EDGES: DEdge[] = [
  { from: "q", to: "parse" },
  { from: "parse", to: "er" },
  { from: "er", to: "rules" },
  { from: "graph", to: "rules", label: "SPARQL" },
  { from: "cand", to: "rules", dashed: true, label: "never read" },
  { from: "rules", to: "comb" },
  { from: "comb", to: "rec" },
  { from: "rec", to: "out" },
];

// ---- 2. The AWS deployment ----------------------------------------------------------------------------------------------

const AWS_NODES: DNode[] = [
  { id: "user", x: 10, y: 270, w: 110, label: "Person", sub: "one of six roles", kind: "person", detail: "Signs in with a user name and password. Cognito puts exactly one role group in the token." },
  { id: "cf", x: 160, y: 270, w: 130, label: "CloudFront", sub: "one address", kind: "service", detail: "Serves the app and the API from one host over HTTPS, so the API needs no CORS. It adds security headers and a strict content security policy. On its default domain it cannot require TLS 1.2; only a custom domain can.", where: "infra/stacks.py (UiStack)" },
  { id: "site", x: 160, y: 120, w: 130, label: "S3: the app", sub: "private", kind: "store", detail: "The built React app and a config.json that the deploy writes. The bucket is private, and only this CloudFront distribution may read it.", where: "ui/" },
  { id: "gw", x: 340, y: 270, w: 140, label: "API Gateway", sub: "token check", kind: "service", detail: "Verifies the Cognito token on every method, rejects oversize and malformed bodies, and throttles at 20 requests a second. A request with no token gets a 401 before any code runs.", where: "infra/stacks.py (ApiStack)" },
  { id: "cog", x: 340, y: 120, w: 140, label: "Cognito", sub: "six role groups", kind: "control", detail: "The user directory. One group per role, admin-created users only. A user in two groups is refused so nobody can play both parts of a two-person rule.", where: "service/identity.py" },
  { id: "eng", x: 540, y: 190, w: 150, label: "Engine Lambda", sub: "same app as the demo", kind: "service", detail: "The FastAPI app of api/index.py behind Mangum. It reads the user and role from the token, runs the steward loop, and writes each decision to DynamoDB and S3.", where: "service/engine_lambda.py" },
  { id: "avp", x: 540, y: 40, w: 150, label: "Verified Permissions", sub: "21 Cedar policies", kind: "control", dashed: true, detail: "Holds the same policy text that the Lambdas evaluate in process. A check compares 126 answers from each and they match. Running Cedar in process avoids interface endpoints and their cost.", where: "authz/policies/gonogo.cedar" },
  { id: "qry", x: 540, y: 410, w: 150, label: "Query Lambda", sub: "read-only", kind: "service", detail: "The only path to Neptune. It validates each query, asks Cedar which graphs the caller may read, and puts those graphs in the FROM clauses. Its Neptune role cannot write.", where: "service/handler.py, service/query.py" },
  { id: "load", x: 740, y: 410, w: 130, label: "Loader Lambda", sub: "write, no route", kind: "service", detail: "Writes the graphs into Neptune. It alone holds write permissions, and no API route reaches it.", where: "service/handler.py" },
  { id: "nep", x: 740, y: 520, w: 160, label: "Neptune Serverless", sub: "46,276 triples", kind: "store", detail: "The graph database. IAM authentication, encrypted with the project key, scaling between 1 and 4 capacity units. The one resource that bills while idle.", where: "infra/stacks.py" },
  { id: "ddb", x: 760, y: 120, w: 130, label: "DynamoDB", sub: "decisions", kind: "store", detail: "One summary row per decision, with point-in-time recovery.", where: "service/audit.py" },
  { id: "aud", x: 760, y: 200, w: 130, label: "S3 audit", sub: "Object Lock", kind: "store", detail: "A tamper-evident copy of each decision in governance-mode Object Lock.", where: "service/audit.py" },
  { id: "evb", x: 760, y: 280, w: 130, label: "EventBridge", sub: "actions", kind: "service", detail: "The engine publishes fact-approved and action events here.", where: "service/audit.py" },
  { id: "kms", x: 940, y: 200, w: 120, label: "KMS key", sub: "rotates yearly", kind: "control", detail: "Encrypts the audit bucket, the table, Neptune, and the graph files.", where: "infra/stacks.py" },
];
const AWS_EDGES: DEdge[] = [
  { from: "user", to: "cf" },
  { from: "cf", to: "site" },
  { from: "cf", to: "gw", label: "/api, /decide, /query" },
  { from: "gw", to: "cog", label: "token" },
  { from: "gw", to: "eng" },
  { from: "gw", to: "qry" },
  { from: "qry", to: "nep" },
  { from: "load", to: "nep" },
  { from: "eng", to: "ddb" },
  { from: "eng", to: "aud" },
  { from: "eng", to: "evb" },
  { from: "avp", to: "eng", dashed: true, label: "same policies" },
  { from: "kms", to: "aud", dashed: true },
];
const AWS_GROUPS: DGroup[] = [{ x: 515, y: 370, w: 410, h: 215, label: "VPC: isolated subnets, no NAT, no internet route" }];

// ---- 3. The two-person rule -----------------------------------------------------------------------------------------------

const STEPS: { who: string; text: string; verdict: Verdict; refuse?: boolean }[] = [
  { who: "Steward Ann", text: "Approves a proposed ownership record. It leaves out co-owner COO-001, whom the approved record lists.", verdict: "COUNSEL" },
  { who: "Engine", text: "Applies it to a copy of the graph and finds two things: it conflicts with the approved record, and it would move this question from COUNSEL to GO.", verdict: "COUNSEL" },
  { who: "Cedar", text: "Ann may not approve alone when a flag is set. She may submit for second review. The approval waits, adds no fact, and changes no verdict.", verdict: "COUNSEL" },
  { who: "Steward Ben", text: "Tries to give the second approval. Refused: a second review is counsel's.", verdict: "COUNSEL", refuse: true },
  { who: "Ann, as counsel", text: "Tries the second review herself. Refused: the first approver cannot also be the second.", verdict: "COUNSEL", refuse: true },
  { who: "Counsel Dee", text: "Approves the held approval. The fact enters the approved graph with both names, and the verdict moves.", verdict: "GO" },
];

// ---- 4. Who may read what ---------------------------------------------------------------------------------------------------

function GraphAccess() {
  const [m, setM] = useState<AuthzMatrix | null>(null);
  useEffect(() => {
    api.authz().then(setM).catch(() => undefined);
  }, []);
  if (!m) return <p className="muted">Loading the policy answers…</p>;
  const rows = m.rows.filter((r) => /^Read the .* graph$/.test(r.label));
  return (
    <div className="authz-wrap">
      <table className="authz" aria-label="Which role may read which graph">
        <thead>
          <tr>
            <th scope="col">Graph</th>
            {m.roles.map((r: Role) => (
              <th key={r} scope="col">
                {ROLE_LABEL[r]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <th scope="row">{row.label.replace("Read the ", "").replace(" graph", "")}</th>
              {m.roles.map((r: Role) => (
                <td key={r} className={row.allowed[r] ? "yes" : "no"}>
                  <span aria-label={row.allowed[r] ? "may read" : "may not read"}>{row.allowed[r] ? "●" : "·"}</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Architecture() {
  return (
    <div className="page">
      <header className="page-head">
        <div className="eyebrow">Architecture</div>
        <h1>How GoNoGo is put together</h1>
        <p className="lede">
          Seven deterministic rules decide every verdict from a knowledge graph. A language model may propose a fact, but a
          person approves it, and no rule reads a proposal. The same engine runs in two places: free on Vercel for anyone
          to try, and on AWS for a session, behind real identities and a graph database. Point at any box.
        </p>
      </header>

      <section className="section">
        <h2>From a question to a verdict</h2>
        <Diagram nodes={VERDICT_NODES} edges={VERDICT_EDGES} width={1060} height={430} label="A question flows through a parser, entity resolution, seven rules over the graph, a combiner, and a decision record to a verdict." />
      </section>

      <section className="section">
        <h2>Two places it runs</h2>
        <div className="grid cols-2">
          <article className="card">
            <h3>The public demo</h3>
            <p>
              <strong>Lives on Vercel's free tier</strong> and stays up with no AWS account behind it. A static React app and
              one Python function run the real engine over a frozen graph snapshot. Your browser holds the steward's event
              log, and the function stores nothing. The role is typed by the visitor, so it shows how the policies work and
              not who someone is.
            </p>
            <p className="muted small">Cost: nothing. No model is called.</p>
          </article>
          <article className="card">
            <h3>The AWS deployment</h3>
            <p>
              <strong>Lives on CloudFront and S3</strong>, with the API behind it. The same app, the same engine, and the same
              Cedar policies, but the role comes from a Cognito token, the graph sits in Neptune, and every decision is
              written to DynamoDB and a locked S3 bucket. It is switched on for a session and torn down after.
            </p>
            <p className="muted small">Cost: Neptune bills while it exists, about $0.16 per capacity unit-hour.</p>
          </article>
        </div>
      </section>

      <section className="section">
        <h2>The AWS deployment</h2>
        <p className="muted">106 resources in four stacks. The full list, with what each one costs while idle, is in docs/aws-resources.md.</p>
        <Diagram nodes={AWS_NODES} edges={AWS_EDGES} groups={AWS_GROUPS} width={1080} height={600} label="A person reaches CloudFront, which serves the app from S3 and passes API calls to API Gateway. Gateway checks the Cognito token and calls the engine Lambda or the query Lambda, which reads Neptune inside a VPC." />
      </section>

      <section className="section">
        <h2>The two-person rule</h2>
        <p className="muted">
          An approval that conflicts with the record, or that would move a verdict from COUNSEL or NO GO to GO, needs counsel
          as well. Nobody approves a fact they proposed.
        </p>
        <ol className="timeline">
          {STEPS.map((s, i) => (
            <li key={s.text} className={s.refuse ? "refuse" : ""}>
              <span className="num">{i + 1}</span>
              <div>
                <div className="who">{s.who}</div>
                <div>{s.text}</div>
              </div>
              <span className={`chip ${VERDICT_CLASS[s.verdict]}`}>{s.verdict}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="section">
        <h2>Who may read which graph</h2>
        <p className="muted">
          Royalty terms and agreement text live in their own graph. The query service puts only the graphs a role may read
          into each query, and these answers come straight from the Cedar policies.
        </p>
        <GraphAccess />
      </section>
    </div>
  );
}
