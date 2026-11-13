"""Ticket 6.1. Saved results: Open Targets answers kept in memory and on disk.

Nothing here touches the network. fetch.py now makes its HTTP calls through
one small function, fetch._send. Here it is swapped for FakeOpenTargets,
which counts the calls. The saved results go in a throwaway folder.

The shape of the data version answer ("meta", "dataVersion", "year",
"month", "iteration") was copied from the live API on 2026-11-12.
"""

import json
import pathlib
from unittest.mock import patch

import pytest

from moonlight import cache, engine, fetch
from moonlight.records import Disease, Target

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
GOLDEN = FIXTURES / "MONDO_0015924"
PAH = Disease(id="MONDO_0015924", name="pulmonary arterial hypertension")
PDE5A = Target(id="ENSG00000138735", symbol="PDE5A", name="phosphodiesterase 5A", score=0.61)
KCNK3_ID = "ENSG00000171303"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def saved_target_drugs(target_id):
    matches = list((GOLDEN / "target_drugs").glob(f"*_{target_id}.response.json"))
    if not matches:  # a protein with no saved file has no medicines here
        return {"data": {"target": {"id": target_id,
                                    "drugAndClinicalCandidates": {"count": 0, "rows": []}}}}
    return load(matches[0])


def without_reports(answer):
    """The same answer with every report taken out, like the thin answers
    the live API sometimes gave for PDE5A."""
    thin = json.loads(json.dumps(answer))
    for row in thin["data"]["target"]["drugAndClinicalCandidates"]["rows"]:
        row["clinicalReports"] = []
    return thin


def without_first_medicine(answer):
    """The same answer with one medicine missing."""
    other = json.loads(json.dumps(answer))
    del other["data"]["target"]["drugAndClinicalCandidates"]["rows"][0]
    return other


class FakeOpenTargets:
    """Stands in for fetch._send. Counts every call it gets."""

    def __init__(self, year="26", month="09", iteration=None):
        self.version = {"year": year, "month": month, "iteration": iteration}
        self.version_calls = 0
        self.data_calls = []  # the variables of every call that asked for data
        self.thin_asks = {}  # target id -> which asks (1, 2, 3...) have no reports
        self.other_medicines_asks = {}  # target id -> which asks name other medicines

    def __call__(self, body):
        assert set(body) == {"query", "variables"}
        variables = body["variables"]
        if "dataVersion" in body["query"]:
            self.version_calls += 1
            return {"data": {"meta": {"dataVersion": dict(self.version)}}}
        self.data_calls.append(variables)
        if "text" in variables:
            return load(GOLDEN / "disease_search.response.json")
        if "targetId" in variables:
            answer = saved_target_drugs(variables["targetId"])
            target_id = variables["targetId"]
            ask_number = self.data_calls.count(variables)
            if ask_number in self.other_medicines_asks.get(target_id, ()):
                return without_first_medicine(answer)
            if ask_number in self.thin_asks.get(target_id, ()):
                return without_reports(answer)
            return answer
        if "size" in variables:
            return load(GOLDEN / "associated_targets.response.json")
        return load(GOLDEN / "disease.response.json")

    def calls_for(self, target_id):
        return self.data_calls.count({"targetId": target_id})


@pytest.fixture(autouse=True)
def fresh_saved_results(tmp_path, monkeypatch):
    """An empty folder and an empty memory for every test. Real HTTP is an error."""
    monkeypatch.setenv("MOONLIGHT_CACHE_DIR", str(tmp_path / "saved"))
    cache.forget_memory()
    fetch.forget_version()
    with patch("requests.post", side_effect=AssertionError("network used")), \
            patch("requests.sessions.Session.request",
                  side_effect=AssertionError("network used")):
        yield
    cache.forget_memory()
    fetch.forget_version()


def use(fake):
    return patch("moonlight.fetch._send", side_effect=fake)


def new_program():
    """What a fresh run of Moonlight starts with: nothing in memory."""
    cache.forget_memory()
    fetch.forget_version()


# ---- the cache on its own ----

def test_what_is_saved_comes_back():
    cache.save("thing", "26.09", {"a": 1}, {"answer": [1, 2]})
    assert cache.load("thing", "26.09", {"a": 1}) == {"answer": [1, 2]}


def test_nothing_saved_gives_none():
    assert cache.load("thing", "26.09", {"a": 1}) is None


def test_it_is_still_there_after_memory_is_forgotten():
    cache.save("thing", "26.09", {"a": 1}, "kept")
    cache.forget_memory()
    assert cache.load("thing", "26.09", {"a": 1}) == "kept"


def test_another_version_key_or_kind_does_not_get_it():
    cache.save("thing", "26.09", {"a": 1}, "kept")
    assert cache.load("thing", "26.12", {"a": 1}) is None
    assert cache.load("thing", "26.09", {"a": 2}) is None
    assert cache.load("other", "26.09", {"a": 1}) is None


def test_the_folder_is_named_by_the_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_CACHE_DIR", str(tmp_path / "elsewhere"))
    cache.save("thing", "26.09", "key", "kept")
    assert list((tmp_path / "elsewhere").rglob("*.json"))


def test_the_default_folder_is_dot_moonlight_cache_and_git_ignores_it(monkeypatch):
    monkeypatch.delenv("MOONLIGHT_CACHE_DIR")
    assert cache.folder() == pathlib.Path(".moonlight-cache")
    ignored = (FIXTURES.parent / ".gitignore").read_text(encoding="utf-8").split()
    assert ".moonlight-cache/" in ignored


def test_a_broken_file_counts_as_nothing_saved(tmp_path):
    cache.save("thing", "26.09", "key", "kept")
    cache.forget_memory()
    for file in (tmp_path / "saved").rglob("*.json"):
        file.write_text("{ not json", encoding="utf-8")
    assert cache.load("thing", "26.09", "key") is None


def test_a_folder_that_cannot_be_written_still_works_from_memory(tmp_path, monkeypatch):
    blocker = tmp_path / "a-file-not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("MOONLIGHT_CACHE_DIR", str(blocker / "inside"))
    cache.save("thing", "26.09", "key", "kept")
    assert cache.load("thing", "26.09", "key") == "kept"


# ---- the data version ----

def test_the_data_version_is_read_from_the_api():
    with use(FakeOpenTargets(year="26", month="09")):
        assert fetch.data_version() == "26.09"


def test_the_data_version_keeps_an_iteration_if_there_is_one():
    with use(FakeOpenTargets(year="26", month="09", iteration="2")):
        assert fetch.data_version() == "26.09.2"


def test_the_data_version_is_asked_once_per_run():
    fake = FakeOpenTargets()
    with use(fake):
        fetch.data_version()
        fetch.data_version()
    assert fake.version_calls == 1


# ---- Example 1: a second identical request makes no HTTP call ----

def test_example_1_a_second_identical_request_makes_no_http_call():
    fake = FakeOpenTargets()
    with use(fake) as send:
        first = fetch.fetch_targets(PAH, 25)
        calls_after_first = send.call_count
        second = fetch.fetch_targets(PAH, 25)
        assert send.call_count == calls_after_first  # no HTTP call at all
    assert second == first
    assert len(fake.data_calls) == 1


def test_example_1_every_kind_of_question_is_saved():
    fake = FakeOpenTargets()
    with use(fake) as send:
        asked = [
            lambda: fetch.search_diseases("pulmonary arterial hypertension"),
            lambda: fetch.fetch_disease(PAH.id),
            lambda: fetch.fetch_targets(PAH, 25),
            lambda: fetch.fetch_paths(PAH, PDE5A),
        ]
        first = [ask() for ask in asked]
        calls_after_first = send.call_count
        second = [ask() for ask in asked]
        assert send.call_count == calls_after_first
    assert second == first


def test_example_1_a_new_run_reads_the_disk_and_only_asks_the_version():
    fake = FakeOpenTargets()
    with use(fake):
        first = fetch.fetch_paths(PAH, PDE5A)
        asked = len(fake.data_calls)
        new_program()
        second = fetch.fetch_paths(PAH, PDE5A)
    assert second == first
    assert len(fake.data_calls) == asked  # no new question for data
    assert fake.version_calls == 2  # each run reads the version once


def test_a_different_question_is_a_fresh_call():
    fake = FakeOpenTargets()
    with use(fake):
        fetch.fetch_targets(PAH, 25)
        fetch.fetch_targets(PAH, 10)
    assert [call["size"] for call in fake.data_calls] == [25, 10]


def test_an_error_answer_is_not_saved():
    replies = [{"errors": [{"message": "boom"}]}]

    def flaky(body):
        if "dataVersion" in body["query"]:
            return {"data": {"meta": {"dataVersion": {"year": "26", "month": "09",
                                                      "iteration": None}}}}
        return replies.pop(0) if replies else load(GOLDEN / "associated_targets.response.json")

    with patch("moonlight.fetch._send", side_effect=flaky):
        with pytest.raises(fetch.FetchError):
            fetch.fetch_targets(PAH, 25)
        assert len(fetch.fetch_targets(PAH, 25)) == 25


# ---- Example 2: a different data version makes a fresh call ----

def test_example_2_a_different_data_version_makes_a_fresh_call():
    fake = FakeOpenTargets(year="26", month="09")
    with use(fake):
        fetch.fetch_targets(PAH, 25)
        assert len(fake.data_calls) == 1

        new_program()
        fake.version["month"] = "12"  # Open Targets released new data
        fetch.fetch_targets(PAH, 25)
        assert len(fake.data_calls) == 2  # the old entry was not used

        fetch.fetch_targets(PAH, 25)
        assert len(fake.data_calls) == 2  # the new one is saved under 26.12


# ---- Kashish's decision, 2026-11-12: ask again, keep the fullest ----

def body_for(target_id):
    return {"query": fetch.TARGET_DRUGS_QUERY, "variables": {"targetId": target_id}}


def test_two_answers_the_same_means_no_third_ask():
    fake = FakeOpenTargets()
    with use(fake):
        assert fetch._post_json(body_for(PDE5A.id)) == saved_target_drugs(PDE5A.id)
        assert fake.calls_for(PDE5A.id) == 2
        fetch._post_json(body_for(PDE5A.id))  # saved now
        assert fake.calls_for(PDE5A.id) == 2


@pytest.mark.parametrize("thin_asks", [(1,), (2,), (1, 3), (2, 3)])
def test_two_answers_that_differ_mean_a_third_ask_and_the_fullest_is_kept(thin_asks):
    fake = FakeOpenTargets()
    fake.thin_asks[PDE5A.id] = thin_asks
    full = saved_target_drugs(PDE5A.id)
    with use(fake):
        assert fetch._post_json(body_for(PDE5A.id)) == full
        assert fake.calls_for(PDE5A.id) == 3
        assert fetch._post_json(body_for(PDE5A.id)) == full  # and that one is saved
        assert fake.calls_for(PDE5A.id) == 3


def test_fullest_means_the_most_clinical_reports_in_total():
    full = saved_target_drugs(PDE5A.id)
    rows = full["data"]["target"]["drugAndClinicalCandidates"]["rows"]
    assert fetch._report_count(full) == sum(len(row["clinicalReports"]) for row in rows) == 43
    assert fetch._report_count(without_reports(full)) == 0


def test_two_short_answers_that_are_the_same_are_kept_as_they_are():
    # The rule cannot tell: two answers the same means no third ask.
    fake = FakeOpenTargets()
    fake.thin_asks[PDE5A.id] = (1, 2)
    with use(fake):
        kept = fetch._post_json(body_for(PDE5A.id))
    assert kept == without_reports(saved_target_drugs(PDE5A.id))
    assert fake.calls_for(PDE5A.id) == 2


@pytest.mark.parametrize("odd_ask, asks", [(2, 2), (3, 3)])
def test_if_the_medicines_differ_it_stops_and_saves_nothing(odd_ask, asks, tmp_path):
    fake = FakeOpenTargets()
    fake.other_medicines_asks[PDE5A.id] = (odd_ask,)
    fake.thin_asks[PDE5A.id] = (1,)  # so that a third ask happens when it is needed
    with use(fake):
        with pytest.raises(fetch.AnswersDisagree) as stopped:
            fetch.fetch_paths(PAH, PDE5A)
        assert fake.calls_for(PDE5A.id) == asks
        assert "Kashish" in str(stopped.value)
        assert PDE5A.id in str(stopped.value)
        assert cache.load("open-targets", "26.09", body_for(PDE5A.id)) is None
    assert not list((tmp_path / "saved").rglob("*.json"))


def test_medicines_that_differ_is_a_fetch_error_so_the_runner_says_so():
    assert issubclass(fetch.AnswersDisagree, fetch.FetchError)


def test_other_questions_are_asked_once():
    fake = FakeOpenTargets()
    with use(fake):
        fetch.fetch_targets(PAH, 25)
        fetch.fetch_disease(PAH.id)
        fetch.search_diseases("pulmonary arterial hypertension")
    assert len(fake.data_calls) == 3


# ---- Change 4: pre-loading a list of disease ids ----

def test_preload_saves_everything_a_search_for_that_disease_needs():
    fake = FakeOpenTargets()
    with use(fake):
        loaded = engine.preload([PAH.id])
        asked = len(fake.data_calls)
        assert asked == 2 + 25 * 2  # the disease, its proteins, 25 proteins x 2

        # A later run, like cli.py after the search: nothing new is asked.
        new_program()
        targets = fetch.fetch_targets(PAH, 25)
        ranked = engine.find_ranked_clues(PAH, targets)
        assert len(fake.data_calls) == asked
    assert loaded == [PAH.id]
    assert ranked.new_clues


def test_preload_skips_an_id_open_targets_does_not_know():
    def unknown(body):
        if "dataVersion" in body["query"]:
            return {"data": {"meta": {"dataVersion": {"year": "26", "month": "09",
                                                      "iteration": None}}}}
        return {"data": {"disease": None}}

    with patch("moonlight.fetch._send", side_effect=unknown):
        assert engine.preload(["MONDO_NOT_REAL"]) == []


# =====================================================================
# Ticket 6.3: a saved Open Targets answer has a use-by date of one day
# =====================================================================

HOUR = 60 * 60


class Clock:
    """Stands in for cache._now, the one place the cache reads the time."""

    def __init__(self):
        self.now = 1_800_000_000.0  # seconds, like time.time()

    def hours_later(self, hours):
        self.now += hours * HOUR


@pytest.fixture
def clock():
    ticking = Clock()
    with patch("moonlight.cache._now", side_effect=lambda: ticking.now):
        yield ticking


def saved_files(tmp_path):
    return [load(file) for file in (tmp_path / "saved").rglob("*.json")]


def test_63_every_saved_open_targets_answer_records_when_it_was_saved(clock, tmp_path):
    with use(FakeOpenTargets()):
        fetch.fetch_targets(PAH, 25)
        clock.hours_later(2)
        fetch.fetch_paths(PAH, PDE5A)
    saved = saved_files(tmp_path)
    assert len(saved) == 2
    assert sorted(entry["saved_at"] for entry in saved) == [clock.now - 2 * HOUR, clock.now]


# Example 1
def test_63_example_1_an_answer_saved_23_hours_ago_is_used(clock):
    fake = FakeOpenTargets()
    with use(fake):
        first = fetch.fetch_targets(PAH, 25)
        clock.hours_later(23)
        second = fetch.fetch_targets(PAH, 25)
    assert second == first
    assert len(fake.data_calls) == 1  # no fresh call


def test_63_example_1_an_answer_saved_25_hours_ago_is_not_used_and_a_fresh_call_is_made(clock):
    fake = FakeOpenTargets()
    with use(fake):
        first = fetch.fetch_targets(PAH, 25)
        clock.hours_later(25)
        second = fetch.fetch_targets(PAH, 25)
    assert second == first
    assert len(fake.data_calls) == 2  # asked for fresh


def test_63_example_1_is_the_same_for_a_new_run_reading_the_disk(clock):
    fake = FakeOpenTargets()
    with use(fake):
        fetch.fetch_targets(PAH, 25)

        clock.hours_later(23)
        new_program()
        fetch.fetch_targets(PAH, 25)
        assert len(fake.data_calls) == 1  # 23 hours old: used

        clock.hours_later(2)
        new_program()
        fetch.fetch_targets(PAH, 25)
        assert len(fake.data_calls) == 2  # 25 hours old: asked for fresh


def test_63_an_answer_exactly_24_hours_old_is_still_used(clock):
    fake = FakeOpenTargets()
    with use(fake):
        fetch.fetch_targets(PAH, 25)
        clock.hours_later(24)
        fetch.fetch_targets(PAH, 25)
        assert len(fake.data_calls) == 1
        clock.now += 1  # one second older than 24 hours
        fetch.fetch_targets(PAH, 25)
        assert len(fake.data_calls) == 2


def test_63_the_use_by_date_is_one_day():
    assert fetch.USE_BY_SECONDS == 24 * HOUR


def test_63_the_fresh_answer_gets_a_new_use_by_date(clock, tmp_path):
    fake = FakeOpenTargets()
    with use(fake):
        fetch.fetch_targets(PAH, 25)
        clock.hours_later(25)
        fetch.fetch_targets(PAH, 25)  # asked for fresh, saved again
        clock.hours_later(23)
        new_program()
        fetch.fetch_targets(PAH, 25)  # the fresh one is 23 hours old: used
    assert len(fake.data_calls) == 2
    assert [entry["saved_at"] for entry in saved_files(tmp_path)] == [clock.now - 23 * HOUR]


def test_63_a_short_answer_saved_by_mistake_only_stays_for_a_day(clock):
    # Two short answers the same are kept (ticket 6.1 cannot tell). A day
    # later the question is asked again, twice, and the full answer replaces it.
    fake = FakeOpenTargets()
    fake.thin_asks[PDE5A.id] = (1, 2)
    full = saved_target_drugs(PDE5A.id)
    with use(fake):
        assert fetch._post_json(body_for(PDE5A.id)) == without_reports(full)
        clock.hours_later(23)
        assert fetch._post_json(body_for(PDE5A.id)) == without_reports(full)
        assert fake.calls_for(PDE5A.id) == 2
        clock.hours_later(2)
        assert fetch._post_json(body_for(PDE5A.id)) == full
        assert fake.calls_for(PDE5A.id) == 4
        assert fetch._post_json(body_for(PDE5A.id)) == full  # and that one is saved
        assert fake.calls_for(PDE5A.id) == 4


def test_63_a_file_saved_before_there_were_dates_is_asked_for_fresh(clock, tmp_path):
    fake = FakeOpenTargets()
    with use(fake):
        fetch.fetch_targets(PAH, 25)
        for file in (tmp_path / "saved").rglob("*.json"):
            entry = load(file)
            del entry["saved_at"]  # how ticket 6.1 wrote its files
            file.write_text(json.dumps(entry), encoding="utf-8")
        new_program()
        fetch.fetch_targets(PAH, 25)
    assert len(fake.data_calls) == 2


def test_63_a_date_from_the_future_is_not_trusted(clock):
    fake = FakeOpenTargets()
    with use(fake):
        fetch.fetch_targets(PAH, 25)
        clock.hours_later(-48)  # the computer's clock was wrong when it was saved
        fetch.fetch_targets(PAH, 25)
    assert len(fake.data_calls) == 2


def test_63_the_cache_only_checks_the_date_when_it_is_asked_to(clock):
    cache.save("thing", "26.09", "key", "kept")
    clock.hours_later(24 * 365)
    assert cache.load("thing", "26.09", "key") == "kept"  # no use-by date asked for
    assert cache.load("thing", "26.09", "key", max_age_seconds=24 * HOUR) is None
    cache.forget_memory()  # and the same from the disk
    assert cache.load("thing", "26.09", "key", max_age_seconds=24 * HOUR) is None
    assert cache.load("thing", "26.09", "key") == "kept"
