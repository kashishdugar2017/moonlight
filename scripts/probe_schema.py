"""Ticket 1.1 schema probe.

Asks the live Open Targets Platform API what it returns for one disease and
saves every request and its raw response under fixtures/, so later tests can
run offline.

Run from the repo root:

    python3 scripts/probe_schema.py                  # golden disease
    python3 scripts/probe_schema.py MONDO_0015924    # or name a disease id

For every call two files are written side by side:
    <name>.request.json    the exact JSON body that was POSTed (query + variables)
    <name>.response.json   the response exactly as the API sent it, only
                           re-indented so that it is readable

Requests go out one at a time with a pause between them. If the API refuses
(any status other than 200, or a GraphQL "errors" entry) the script stops at
once and keeps everything saved so far.
"""

import json
import pathlib
import sys
import time

import requests

URL = "https://api.platform.opentargets.org/api/v4/graphql"
GOLDEN_DISEASE = "MONDO_0015924"  # pulmonary arterial hypertension
ALWAYS_INCLUDE_SYMBOLS = ["PDE5A"]  # probed even when not in the top targets
TOP_TARGETS = 25
TOP_TARGETS_WITH_DRUGS = 10
PAUSE_SECONDS = 2.0
FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"

# The schema types Moonlight reads from. Saved so field names can be checked
# offline instead of remembered.
SCHEMA_TYPES = [
    "Query", "Pagination", "Disease", "DiseaseSynonyms",
    "AssociatedTargets", "AssociatedTarget", "ScoredComponent", "Target",
    "clinicalTargets", "ClinicalTargetFromTarget",
    "clinicalIndicationsFromDiseaseImp", "ClinicalIndicationFromDisease",
    "clinicalIndicationsFromDrugImp", "ClinicalIndicationFromDrug",
    "ClinicalDiseaseListItem", "ClinRepDrugListItem",
    "ClinicalReport", "ClinicalReportType",
    "Drug", "MechanismsOfAction", "MechanismOfActionRow", "Reference",
]

SCHEMA_QUERY = (
    "query SchemaTypes {\n"
    "  meta { name apiVersion { x y z } dataVersion { year month iteration } }\n"
    + "".join(
        f'  {name}: __type(name: "{name}") {{ ...TypeInfo }}\n' for name in SCHEMA_TYPES
    )
    + """}

fragment TypeInfo on __Type {
  name
  kind
  description
  enumValues { name description }
  inputFields { name description defaultValue type { ...TypeRef } }
  fields {
    name
    description
    args { name defaultValue type { ...TypeRef } }
    type { ...TypeRef }
  }
}

fragment TypeRef on __Type {
  kind name
  ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
}
"""
)

DISEASE_QUERY = """
query DiseaseRecord($diseaseId: String!) {
  disease(efoId: $diseaseId) {
    id
    name
    description
    dbXRefs
    synonyms { relation terms }
    isTherapeuticArea
    therapeuticAreas { id name }
    parents { id name }
    children { id name }
    ancestors
    descendants
    obsoleteTerms
  }
}
"""

ASSOCIATED_TARGETS_QUERY = """
query AssociatedTargets($diseaseId: String!, $size: Int!) {
  disease(efoId: $diseaseId) {
    id
    name
    associatedTargets(page: {index: 0, size: $size}) {
      count
      rows {
        score
        novelty
        datatypeScores { id score }
        datasourceScores { id score }
        target { id approvedSymbol approvedName biotype }
      }
    }
  }
}
"""

# Shared by the two drug queries, so a drug looks the same in both.
DRUG_FIELDS = """
fragment DrugFields on Drug {
  id
  name
  drugType
  maximumClinicalStage
  description
  parentMolecule { id name }
  mechanismsOfAction {
    uniqueActionTypes
    uniqueTargetTypes
    rows {
      mechanismOfAction
      actionType
      targetName
      targets { id approvedSymbol }
      references { source ids urls }
    }
  }
  indications {
    count
    rows { id maxClinicalStage disease { id name } }
  }
}

fragment ReportFields on ClinicalReport {
  id
  type
  source
  provider
  origin
  clinicalStage
  phaseFromSource
  trialPhase
  trialOverallStatus
  year
  url
}
"""

TARGET_DRUGS_QUERY = """
query TargetDrugs($targetId: String!) {
  target(ensemblId: $targetId) {
    id
    approvedSymbol
    approvedName
    drugAndClinicalCandidates {
      count
      rows {
        id
        maxClinicalStage
        drug { ...DrugFields }
        diseases { diseaseFromSource disease { id name } }
        clinicalReports { ...ReportFields }
      }
    }
  }
}
""" + DRUG_FIELDS

DISEASE_DRUGS_QUERY = """
query DiseaseDrugs($diseaseId: String!) {
  disease(efoId: $diseaseId) {
    id
    name
    drugAndClinicalCandidates {
      count
      rows {
        id
        maxClinicalStage
        drug { ...DrugFields }
        clinicalReports { ...ReportFields }
      }
    }
  }
}
""" + DRUG_FIELDS


def post(body):
    """The one place this script touches the network."""
    return requests.post(URL, json=body, timeout=120)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_and_save(stem, query, variables):
    """POST one query, save request and response next to each other, pause."""
    body = {"query": query.strip() + "\n", "variables": variables}
    response = post(body)
    if response.status_code != 200:
        sys.exit(
            f"STOP: the API answered {response.status_code} for {stem.name}. "
            f"Nothing more was sent. First 300 characters: {response.text[:300]}"
        )
    data = response.json()
    write_json(stem.with_name(stem.name + ".request.json"), body)
    write_json(stem.with_name(stem.name + ".response.json"), data)
    print(f"saved {stem.relative_to(FIXTURES.parent)}  ({len(response.content)} bytes)")
    if data.get("errors"):
        sys.exit(f"STOP: the API reported errors for {stem.name}: {data['errors']}")
    time.sleep(PAUSE_SECONDS)
    return data["data"]


def main():
    disease_id = sys.argv[1] if len(sys.argv) > 1 else GOLDEN_DISEASE
    out = FIXTURES / disease_id

    fetch_and_save(FIXTURES / "schema" / "types", SCHEMA_QUERY, {})

    disease = fetch_and_save(out / "disease", DISEASE_QUERY, {"diseaseId": disease_id})
    if disease["disease"] is None:
        sys.exit(f"STOP: Open Targets has no disease with id {disease_id}")

    associated = fetch_and_save(
        out / "associated_targets",
        ASSOCIATED_TARGETS_QUERY,
        {"diseaseId": disease_id, "size": TOP_TARGETS},
    )
    rows = associated["disease"]["associatedTargets"]["rows"]

    # Top 10 by score, plus the always-include targets wherever they rank.
    chosen = [(rank, row["target"]) for rank, row in enumerate(rows, start=1)]
    picked = chosen[:TOP_TARGETS_WITH_DRUGS]
    for symbol in ALWAYS_INCLUDE_SYMBOLS:
        if any(target["approvedSymbol"] == symbol for _, target in picked):
            continue
        found = [(r, t) for r, t in chosen if t["approvedSymbol"] == symbol]
        if not found:
            sys.exit(
                f"STOP: {symbol} is not in the top {TOP_TARGETS} targets, so its "
                "id is not known from saved data. Ask before going further."
            )
        picked.append(found[0])

    for rank, target in picked:
        stem = out / "target_drugs" / f"{rank:02d}_{target['approvedSymbol']}_{target['id']}"
        fetch_and_save(stem, TARGET_DRUGS_QUERY, {"targetId": target["id"]})

    fetch_and_save(out / "disease_drugs", DISEASE_DRUGS_QUERY, {"diseaseId": disease_id})
    print("done")


if __name__ == "__main__":
    main()
