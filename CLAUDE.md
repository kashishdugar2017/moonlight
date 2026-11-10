# Moonlight: project instructions

Read this file fully before doing anything in this repo.

## What Moonlight is
An explorer for drug-repurposing clues. A user types a disease. Moonlight
finds the proteins linked to it, then approved medicines that act on those
proteins, removes medicines already known for that disease, ranks the rest,
and explains each medicine -> protein -> disease path in plain language.
It is a learning and research exploration tool. It is never treatment advice.

## Who decides what
- Kashish (age 9) is the tech lead. She decides how Moonlight behaves, writes
  the hand-worked examples, runs the acceptance checks and says merge.
- Shreshth runs the agent sessions and reads every change first.
- Agents write code and tests for one ticket at a time.
When Kashish writes to you, answer in plain language a 9-year-old can follow,
with physical analogies (swim lanes, relays, a volume knob, maps). Never talk
down to her.

## Pipeline (one module each, in moonlight/)
1. translate.py  everyday words -> candidate diseases, confirmed by Open Targets search
2. fetch.py      disease -> targets with scores, and drugs acting on each target
3. filter.py     remove drugs already linked to the disease
4. rank.py       rank the remaining paths (plain code, no AI)
5. explain.py    one path's records -> plain-language text (Gemini), then a grounding check
6. app.py        Streamlit page: search, ranked list, path map, safety banner
Shared record types live in moonlight/records.py: Disease, Target, Drug, Path.

## Safety rules. No ticket may weaken these.
- Every page shows: "For learning and research exploration, not medical advice.
  Never start, stop or change any medicine without a doctor."
- Every result shows its source and evidence strength.
- Every result shows whether the medicine turns the protein up or down. If the
  data does not say which direction the disease needs, the result says so.
- Gemini only explains records it is handed. It never creates a disease,
  protein, medicine, link, ID or score.
- Results are "connections worth reading about", never treatments.
Changing safety text or the grounding rule needs Kashish's explicit approval.

## Data and network
- Open Targets Platform GraphQL: https://api.platform.opentargets.org/api/v4/graphql
- Gemini API at generativelanguage.googleapis.com. The key is attached to
  requests by the environment. Never ask for it, print it, log request
  headers, or write any key to a file.
- These are the only two outside data sources. Do not use any other.
- Check field names against live responses or files in fixtures/. Never
  assume a field name from memory.

## How to work
- One ticket per branch, named ticket-<id>-<short-name>. Touch only the
  files the ticket names. Open a pull request. Never merge it yourself.
- Tests first: turn the ticket's EXAMPLE into a test, show it failing, then
  write the code.
- Tests use saved responses in fixtures/ so they run offline.
- Never edit, skip or delete a test to make it pass. If a test looks wrong,
  stop and say so.
- If something in the ticket does not match the repo or the data, stop and ask.
- Stack: Python 3, requests, pytest. Streamlit for the page. Keep
  dependencies few and list them in requirements.txt.

## End every session with a report
1. What changed (files).
2. What you ran, with the exact commands and their output.
3. What you did not verify.
