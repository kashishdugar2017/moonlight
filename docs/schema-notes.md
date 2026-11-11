# Schema notes: what Open Targets really sends back

Ticket 1.1. Probed on 2026-11-10 against the live API
(API version 26.9.0, data release 26.09), for our golden disease
`MONDO_0015924`, pulmonary arterial hypertension (PAH).

Every field name below was read from a saved response in `fixtures/`, not from
memory. To rerun the probe: `python3 scripts/probe_schema.py`. To check the
saved files: `python3 scripts/check_fixtures.py`.

## The short version

- The golden disease exists under exactly the id we expected.
- Open Targets changed its drug data. The old doors called `knownDrugs`,
  `isApproved` and `maximumClinicalTrialPhase` are **gone**. The new door is
  called `drugAndClinicalCandidates`, and "phase" is now a word
  (`"APPROVAL"`, `"PHASE_3"`), not a number.
- PDE5A is target number 15 of 4,549, so it is not in the top 10. The probe
  fetched it as the extra target.
- Sildenafil appears in three places, and under **two different ids**
  (plain sildenafil and sildenafil citrate). They disagree about PAH. This is
  the biggest surprise and it matters for filter.py. See "Surprises" below.

## What is saved, and where

Each call has two files side by side: `X.request.json` is the exact body that
was sent (the query text and its variables), and `X.response.json` is what
came back. The response is untouched except for line breaks and indenting, so
people can read it.

| Files in `fixtures/` | What it is |
|---|---|
| `schema/types` | The API's own description of the 22 types we read from |
| `MONDO_0015924/disease` | The disease record |
| `MONDO_0015924/associated_targets` | Top 25 targets with scores |
| `MONDO_0015924/target_drugs/<rank>_<symbol>_<id>` | Drugs acting on one target. 11 files: ranks 01 to 10, plus 15 (PDE5A) |
| `MONDO_0015924/disease_drugs` | Drugs already linked to PAH itself (118) |

## Real field names

### Disease (`disease(efoId: ...)`)

The argument is called `efoId` even though our id starts with `MONDO_`.

| Field | What we got |
|---|---|
| `id` | `"MONDO_0015924"` |
| `name` | `"pulmonary arterial hypertension"` |
| `description` | one paragraph of text |
| `synonyms` | a list of groups, each `{relation, terms}`. Relations seen: `hasExactSynonym`, `hasRelatedSynonym`, `hasNarrowSynonym`, `hasBroadSynonym` |
| `dbXRefs` | 14 ids in other catalogues, like `"EFO:0001361"` |
| `parents` | 1: `MONDO_0005149` pulmonary hypertension |
| `children` | 6, for example idiopathic PAH and heritable PAH |
| `ancestors`, `descendants` | lists of plain ids (11 and 20) |
| `therapeuticAreas` | cardiovascular disorder, phenotype |
| `obsoleteTerms` | old ids that now point here: `EFO_0001361`, `EFO_0001362` |

### Targets for a disease (`disease.associatedTargets`)

Ask with `page: {index: 0, size: 25}`. Both parts of `page` are required.

| Field | Meaning |
|---|---|
| `count` | how many targets exist in total (4,549) |
| `rows[].score` | the overall score, 0 to 1. Rows arrive highest first |
| `rows[].target.id` | Ensembl id, like `"ENSG00000138735"` |
| `rows[].target.approvedSymbol` | short name, like `"PDE5A"` |
| `rows[].target.approvedName` | long name |
| `rows[].target.biotype` | `"protein_coding"` for all 25 |
| `rows[].datatypeScores[]` | `{id, score}` per kind of evidence. Ids seen: `genetic_association`, `genetic_literature`, `literature`, `animal_model`, `clinical` |
| `rows[].datasourceScores[]` | `{id, score}` per data source. Ids seen include `europepmc`, `clinical_precedence`, `orphanet`, `eva`, `impc` |
| `rows[].novelty` | a small number about how new the link is |

A kind of evidence that is missing for a target is simply not in the list. It
is not sent as zero.

### Drugs acting on a target (`target.drugAndClinicalCandidates`)

It takes no paging. It sends every row at once (`count` matched the number of
rows in all 11 files).

| Field | Meaning |
|---|---|
| `rows[].drug.id` | ChEMBL id, like `"CHEMBL192"` |
| `rows[].drug.name` | in capitals, like `"SILDENAFIL"` |
| `rows[].drug.drugType` | `"Small molecule"`, `"Protein"`, `"Antibody"` |
| `rows[].drug.maximumClinicalStage` | **the drug's best stage for any disease** |
| `rows[].drug.parentMolecule` | `{id, name}` if this is a salt form of another drug, otherwise `null` |
| `rows[].drug.mechanismsOfAction.rows[]` | see "Where action type lives" |
| `rows[].drug.indications.rows[]` | **every disease the drug is linked to**: `{id, maxClinicalStage, disease {id, name}}` |
| `rows[].maxClinicalStage` | a stage for this drug-and-target pair. Do not use it. See Surprises |
| `rows[].diseases[]` | `{diseaseFromSource, disease}`. The disease is `null` for 535 of 1,268 entries, where the trial's wording could not be matched to a catalogue id |
| `rows[].clinicalReports[]` | the trials and labels behind the row: `source`, `provider`, `origin`, `clinicalStage`, `url` (every saved report has a `url`), and more |

### Drugs already linked to the disease (`disease.drugAndClinicalCandidates`)

Also no paging. 118 rows for PAH.

| Field | Meaning |
|---|---|
| `rows[].drug` | same shape as above |
| `rows[].maxClinicalStage` | how far this drug got **for this disease** |
| `rows[].clinicalReports[]` | the evidence, with `source` and `url` |

## Where action type lives

`drug.mechanismsOfAction.rows[].actionType`.

One drug can have several mechanism rows, for several targets. Each row says
which targets it is about in `rows[].targets[].id`. So to learn what a drug
does to *our* target, take only the rows whose `targets` include our target's
id. Do **not** use `uniqueActionTypes`: it mixes all the drug's targets
together. Example: pentoxifylline is listed as `["ANTAGONIST", "INHIBITOR"]`
overall, but for PDE5A it is only `INHIBITOR`.

Action types seen in our 11 targets: `INHIBITOR`, `ANTAGONIST`, `BLOCKER`
(these turn the protein down), `AGONIST`, `OPENER` (these turn it up). Other
drugs showed `POSITIVE MODULATOR` and `POSITIVE ALLOSTERIC MODULATOR` on other
targets. The schema says `actionType` may be empty, though none was empty here.

The row also has `mechanismOfAction` (a sentence like "Phosphodiesterase 5A
inhibitor"), `targetName`, and `references[]` with `source`, `ids`, `urls`.

## Where clinical phase lives

There are three, and they mean different things. Think of a swimmer: their
best race ever, their best race in one pool, and one single race.

1. `drug.maximumClinicalStage`: the drug's best stage for any disease.
   `"APPROVAL"` here is how we know a medicine is approved somewhere.
2. `maxClinicalStage` on a disease row or an indication row: how far the drug
   got for that one disease.
3. `clinicalReports[].clinicalStage`: the stage of one single trial or label.

Values seen: `APPROVAL`, `PHASE_4`, `PHASE_3`, `PHASE_2_3`, `PHASE_2`,
`PHASE_1_2`, `PHASE_1`, `EARLY_PHASE_1`, `WITHDRAWAL`, `UNKNOWN`. They are
words, so the code will need its own ordered list to compare them. The API does
not send an order.

## Surprises, compared with CLAUDE.md

1. **There is no "approved" yes/no field.** CLAUDE.md says Moonlight finds
   "approved medicines". The nearest thing is
   `drug.maximumClinicalStage == "APPROVAL"`. Of the 40 drugs on our 11
   targets, 28 are `APPROVAL` and 12 are still in trials.
   Kashish needs to decide whether that is our meaning of "approved".

2. **Salt forms are separate drugs with separate ids.** Sildenafil is
   `CHEMBL192`. Sildenafil citrate (the form inside the tablet) is
   `CHEMBL1737`, with `parentMolecule` pointing to `CHEMBL192`. Their disease
   lists are different. A filter that only compares ids will leak. Real case
   in the fixtures: plain vardenafil is linked to PAH (`PHASE_3`), but
   vardenafil hydrochloride has no PAH link at all, so it would slip through
   the filter as a "new clue".

3. **"Already linked" comes in strengths.** Of the 118 drugs linked to PAH
   only 14 are `APPROVAL`. The rest were only tried in trials (43 at
   `PHASE_2`, 22 at `PHASE_3`, 9 `UNKNOWN`, and so on). CLAUDE.md says
   "remove medicines already known for that disease" but not how strong the
   link must be. Kashish needs to decide.

4. **The disease family is not included.** The PAH list is about PAH's own id.
   Sildenafil is `APPROVAL` for the parent, pulmonary hypertension
   (`MONDO_0005149`), but only `PHASE_3` for PAH under its plain id. filter.py
   will have to decide whether parents and children count.

5. **The stage on a target row is odd.** `target.drugAndClinicalCandidates
   .rows[].maxClinicalStage` says `WITHDRAWAL` for sildenafil and `PHASE_4`
   for tadalafil, while both drugs are `APPROVAL`. Use
   `drug.maximumClinicalStage` instead.

6. **Nothing says which direction the disease needs.** We get what the
   medicine does to the protein (`actionType`). We did not find any field
   saying whether PAH needs that protein turned up or down. So, by our safety
   rule, results must say the data does not tell us the direction.

7. **Many targets have no drugs.** 6 of the top 10 (EIF2AK4, SMAD9, ATP13A3,
   CAV1, TBX4, SOX17) returned zero drugs. The top targets are top because of
   gene evidence, not because medicines exist for them.

8. **The score has parts.** "Evidence strength" can be the overall `score`,
   or the per-kind `datatypeScores`. A target can score high from the
   `clinical` kind alone, which mostly means "drugs for this disease already
   hit this target" (EDNRA and PDE5A both have `clinical` near 0.99).

9. **Sources are there.** Each clinical report names its `source`
   (`ClinicalTrials.gov`, `DailyMed`, `EMA Human Drugs`, `FDA`, `PMDA`, `TTD`,
   and others) and a `url`. Each mechanism row has `references`.

## Sildenafil and PDE5A: do they appear, and where?

Yes to both.

**PDE5A** (`ENSG00000138735`, "phosphodiesterase 5A")
- `associated_targets.response.json`: row 15 of 25, score 0.61. Its evidence
  kinds are `clinical` 0.98 and `literature` 0.53.
- `target_drugs/15_PDE5A_ENSG00000138735.response.json`: 13 drugs, all with
  action type `INHIBITOR` on PDE5A.

**Sildenafil**
- In the PDE5A drug file, twice: `CHEMBL192` SILDENAFIL and `CHEMBL1737`
  SILDENAFIL CITRATE. Both are `INHIBITOR` of PDE5A, with the mechanism text
  "Phosphodiesterase 5A inhibitor", and both have
  `maximumClinicalStage: "APPROVAL"`.
- In each one's `indications`: SILDENAFIL CITRATE lists PAH at `APPROVAL`.
  Plain SILDENAFIL lists PAH at `PHASE_3` and pulmonary hypertension at
  `APPROVAL`.
- In `disease_drugs.response.json` (already linked to PAH), twice:
  SILDENAFIL CITRATE at `APPROVAL` and SILDENAFIL at `PHASE_3`.

So the golden path "sildenafil -> PDE5A -> PAH" is fully in the saved data,
and sildenafil is correctly on the "already known" list, as long as the filter
handles the two ids.

## Not checked

- Whether `disease.drugAndClinicalCandidates` also gathers drugs from child
  diseases (like idiopathic PAH). It does not gather from the parent.
- Any disease other than PAH.
- Whether two calls on different days give the same answer. Scores change
  when Open Targets publishes a new data release.
