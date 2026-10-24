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

`vercel.json` configures a Vercel static deployment with `ui/` as the root directory. The build needs no
server and no AWS account. Gate 3 adds a snapshot mode in which the same rule engine runs on a Vercel function,
so the request, steward, and release views keep working after the AWS stack is torn down. See
[docs/public-demo.md](../docs/public-demo.md).
