# A tour of GoNoGo

Every picture here is a screenshot of the running app, taken by `scripts/screenshots.py`. Run it again after a
change and the pictures update. The live demo is at [gonogo-livid.vercel.app](https://gonogo-livid.vercel.app).

## The ontology, in motion

![A guided walk through the ontology graph: select a class and its relationships light up and flow along their arrows](screenshots/ontology-walk.gif)

Each dot is an OWL class. Select one and its relationships light up, the dashes move in the direction each arrow
points, and the panel gives its definition, the rules that read it, and the modeling decisions behind it. The walk
above goes from a patent, to a grant, to the field-of-use hierarchy, to the facts a model proposes, to the second
review that a risky approval needs. Find it in the app under **Ontology**, or open a class directly with
`#/ontology?select=Grant`.

![The ontology as a graph of 48 classes](screenshots/02-ontology-graph.png)

## How provenance moves

![A guided walk through provenance: a decision, the approved fact behind it, who proposed it and who approved it](screenshots/provenance-walk.gif)

Start at a decision and follow its edges back: the fact it used, the event that approved it, the person who proposed
it, and the second reviewer. Every node is a real record in the graph.

A narrated four-minute video joins the ontology walk, this provenance walk, the Architecture page, and the AWS diagram: [media/gonogo-overview.mp4](media/gonogo-overview.mp4), with subtitles in
[media/gonogo-overview.srt](media/gonogo-overview.srt). The title clip was generated with Higgsfield from a text
prompt with no words in it, and the title was added afterward. The voice is ElevenLabs text-to-speech reading
[media/narration.json](media/narration.json). Each walk holds a step for exactly as long as its line, and
`scripts/assemble_video.py` places every line at the moment its step appears.

## The benchmark

![The Benchmark page: verdict accuracy, false GOs, and accuracy by question family for four answerers](screenshots/17-benchmark.png)

Two hundred questions, four answerers, one false-GO count that matters. The page charts
[eval/results.md](../eval/results.md); [benchmark.md](benchmark.md) explains the method and what the numbers show.

## How a verdict is made

![The architecture page: a question flows through a parser, entity resolution, seven rules, a combiner, and a decision record](screenshots/06-architecture.png)

The **Architecture** page draws the path from a question to a verdict, the two places the system runs, the AWS
deployment, the two-person rule, and who may read which graph. Point at any box for what it does and where its code
lives.

## Asking a question

The parser underlines what it understood and says what it could not find. It guesses nothing.

![A question with each part underlined: licensee, patent, license type, field, territory, and dates](screenshots/10-ask-parsed.png)

The verdict card gives the rule that decided, the facts it read, and the clause each fact came from.

![A verdict card with seven rule tiles and the evidence for the selected rule](screenshots/11-verdict-card.png)

## A person approves, and sometimes two

A steward's approval of the decoy record drops a co-owner and would turn COUNSEL into GO. It waits for counsel, adds no
fact, and changes no verdict.

![A held approval: the queue shows the conflict and says the approval waits for counsel](screenshots/12-held-for-counsel.png)

Cedar decides who may do what. The grid below is the answer of the policies, not a hand-drawn table.

![Which role may do which action, from 21 Cedar policies](screenshots/13-policy-grid.png)

A different counsel approves, and the verdict moves. The record then names both people.

![The second review: counsel approves and the verdict moves from COUNSEL to GO, with the rule that changed](screenshots/14-second-review-go.png)

Every approved fact has a provenance graph: who proposed it, who approved it, what it replaced, and the activity that made it.

![The provenance graph of an approved fact: the steward, the action, the candidate, and the patent](screenshots/15-provenance-graph.png)

Every decision keeps its context, and the history shows how each verdict moved as evidence arrived.

![The history page: a timeline of verdicts as steward actions arrived](screenshots/16-history.png)

## The data and the vocabularies

![The SKOS field and territory hierarchies](screenshots/03-vocabularies.png)

![What the real public data showed, as charts](screenshots/04-data-findings.png)

![The bitemporal model: drag the recording cutoff and watch the facts a decision could see](screenshots/05-time-model.png)

## The same app on AWS

The AWS deployment serves the same React app from CloudFront. It adds a sign-in page (Cognito), and the Steward page
takes the person and role from the signed-in token instead of a form. Two different users, a steward and a counsel,
play the two-person rule.

![The AWS sign-in page](screenshots/20-aws-sign-in.png)
![The same question decided on the in-process engine and on Neptune, with identical signatures](screenshots/21-aws-neptune-compare.png)
![The architecture page served from CloudFront](screenshots/23-aws-architecture.png)
![A steward approval held for counsel](screenshots/24-aws-held-for-counsel.png)
![Counsel's second review moves the verdict to GO](screenshots/25-aws-second-review-go.png)
