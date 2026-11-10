"""Ticket 1.1 check: every file in fixtures/ loads as JSON, then count.

Run from the repo root:

    python3 scripts/check_fixtures.py

Never touches the network. Exits with an error if any file is not valid JSON.
"""

import json
import pathlib
import sys

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"


def main():
    files = sorted(p for p in FIXTURES.rglob("*") if p.is_file())
    loaded = {}
    bad = []
    for path in files:
        try:
            loaded[path] = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            bad.append(f"{path.relative_to(FIXTURES.parent)}: {error}")
    print(f"files in fixtures/: {len(files)}   valid JSON: {len(loaded)}   broken: {len(bad)}")
    for line in bad:
        print("  BROKEN", line)

    for disease_dir in sorted(p for p in FIXTURES.iterdir() if (p / "disease.response.json").exists()):
        disease = loaded[disease_dir / "disease.response.json"]["data"]["disease"]
        print(f"\n{disease['id']}  {disease['name']}")

        assoc = loaded[disease_dir / "associated_targets.response.json"]["data"]["disease"]["associatedTargets"]
        print(f"  associated targets saved: {len(assoc['rows'])}  (Open Targets knows {assoc['count']})")

        all_drugs = set()
        print("  drugs acting on each probed target:")
        for path in sorted((disease_dir / "target_drugs").glob("*.response.json")):
            target = loaded[path]["data"]["target"]
            ids = {row["drug"]["id"] for row in target["drugAndClinicalCandidates"]["rows"] if row["drug"]}
            all_drugs |= ids
            print(f"    rank {path.name[:2]}  {target['approvedSymbol']:<8} {target['id']}  {len(ids):>3} drugs")
        print(f"  different drugs across those {len(list((disease_dir / 'target_drugs').glob('*.response.json')))} targets: {len(all_drugs)}")

        known = loaded[disease_dir / "disease_drugs.response.json"]["data"]["disease"]["drugAndClinicalCandidates"]
        known_ids = {row["drug"]["id"] for row in known["rows"] if row["drug"]}
        print(f"  drugs already linked to the disease: {len(known_ids)}  (Open Targets count: {known['count']})")
        print(f"  target drugs that are already linked to the disease: {len(all_drugs & known_ids)}")

    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
