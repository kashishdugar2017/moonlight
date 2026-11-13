# Decisions

One line per decision, newest at the bottom, in Kashish's words.
Format: date, the decision, why.

- 2026-11-10: The licence is MIT. Anyone can use and change Moonlight if they keep our name on it.
- 2026-11-10: The app is called Moonlight. Old medicines can "moonlight" in a second job.
- 2026-11-10: A key that has been seen is a dead key. Delete it and make a new one.
- 2026-11-10: "Approved" means approved for at least one disease. Trial medicines might not work or be safe yet.
- 2026-11-10: Medicines already being tested for the disease go in a separate box, not the main list.
- 2026-11-10: A medicine and its tablet form are one item, with both forms shown inside. It is easier to understand.
- 2026-11-11: Medicines already approved for the disease are removed. They are not clues.
- 2026-11-11: WITHDRAWAL stays at the bottom of the stage ladder. A medicine taken off the shelves does not count as approved.
- 2026-11-11: If Moonlight meets an action word it does not know, it says "unknown". It never guesses.
- 2026-11-12: Ranking: highest protein score first, then more reports, then alphabetical. A medicine appears once.
- 2026-11-12: Pieces of the same machine count once in the score. Isosorbide Mononitrate was counted three times, like one relay win counted as three.
- 2026-11-12: Explanations are for everyone, written simply enough for a five-year-old who can read. No sentence longer than 20 words.
- 2026-11-12: Explanations must: explain big words, say only true things from the facts, say the catch, and say not to try it.
- 2026-11-12: Explanations must never: add made-up things, say where to get medicines, or say it will work.
- 2026-11-12: The ending is added by the code, not by Gemini, so it is always the same.
- 2026-11-12: Scores are also shown as points out of 100. A five-year-old does not know decimals.
- 2026-11-12: Moonlight waits at most 25 seconds for an explanation, and shows a "Please wait" message.
- 2026-11-12: ACTIVATOR means the medicine turns the protein up. BINDING AGENT stays "unknown", because sticking to a protein does not say which way it turns.
- 2026-11-12: The page is medicine first. The medicine is the clue, so the reader sees medicines in my ranked order. Proteins are filter buttons.
- 2026-11-12: The page is a small API with Mumma's designed page, not Streamlit.
- 2026-11-12: Open Targets sometimes gives a short answer for the same question. Moonlight asks again and keeps the fullest answer, because every report is a real record and a shorter list has something missing.
- 2026-11-13: Moonlight shows "Did you mean: <disease>?" and the person taps it. Moonlight never picks a disease for the person. A helper can point at the map, but the person chooses the road.
- 2026-11-13: Measurements are hidden from the list of matches. "Diastolic blood pressure" is a number a doctor measures. It is not a disease. Open Targets marks them itself with the word "measurement", so Moonlight does not guess.
- 2026-11-13: Only measurements are hidden for now. Other things that are not diseases, like "response to high sodium diet", stay until I have seen more examples.
- 2026-11-13: When the words typed are on Open Targets' own "also called" list for a disease, Moonlight shows that word next to the name, like "Orthomyxoviridae infectious disease, also called: flu". Open Targets has no entry named "influenza", only this one. The word comes from Open Targets, never from Gemini.
- 2026-11-13: A suggestion that is already the first match is not shown twice.
