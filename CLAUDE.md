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
- Kashish also runs the agent sessions and reviews every change.
  Shreshth is her co-founder and explains things when she asks.
- Agents write code and tests for one ticket at a time.
When Kashish writes to you, answer in plain language a 9-year-old can follow,
with physical analogies (swim lanes, relays, a volume knob, maps). Never talk
down to her.

## Pipeline (one module each, in moonlight/)
1. translate.py  everyday words -> candidate diseases, confirmed by Open Targets search
2. fetch.py      disease -> targets with scores, and drugs acting on each target
3. filter.py     sort medicines into groups using Kashish's rules below
4. rank.py       rank the remaining paths (plain code, no AI)
5. explain.py    one path's records -> plain-language text (Gemini), then a grounding check
6. app.py        Streamlit page: search, ranked list, path map, safety banner
Shared record types live in moonlight/records.py: Disease, Target,
MedicineForm, Medicine, Path.

## Kashish's rules for medicines
- A medicine and its tablet (salt) forms are one item, with all forms
  shown inside it. The item takes the strongest stage of its forms.
- "Approved" means approved for at least one disease. A medicine that
  is not approved anywhere is left out.
- New clue: approved, with no link to the disease. Main list.
- Being studied: approved, and in trials for the disease. Separate box
  labelled "Already being studied for this disease", with the trial
  phase and source. Never say or hint it is more likely to work.
- Already approved for the disease: removed. It is not a clue.

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
- Gemini API at generativelanguage.googleapis.com, called over REST with the
  requests library. Do not add a Gemini SDK.
  - In agent sessions the environment adds the key to each request. Send no
    key header yourself.
  - In the deployed app the key comes from the environment variable
    GEMINI_API_KEY. If that variable is set, send it as the x-goog-api-key
    header. If it is not set, send no key header.
  - Never ask for the key, print it, log request headers, or write any key
    to a file.
  - Check the model name against the API's model list. Never assume it.
- These are the only two outside data sources. Do not use any other.
- Check field names against live responses or files in fixtures/. Never
  assume a field name from memory.

## How to work
- One ticket per branch, named ticket-<id>-<short-name>. Touch only the
  files the ticket names. Open a pull request. Never merge it yourself.
- Tests first: turn the ticket's EXAMPLE into a test, show it failing, then
  write the code.
- Tests use saved JSON responses in fixtures/ and must never touch the
  network. Each module makes its HTTP calls through one small function, and
  tests replace that function using unittest.mock.patch.
- Never edit, skip or delete a test to make it pass. If a test looks wrong,
  stop and say so.
- If something in the ticket does not match the repo or the data, stop and ask.
- Stack: Python 3, requests, pytest. Streamlit for the page. Open Targets
  queries are plain POST requests with a JSON body holding "query" and
  "variables". Keep dependencies few and list them in requirements.txt.

## End every session with a report
1. What changed (files).
2. What you ran, with the exact commands and their output.
3. What you did not verify.
4. Explain the change in five plain sentences for Kashish.
Nothing is merged until Kashish has read that explanation and answered
questions about the change.
