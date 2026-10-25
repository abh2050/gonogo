# GoNoGo UI

A Vite, React, and TypeScript app that shows how the ontology, the data, and the time model fit together.
It draws with D3 (graphs and hierarchies) and Chart.js (charts). Gate 1 ships five views:

| View | What it shows | Library |
|---|---|---|
| Overview | The five verdicts, the seven rules, and how a verdict is made | React, SVG |
| Ontology | All 42 classes as a force-directed graph, with definitions, rules, and modeling decisions | D3 |
| Vocabularies | Fields of use and territories as hierarchies. Pick a grant and a request to see rights coverage | D3 layout, React SVG |
| Data findings | What the real data showed, including 181 lapsed patents that a public snapshot shows alive | Chart.js, D3 |
| Time | The bitemporal model. Drag a recording cutoff and watch the system's belief change | D3 |

Gate 2 adds the request screen, the verdict card, the steward queue, and the release review screen.

## Run it

```bash
cd ui
npm install
npm run dev          # http://localhost:5173
npm run build        # type-checks, then writes dist/
```

The views read JSON from `public/data/`. Regenerate it from the ontology files and the built graph:

```bash
uv run python -m kg.export_viz
```

Every number on screen comes from those files, so a chart and the tests that check the same facts cannot
disagree.

## Links you can share

Each view has a hash route, and some take a parameter:

- `#/ontology?select=Grant` opens the ontology with a class selected
- `#/findings?theme=dark` and any other route accept `theme=light` or `theme=dark`

## Hosting

The repository-root `vercel.json` builds this app as the static site and deploys [api/index.py](../api/index.py)
as one Python function. The function runs the real rule engine over a committed snapshot of the graph
(`api/snapshot/`), so the Ask, Steward, and History views work with no AWS account. The browser holds the
steward's event log and sends it with each call. See [docs/public-demo.md](../docs/public-demo.md).

For local work, run the API beside the dev server; Vite forwards `/api` to it:

```bash
uv run uvicorn api.index:app --port 8000   # from the repository root
cd ui && npm run dev
```
