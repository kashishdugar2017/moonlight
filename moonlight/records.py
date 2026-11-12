"""Shared record types for Moonlight: Disease, Target, MedicineForm, Medicine, Path.

Nothing here fetches, filters or ranks. These are only the shapes that the
other modules pass to each other, plus two small rules: which clinical stage
is stronger, and which way a medicine pushes a protein.
"""

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

# Clinical stages, strongest first. Open Targets sends these as words and
# does not send an order, so the order lives here.
STAGE_ORDER = (
    "APPROVAL",
    "PHASE_4",
    "PHASE_3",
    "PHASE_2_3",
    "PHASE_2",
    "PHASE_1_2",
    "PHASE_1",
    "EARLY_PHASE_1",
    "WITHDRAWAL",
    "UNKNOWN",
)

DOWN_ACTION_TYPES = frozenset({"INHIBITOR", "ANTAGONIST", "BLOCKER"})
UP_ACTION_TYPES = frozenset(
    {"AGONIST", "OPENER", "POSITIVE MODULATOR", "POSITIVE ALLOSTERIC MODULATOR"}
)


def _stage_rank(stage: str) -> int:
    """Position in STAGE_ORDER. 0 is strongest."""
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        raise ValueError(f"Unknown clinical stage: {stage!r}") from None


def stronger_stage(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Return the stronger of two stages.

    None means "no stage at all" and loses to every real stage. Two Nones
    give None.
    """
    if a is None:
        if b is not None:
            _stage_rank(b)
        return b
    if b is None:
        _stage_rank(a)
        return a
    return a if _stage_rank(a) <= _stage_rank(b) else b


def direction_from_action_types(action_types: Iterable[str]) -> str:
    """What the medicine does to the protein: "down", "up", "mixed" or "unknown".

    Action types on neither list are not guessed at. If nothing recognised
    is left, the answer is "unknown".
    """
    seen = {a.strip().upper() for a in action_types if a}
    down = bool(seen & DOWN_ACTION_TYPES)
    up = bool(seen & UP_ACTION_TYPES)
    if down and up:
        return "mixed"
    if down:
        return "down"
    if up:
        return "up"
    return "unknown"


@dataclass(frozen=True)
class Disease:
    id: str
    name: str
    description: str = ""  # what the disease is, in Open Targets' words; "" if not known


@dataclass(frozen=True)
class Target:
    id: str
    symbol: str
    name: str
    score: float  # link strength to the disease, 0 to 1


@dataclass(frozen=True)
class MedicineForm:
    """One database row: a medicine, or one tablet (salt) form of it."""

    id: str
    name: str
    best_stage: str  # furthest stage for any disease
    disease_stage: Optional[str] = None  # stage for our disease, None if no link
    parent_id: Optional[str] = None  # id of the medicine this is a form of

    def __post_init__(self):
        _stage_rank(self.best_stage)
        if self.disease_stage is not None:
            _stage_rank(self.disease_stage)


@dataclass(frozen=True)
class Medicine:
    """A family: a medicine and its tablet (salt) forms, kept as ONE item."""

    name: str
    forms: Tuple[MedicineForm, ...]

    def __post_init__(self):
        object.__setattr__(self, "forms", tuple(self.forms))
        if not self.forms:
            raise ValueError("A Medicine needs at least one form.")

    @property
    def best_stage(self) -> str:
        """Strongest best_stage among the forms."""
        best = None
        for form in self.forms:
            best = stronger_stage(best, form.best_stage)
        return best

    @property
    def disease_stage(self) -> Optional[str]:
        """Strongest disease_stage among the forms. None if no form has a link."""
        best = None
        for form in self.forms:
            best = stronger_stage(best, form.disease_stage)
        return best


@dataclass(frozen=True)
class Path:
    """One medicine -> protein -> disease connection worth reading about."""

    medicine: Medicine
    target: Target
    disease: Disease
    action_types: Tuple[str, ...]  # what the medicine does to this target
    score: float
    sources: Tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "action_types", tuple(self.action_types))
        object.__setattr__(self, "sources", tuple(self.sources))

    @property
    def direction(self) -> str:
        """Worked out from action_types, so the two can never disagree."""
        return direction_from_action_types(self.action_types)
