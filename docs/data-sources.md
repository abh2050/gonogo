# Data sources

GoNoGo uses five real public sources and one synthetic generator. Each ingestion module caches every raw
response under `data/raw/<source>/` in an envelope that records the URL, parameters, HTTP status, and
retrieval timestamp. A second run reads the cache and makes no network calls, so every module is
idempotent. `--refresh` fetches again. The first full retrieval ran on 2026-10-24.

`python -m ingest all` runs the steps in this order: patents, Federal Register, scope pass 1, T2 portal,
scope pass 2, USPTO, scope pass 3, NTRS.

## Record counts

`python -m gonogo.counts` writes this table from the metadata files, and a unit test fails when the table
and the data disagree.

<!-- counts:start -->
| Source | Measure | Count |
|---|---|---:|
| NASA Patents, JSON file named in the spec | rows | 1,000 |
| NASA Patents, full CSV export | rows | 1,393 |
| NASA Patents, processed | patents | 1,393 |
| NASA Patents, processed | with a patent number | 936 |
| NASA Patents, processed | with an expiration date | 1,043 |
| Federal Register | Intent to Grant notices, 2018 to today | 92 |
| Federal Register | notices with a licensee extracted | 91 |
| Federal Register | notices with an objection deadline | 91 |
| Federal Register | notices that state a field of use | 24 |
| Federal Register | notices that match any patent | 48 |
| T2 portal | technologies at the three centers | 289 |
| T2 portal | technologies with patent numbers | 226 |
| T2 portal | technologies with a stated TRL | 119 |
| Scope | patents in scope | 300 |
| Scope | patents in scope from the NASA dataset | 240 |
| Scope | patents in scope from the T2 portal | 60 |
| Scope | patents in scope that USPTO shows in force | 170 |
| Scope | patents in scope that USPTO shows lapsed for unpaid fees | 77 |
| Scope | patents in scope with no USPTO record | 28 |
| Scope | notices in scope | 41 |
| USPTO | candidate patents checked at the three centers | 724 |
| USPTO | candidates with a USPTO record | 631 |
| USPTO | candidates in force | 170 |
| USPTO | candidates lapsed for unpaid maintenance fees | 377 |
| USPTO | candidates the NASA dataset calls in force but USPTO shows lapsed | 181 |
| USPTO | candidates the NASA dataset lists as applications that USPTO has granted | 208 |
| USPTO | candidates reinstated after a lapse | 5 |
| USPTO | candidates with a recorded co-assignee besides NASA | 96 |
| NTRS | in-scope patents with at least one related report | 121 |
| NTRS | unique reports | 172 |
| NTRS | patent-report links with a downloaded PDF | 218 |
| Synthetic | executed agreements (PDF and text) | 120 |
| Synthetic | agreements seeded from real notices | 41 |
| Synthetic | proposed grants for rule cases | 7 |
| Synthetic | ownership records | 274 |
| Synthetic | ownership records that list real USPTO co-assignees | 52 |
| Synthetic | consent records | 60 |
| Synthetic | export classifications | 265 |
| Synthetic | filing dates | 15 |
| Synthetic | clearance requests | 43 |
| Synthetic | injected cases with expected verdicts | 44 |
<!-- counts:end -->

## 1. NASA Patents dataset (data.nasa.gov, gquh-watm)

- **Module:** `ingest/nasa_patents.py`
- **Spec URL:** `https://data.nasa.gov/docs/legacy/NASA_Patents/gquh-watm.json`
- **URL used as the source of record:** `https://data.nasa.gov/docs/legacy/NASA_Patents/NASA_Patents_rows.csv`

The JSON file named in the spec returns exactly 1,000 rows, which is the default page size of the old
Socrata API. The data.nasa.gov catalog (CKAN `package_search?q=gquh-watm`) lists four exports of the same
dataset. The CSV export holds 1,393 rows, so the JSON file is truncated. The module downloads both files,
records the truncation in `data/processed/nasa_patents.meta.json`, and uses the CSV. The catalog reports a
last modification date of 2025-05-29, which matches the May 2025 snapshot date in the spec.

The snapshot is older than its modification date suggests. The highest patent number in it is 8,679,642,
which the USPTO issued in 2014. Most Federal Register notices since 2018 cite newer patents, so the module
alone cannot match most notices. Section 3 describes how scope handles this gap.

The module normalizes three identifiers. Patent numbers lose commas and kind codes, and the placeholder
"0" becomes empty. Application serials become eight digits, so `13/033,085` becomes `13033085`. NASA case
numbers keep their suffixes, so `ARC-14231-2DIV` stays distinct from `ARC-14231-1`.

## 2. Federal Register notices

- **Module:** `ingest/federal_register.py`
- **Endpoint:** `https://www.federalregister.gov/api/v1/documents.json`
- **Query:** agency `national-aeronautics-and-space-administration`, type `NOTICE`, term `"Intent to Grant"`,
  publication date from 2018-01-01 to the run date.

The search returned 92 notices. The module downloads each notice's full text from `raw_text_url`, removes
the HTML wrapper and the `[[Page N]]` markers, and rejoins identifiers that the printed page split across
lines. Each extracted value keeps the character span of the text it came from, measured against the
cleaned text stored in the record.

Every notice is a **proposed** grant. A notice announces NASA's intent to grant a license and opens an
objection window. It does not prove that a license exists, so the module types every record as
`ProposedGrant`.

The extractors read these fields:

| Field | Rule |
|---|---|
| Patent numbers, application serials, case numbers | Pattern match over the whole notice. Case numbers must start with a NASA center prefix. |
| Exclusivity | Read from the grant sentence, never from the title. The title always says "Exclusive License", even when the notice grants a partially exclusive license. Since 2021 most notices offer "an exclusive, co-exclusive, or partially exclusive" license; the module records these as `unspecified` with the three options. |
| Territory | The phrase after "license in". |
| Licensee and address | The name between the last "to" and "having its principal place of business". |
| Field of use | The text after "fields of use may be limited to". Each notice gets a `field_of_use_status`: `stated`, `limited_unspecified` when the notice says only "The fields of use may be limited.", or `not_mentioned`. |
| Objection deadline | A stated date ("no later than March 23, 2022"), or the publication date plus the stated number of days ("within fifteen (15) days"). The record names the basis. |
| Joint ownership | A flag when the notice licenses NASA's "undivided interest" in a "jointly-owned" invention. R6 uses this signal. |
| Correction | A flag when the notice corrects an earlier notice. |

`tests/unit/test_federal_register.py` checks the extractors against eight real notices. A person read each
notice and wrote the expected values by hand.

## 3. Scope

- **Module:** `ingest/scope.py`

A notice matches a patent when one of its patent numbers, application serials, or case numbers equals the
patent's normalized value. A case number also matches on its family root (`LAR-18232-1` matches
`LAR-18232-2`). The scope file labels that weaker match `case_family`.

Pass 1 ranks centers by the number of notices that match a patent in the NASA dataset and keeps the top
three: Langley, Kennedy, and Glenn. Pass 2 runs after the T2 module and adds every T2 patent at those
centers that a notice names but the NASA dataset lacks. The user approved this addition on 2026-10-24
because the NASA dataset stops around 2014. With the T2 patents, the share of notices that match a patent
rose from 33 percent to 52 percent.

Scope then keeps every matched patent at the three centers and fills the remaining places, up to 300, with
issued patents from the NASA dataset. A patent counts as issued when the NASA dataset says "Issued" or
USPTO shows a grant, because USPTO has since granted 208 of the applications in the NASA snapshot. Pass 3
runs after the USPTO module, and its fill takes patents that USPTO shows in force first, because a
licensing office mostly clears requests on live patents. Lapsed and expired patents still enter scope
through notice matches and through the rest of the fill, so R1 has real failures to find. The fill spreads
patents evenly across the three centers.

Output: `data/scope/patents_in_scope.csv`, `data/scope/notices_in_scope.txt`, and
`data/scope/scope.meta.json`, which also lists every unmatched notice.

## 4. NASA Technology Transfer portal

- **Module:** `ingest/t2_portal.py`
- **Spec endpoint:** `https://technology.nasa.gov/api/1.0/patent/search/{query}` returns **HTTP 404**.
- **Endpoint that worked:** `https://technology.nasa.gov/api/api/patent/{query}` for search, plus the portal
  detail page `https://technology.nasa.gov/patent/{TOPS id}`.

A search on a center prefix (`LAR`, `LEW`, `KSC`) lists every technology record for that center. Each
search row carries the TOPS id, title, abstract, category, and center code, but not the case or patent
numbers. The module therefore reads each technology's detail page, which labels the category, case
numbers, and patent numbers in named HTML spans. The detail page has no TRL field. The module reads TRL
only when the technology description states it ("TRL of 5"), and leaves it empty otherwise.

A detail page lists case numbers and patent numbers without pairing them. When scope adds a T2 patent, it
records a case number only when the page lists exactly one.

The T2 categories seed the top level of the field-of-use hierarchy in `synth/templates/fields.yaml`.

## 5. NASA Technical Reports Server

- **Module:** `ingest/ntrs.py`
- **Search:** `POST https://ntrs.nasa.gov/api/citations/search`
- **Files:** `GET https://ntrs.nasa.gov/api/citations/{id}/downloads`

For each in-scope patent, the module searches NTRS with the content words of the patent title. It keeps up
to three reports whose titles share at least two content words with the patent title. It downloads one PDF
per kept report when NTRS offers one, up to 300 PDFs in total. Gate 4 indexes these reports for the
retrieval tool. The relevance filter is lexical, so the Gate 4 benchmark reports citation precision on
this corpus rather than assuming every link is correct.

## 6. Synthetic augmentation

- **Module:** `synth/generator.py`, run with `python -m synth --seed 42`
- **Output:** `data/synthetic/`, with SHA-256 hashes of every file in `manifest.json`

NASA does not publish executed license agreements, consent records, or export classifications, and no
public source states that a patent's ownership is complete. The generator creates these facts from a
fixed seed, and the same seed always produces the same bytes, including the PDFs.

The generator never contradicts a real fact. When USPTO records a co-assignee besides NASA, the synthetic
ownership record lists that real co-assignee (prefixed `USPTO:`) instead of claiming that NASA owns the
patent alone. The generator writes synthetic filing dates only for patents that have neither a USPTO
record nor an expiration date. Test cases that need a live patent use only patents that USPTO shows in
force.

| File | Contents |
|---|---|
| `agreements.jsonl`, `agreements/AGR-*.pdf`, `agreements/AGR-*.txt` | Executed agreements with numbered clauses. Each record lists each clause's character span in the text file and maps each fact to its clause. Royalty terms sit in a separate `confidential` block for the royalty named graph. |
| `proposed_grants.jsonl` | Synthetic proposed grants for the R2 and R4 rule cases. |
| `ownership.jsonl`, `consents.jsonl` | Ownership records that are complete with co-owners, complete with no co-owners, or incomplete. Co-owners are real USPTO co-assignees where USPTO records one, and fictional otherwise. Some patents have no record at all. Every consent is synthetic. |
| `export_classifications.jsonl` | Unrestricted, or restricted with a list of permitted countries. Some patents have no classification. |
| `filing_dates.jsonl` | Filing dates for some patents that have no USPTO record and no expiration date, so R1 can derive one. |
| `requests.jsonl` | Clearance requests in plain language and in structured form. |
| `candidate_facts.jsonl` | A proposed fact that a steward approves in the Gate 2 rerun demonstration. |
| `injected_conflicts.json` | Every injected case, with the expected status of each rule it asserts and the expected verdict. R1 cases built on real USPTO facts carry a `real_fact_source` link. |

**How the injected cases stay trustworthy.** A person wrote each case's expected statuses and verdict by
hand in `build_cases()`. The generator never runs rule logic to produce them. A unit test checks that each
hand-written verdict follows the GoNoGo precedence, and another test checks that no background agreement
touches a patent that an injected case controls.

**How synthetic data stays visible.** Every synthetic record carries `"synthetic": true` and
`"generated_by": "https://w3id.org/gonogo/synth/generator/v0.1"`. Gate 1 turns that label into
`prov:wasGeneratedBy`. Every synthetic agreement prints "SYNTHETIC DOCUMENT" on its first page.

**Why licensees are fictional.** Forty-one agreements are seeded from real notices. Each one copies the
notice's patents, exclusivity, field of use, and territory, starts 60 days after the objection deadline,
and links back to the notice. Each one names a fictional licensee instead of the company in the notice,
because a public repository should not claim that a real company holds a license it may not hold. A unit
test checks that no fictional name matches a real notice licensee. The fictional names come with spelling
variants, such as "Orbital Lens Works, Inc." and "ORBITAL LENS WORKS INCORPORATED", for the Gate 2 entity
resolver.

## 7. USPTO Open Data Portal

- **Module:** `ingest/uspto.py`
- **Endpoints:** `GET https://api.uspto.gov/api/v1/patent/applications/{application number}`, its
  `/continuity` sub-resource, and `GET .../applications/search` with
  `q=applicationMetaData.patentNumber:{number}` for patents that have only a patent number.
- **Access:** a free Open Data Portal API key, read from `USPTO_API_KEY` in the environment or the
  git-ignored `.env` file. The key travels as the `X-API-KEY` header and never enters the cache.
- **Retired sources:** PatentsView search, the old assignment API, the old bulk data server, and PEDS no
  longer resolve in DNS. The Open Data Portal is the only working source.

The user first chose to skip USPTO, then reversed that choice on 2026-10-24 after a spot check found that
US 8,077,103, which the NASA dataset lists as in force until 2027, lapsed for unpaid maintenance fees on
2019-12-13.

**What the module reads.** One application record returns the current status, filing and grant dates,
the patent term adjustment in days, the prosecution event history, and the recorded assignments. The
continuity record lists parent applications. The module computes the expiration date as the earliest
non-provisional filing date plus 20 years plus the term adjustment. For applications filed before
1995-06-08, it uses the later of filing plus 20 years and grant plus 17 years. The computation ignores
terminal disclaimers, which can shorten a term, so the record flags every patent that has one.

**How it classifies legal state.** The module assigns one state per patent, as of 2026-11-01:

| State | Rule |
|---|---|
| `lapsed` | The history has an `EXP.` event (expired for unpaid maintenance fees) and no later `PMFG` event (petition granted to accept the late fee). |
| `in_force` | The patent was granted, has not lapsed, and the computed term runs past 2026-11-01. |
| `term_ended` | The patent was granted, has not lapsed, and the computed term ended before 2026-11-01. |
| `abandoned`, `not_granted` | No grant date exists. |

Five patents lapsed and were later reinstated after a late fee payment. The module records the lapse
period for each one, because third parties may hold intervening rights for acts during that window
(35 U.S.C. 41(c)). These records give the bitemporal model a real retroactive change.

**Which patents it reads.** The module reads every NASA dataset patent at the three scope centers, plus
the T2 patents in scope, so that scope pass 3 can prefer live patents. It finds a record for most of
them. The ones it misses are mostly T2 provisional-only case numbers and old Kennedy filings that the
Open Data Portal does not hold.

**What it changes for the rules.**
- R1 reads the USPTO state first and falls back to the NASA expiration date only when USPTO has no record.
- R6 reads real co-assignees. An assignee such as the National Institute of Aerospace or Purdue Research
  Foundation is real evidence of joint ownership. Consent records stay synthetic, and a missing
  assignment still does not prove sole ownership.

**What it does not change.** USPTO does not publish executed licenses in usable form, so R2 and R3 still
run on synthetic agreements. R5 still runs on synthetic export classifications.

## AWS model discovery

`python -m gonogo.preflight` makes two read-only calls with profile `awsnew` in `us-east-2`:
`sts:GetCallerIdentity` and `bedrock:ListInferenceProfiles`. It invokes no model. On 2026-10-24 it found
`us.` and `global.` inference profiles for the Claude Opus, Sonnet, Haiku, and Fable families. The code
selects the newest `us.` profile in the family named in `config/aws.yaml` (Sonnet). On that date it
selected `us.anthropic.claude-sonnet-5-5`. No model ID is hardcoded.
