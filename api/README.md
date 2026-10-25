# api

`index.py` is the GoNoGo API: one FastAPI app that runs locally (`uv run uvicorn api.index:app`) and as the
Vercel function behind the public demo. It serves the rule engine over `snapshot/`, the release, approved, and
candidate graphs as the last build wrote them. The royalty graph is not in the snapshot.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Release, rule versions, combiner policy, graph sizes |
| `GET /api/vocabulary` | Field, territory, and exclusivity concepts for the structured form |
| `GET /api/examples` | Example questions, each with the verdict it reaches |
| `POST /api/parse` | The deterministic parse of a question |
| `POST /api/decide` | Parse (or take a structured request) and decide; with `previous`, also the diff |
| `POST /api/rerun` | Evaluate a stored decision again from its stored cutoff |
| `POST /api/queue` | Candidate facts and proposed identity links that wait for a steward |
| `POST /api/act` | Apply one steward action; returns the new event log and the SPARQL Update |
| `POST /api/provenance` | The graph around one node, two steps out, for the provenance view |

Every POST takes `events`, the steward's event log. The server replays it and keeps no session. Gate 3 puts
the same handlers behind API Gateway with a Cognito authorizer.
