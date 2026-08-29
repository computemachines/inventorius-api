"""Slow, bounded reference semantics for constraint-solver experiments.

This module intentionally knows nothing about Z3 or Inventorius's production
event and query compilers.  It enumerates every assignment in a tiny finite
integer world, keeps the assignments that satisfy plain Python predicates, and
answers questions by directly inspecting those surviving worlds.

The implementation is test support, not a candidate production solver.  Its
value comes from being simple enough to audit and independent enough to catch a
mistake in the production translation to mathematical constraints.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from itertools import combinations, product


IntegerExpression = Callable[[Mapping[str, int]], int]
WorldPredicate = Callable[[Mapping[str, int]], bool]


@dataclass(frozen=True)
class FiniteWorld(Mapping[str, int]):
    """One immutable assignment of every variable in a finite experiment."""

    assignments: tuple[tuple[str, int], ...]

    def __getitem__(self, variable_id: str) -> int:
        for candidate_id, value in self.assignments:
            if candidate_id == variable_id:
                return value
        raise KeyError(variable_id)

    def __iter__(self) -> Iterator[str]:
        return (variable_id for variable_id, _ in self.assignments)

    def __len__(self) -> int:
        return len(self.assignments)


@dataclass(frozen=True)
class EventGroup:
    """A removable recorded or counterfactual event's physical predicates.

    All predicates in one group are installed or removed together.  This lets
    the oracle check conflicts at the event level even when one event contributes
    several individual mathematical facts.
    """

    group_id: str
    predicates: tuple[WorldPredicate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.group_id, str) or not self.group_id.strip():
            raise ValueError("group_id must be a nonblank string")
        if not self.predicates:
            raise ValueError("an event group needs at least one predicate")
        if any(not callable(predicate) for predicate in self.predicates):
            raise ValueError("event-group predicates must be callable")

    @classmethod
    def one(
        cls,
        group_id: str,
        predicate: WorldPredicate,
    ) -> EventGroup:
        """Construct the common one-predicate event group."""

        return cls(group_id, (predicate,))


@dataclass(frozen=True)
class OracleBounds:
    """Sharp integer endpoints and one concrete world attaining each one."""

    minimum: int
    maximum: int
    minimum_witness: FiniteWorld
    maximum_witness: FiniteWorld

    @property
    def exact(self) -> bool:
        return self.minimum == self.maximum


@dataclass(frozen=True)
class PredicateResult:
    """Whether a predicate is possible and guaranteed in the feasible worlds."""

    possible: bool
    guaranteed: bool
    satisfying_witness: FiniteWorld | None
    counterexample_witness: FiniteWorld | None


class NoFeasibleWorlds(ValueError):
    """The selected event groups admit no physical integer history."""


class FiniteHistoryOracle:
    """Exhaustively answer questions over a deliberately tiny integer world.

    ``variable_domains`` must be genuinely finite.  No attempt is made to turn
    an unbounded iterable into a safe input: keeping experiments visibly small
    is part of the reference oracle's contract.
    """

    def __init__(
        self,
        variable_domains: Mapping[str, Iterable[int]],
        event_groups: Iterable[EventGroup] = (),
    ) -> None:
        normalized_domains: list[tuple[str, tuple[int, ...]]] = []
        for variable_id, raw_domain in variable_domains.items():
            if not isinstance(variable_id, str) or not variable_id.strip():
                raise ValueError("variable identifiers must be nonblank strings")
            domain = tuple(raw_domain)
            if not domain:
                raise ValueError(f"{variable_id} needs a nonempty domain")
            if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in domain
            ):
                raise ValueError(f"{variable_id} domain must contain integers")
            if len(set(domain)) != len(domain):
                raise ValueError(f"{variable_id} domain contains duplicates")
            normalized_domains.append((variable_id, domain))

        groups = tuple(event_groups)
        group_ids = tuple(group.group_id for group in groups)
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("event group identifiers must be unique")

        self._variable_domains = tuple(normalized_domains)
        self._event_groups = groups
        self._groups_by_id = {group.group_id: group for group in groups}

    @property
    def variable_domains(self) -> tuple[tuple[str, tuple[int, ...]], ...]:
        return self._variable_domains

    @property
    def group_ids(self) -> tuple[str, ...]:
        return tuple(group.group_id for group in self._event_groups)

    @property
    def enumerated_world_count(self) -> int:
        count = 1
        for _, domain in self._variable_domains:
            count *= len(domain)
        return count

    def all_worlds(self) -> tuple[FiniteWorld, ...]:
        """Return every assignment before event predicates are applied."""

        variable_ids = tuple(
            variable_id for variable_id, _ in self._variable_domains
        )
        domains = tuple(domain for _, domain in self._variable_domains)
        return tuple(
            FiniteWorld(tuple(zip(variable_ids, values)))
            for values in product(*domains)
        )

    def feasible_worlds(
        self,
        included_group_ids: Iterable[str] | None = None,
    ) -> tuple[FiniteWorld, ...]:
        """Enumerate the exact worlds allowed by the selected event groups."""

        group_ids = self._normalize_group_ids(included_group_ids)
        groups = tuple(self._groups_by_id[group_id] for group_id in group_ids)
        feasible = []
        for world in self.all_worlds():
            if all(
                predicate(world)
                for group in groups
                for predicate in group.predicates
            ):
                feasible.append(world)
        return tuple(feasible)

    def is_feasible(
        self,
        included_group_ids: Iterable[str] | None = None,
    ) -> bool:
        return bool(self.feasible_worlds(included_group_ids))

    def expression_values(
        self,
        expression: IntegerExpression,
        included_group_ids: Iterable[str] | None = None,
    ) -> tuple[int, ...]:
        """Evaluate an integer expression once in every feasible world."""

        if not callable(expression):
            raise ValueError("expression must be callable")
        values = []
        for world in self.feasible_worlds(included_group_ids):
            value = expression(world)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("oracle expressions must return integers")
            values.append(value)
        if not values:
            raise NoFeasibleWorlds("the selected event groups have no worlds")
        return tuple(values)

    def expression_bounds(
        self,
        expression: IntegerExpression,
        included_group_ids: Iterable[str] | None = None,
    ) -> OracleBounds:
        """Return the exact extrema of an expression by exhaustive inspection."""

        if not callable(expression):
            raise ValueError("expression must be callable")
        worlds = self.feasible_worlds(included_group_ids)
        if not worlds:
            raise NoFeasibleWorlds("the selected event groups have no worlds")

        evaluated: list[tuple[int, FiniteWorld]] = []
        for world in worlds:
            value = expression(world)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("oracle expressions must return integers")
            evaluated.append((value, world))
        minimum, minimum_witness = min(evaluated, key=lambda item: item[0])
        maximum, maximum_witness = max(evaluated, key=lambda item: item[0])
        return OracleBounds(
            minimum,
            maximum,
            minimum_witness,
            maximum_witness,
        )

    def evaluate_predicate(
        self,
        predicate: WorldPredicate,
        included_group_ids: Iterable[str] | None = None,
    ) -> PredicateResult:
        """Answer possible/guaranteed without translating the predicate."""

        if not callable(predicate):
            raise ValueError("predicate must be callable")
        worlds = self.feasible_worlds(included_group_ids)
        if not worlds:
            raise NoFeasibleWorlds("the selected event groups have no worlds")
        satisfying = next((world for world in worlds if predicate(world)), None)
        counterexample = next(
            (world for world in worlds if not predicate(world)),
            None,
        )
        return PredicateResult(
            possible=satisfying is not None,
            guaranteed=counterexample is None,
            satisfying_witness=satisfying,
            counterexample_witness=counterexample,
        )

    def deletion_minimal_conflicts(
        self,
        candidate_group_ids: Iterable[str] | None = None,
        *,
        fixed_group_ids: Iterable[str] = (),
    ) -> tuple[tuple[str, ...], ...]:
        """Return every inclusion-minimal infeasible candidate-group subset.

        ``fixed_group_ids`` models the frozen base graph.  The returned tuples
        contain only removable candidate groups.  If the fixed graph is already
        infeasible, the sole minimal overlay conflict is the empty tuple.
        """

        fixed = self._normalize_group_ids(tuple(fixed_group_ids))
        candidates = self._normalize_group_ids(
            (
                group_id for group_id in self.group_ids
                if group_id not in fixed
            )
            if candidate_group_ids is None
            else candidate_group_ids
        )
        overlap = set(candidates).intersection(fixed)
        if overlap:
            raise ValueError(
                "candidate and fixed groups must be disjoint: "
                + ", ".join(sorted(overlap))
            )

        if not self.is_feasible(fixed):
            return ((),)

        conflicts: list[tuple[str, ...]] = []
        for size in range(1, len(candidates) + 1):
            for subset in combinations(candidates, size):
                subset_ids = set(subset)
                if any(
                    set(conflict).issubset(subset_ids)
                    for conflict in conflicts
                ):
                    continue
                if not self.is_feasible((*fixed, *subset)):
                    conflicts.append(subset)
        return tuple(conflicts)

    def is_deletion_minimal_conflict(
        self,
        conflict_group_ids: Iterable[str],
        *,
        fixed_group_ids: Iterable[str] = (),
    ) -> bool:
        """Validate one proposed deletion-minimal event-level conflict."""

        conflict = self._normalize_group_ids(tuple(conflict_group_ids))
        fixed = self._normalize_group_ids(tuple(fixed_group_ids))
        if set(conflict).intersection(fixed):
            raise ValueError("conflict and fixed groups must be disjoint")
        if self.is_feasible((*fixed, *conflict)):
            return False
        return all(
            self.is_feasible(
                (
                    *fixed,
                    *(
                        group_id for group_id in conflict
                        if group_id != removed_id
                    ),
                )
            )
            for removed_id in conflict
        )

    def removal_restores_feasibility(
        self,
        removed_group_id: str,
        included_group_ids: Iterable[str] | None = None,
    ) -> bool:
        """Check the common forensic question about removing one event."""

        included = self._normalize_group_ids(included_group_ids)
        if removed_group_id not in included:
            raise ValueError(
                f"cannot remove an excluded event group: {removed_group_id}"
            )
        return not self.is_feasible(included) and self.is_feasible(
            (
                group_id for group_id in included
                if group_id != removed_group_id
            )
        )

    def _normalize_group_ids(
        self,
        group_ids: Iterable[str] | None,
    ) -> tuple[str, ...]:
        if group_ids is None:
            return self.group_ids
        normalized = tuple(group_ids)
        if len(set(normalized)) != len(normalized):
            raise ValueError("event group selection contains duplicates")
        unknown = set(normalized).difference(self._groups_by_id)
        if unknown:
            raise ValueError(
                "unknown event groups: " + ", ".join(sorted(unknown))
            )
        return normalized


@dataclass(frozen=True)
class LEDAllocationScenario:
    """Compact physical histories for two color-untracked part builds.

    Each world chooses only the number of red LEDs placed in part A and part B.
    Blue quantities are the fixed part sizes minus those red quantities.  This
    reduces the corrected 25/25 example to 650 candidate assignments while
    retaining every physically distinct color allocation relevant to queries.
    """

    opening_red: int
    opening_blue: int
    part_a_size: int
    part_b_size: int

    def __post_init__(self) -> None:
        for field_name in (
            "opening_red",
            "opening_blue",
            "part_a_size",
            "part_b_size",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")

    def oracle(
        self,
        *,
        observed_remaining_blue: int | None = None,
    ) -> FiniteHistoryOracle:
        """Build a fresh enumerator, optionally adding one blue-count audit."""

        if observed_remaining_blue is not None:
            if (
                isinstance(observed_remaining_blue, bool)
                or not isinstance(observed_remaining_blue, int)
                or observed_remaining_blue < 0
            ):
                raise ValueError(
                    "observed_remaining_blue must be a nonnegative integer"
                )

        groups = [
            EventGroup.one(
                "opening:red-capacity",
                lambda world: (
                    world["red_in_a"] + world["red_in_b"]
                    <= self.opening_red
                ),
            ),
            EventGroup.one(
                "opening:blue-capacity",
                lambda world: self.blue_used(world) <= self.opening_blue,
            ),
        ]
        if observed_remaining_blue is not None:
            groups.append(
                EventGroup.one(
                    "observation:remaining-blue",
                    lambda world: (
                        self.opening_blue - self.blue_used(world)
                        == observed_remaining_blue
                    ),
                )
            )
        return FiniteHistoryOracle(
            {
                "red_in_a": range(self.part_a_size + 1),
                "red_in_b": range(self.part_b_size + 1),
            },
            groups,
        )

    def blue_in_a(self, world: Mapping[str, int]) -> int:
        return self.part_a_size - world["red_in_a"]

    def blue_in_b(self, world: Mapping[str, int]) -> int:
        return self.part_b_size - world["red_in_b"]

    def red_used(self, world: Mapping[str, int]) -> int:
        return world["red_in_a"] + world["red_in_b"]

    def blue_used(self, world: Mapping[str, int]) -> int:
        return self.blue_in_a(world) + self.blue_in_b(world)

    def remaining_red(self, world: Mapping[str, int]) -> int:
        return self.opening_red - self.red_used(world)

    def remaining_blue(self, world: Mapping[str, int]) -> int:
        return self.opening_blue - self.blue_used(world)


@dataclass(frozen=True, init=False)
class TwoStageLEDAssemblyScenario:
    """Compact histories for color-untracked parts and a later final draw.

    Each first-stage part records only its total size.  The second stage draws a
    fixed total from each part, again without recording color.  A world chooses
    the red quantity initially placed in each part and the red quantity left
    behind there after the final draw.  Blue quantities follow from the known
    totals, so enumeration retains every color allocation relevant to queries
    without assigning identities to otherwise interchangeable LEDs.
    """

    opening_red: int
    opening_blue: int
    part_sizes: tuple[int, ...]
    final_draws: tuple[int, ...]

    def __init__(
        self,
        opening_red: int,
        opening_blue: int,
        part_sizes: Iterable[int],
        final_draws: Iterable[int],
    ) -> None:
        sizes = tuple(part_sizes)
        draws = tuple(final_draws)
        for field_name, value in (
            ("opening_red", opening_red),
            ("opening_blue", opening_blue),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")
        if not sizes:
            raise ValueError("a two-stage scenario needs at least one part")
        if len(sizes) != len(draws):
            raise ValueError("part sizes and final draws must have equal lengths")
        for index, (size, draw) in enumerate(zip(sizes, draws)):
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise ValueError(
                    f"part_sizes[{index}] must be a nonnegative integer"
                )
            if (
                isinstance(draw, bool)
                or not isinstance(draw, int)
                or draw < 0
            ):
                raise ValueError(
                    f"final_draws[{index}] must be a nonnegative integer"
                )
            if draw > size:
                raise ValueError(
                    f"final_draws[{index}] cannot exceed its part size"
                )
        if sum(sizes) > opening_red + opening_blue:
            raise ValueError("first-stage parts exceed the opening LED quantity")

        object.__setattr__(self, "opening_red", opening_red)
        object.__setattr__(self, "opening_blue", opening_blue)
        object.__setattr__(self, "part_sizes", sizes)
        object.__setattr__(self, "final_draws", draws)

    @property
    def part_count(self) -> int:
        return len(self.part_sizes)

    @property
    def final_size(self) -> int:
        return sum(self.final_draws)

    @property
    def outside_size(self) -> int:
        return self.opening_red + self.opening_blue - self.final_size

    def oracle(
        self,
        *,
        observed_outside_blue: int | None = None,
    ) -> FiniteHistoryOracle:
        """Build a fresh enumerator, optionally auditing all outside LEDs."""

        if observed_outside_blue is not None and (
            isinstance(observed_outside_blue, bool)
            or not isinstance(observed_outside_blue, int)
            or observed_outside_blue < 0
        ):
            raise ValueError(
                "observed_outside_blue must be a nonnegative integer"
            )

        groups = [
            EventGroup.one(
                "opening:red-capacity",
                lambda world: self.red_in_parts(world) <= self.opening_red,
            ),
            EventGroup.one(
                "opening:blue-capacity",
                lambda world: self.blue_in_parts(world) <= self.opening_blue,
            ),
        ]
        variable_domains: dict[str, range] = {}
        for index, (size, draw) in enumerate(
            zip(self.part_sizes, self.final_draws)
        ):
            variable_domains[self._red_in_id(index)] = range(size + 1)
            variable_domains[self._red_left_id(index)] = range(size - draw + 1)
            groups.append(
                EventGroup(
                    f"part:{index}:leftover-capacity",
                    (
                        lambda world, selected=index: (
                            self.red_left_in_part(world, selected)
                            <= self.red_in_part(world, selected)
                        ),
                        lambda world, selected=index: (
                            self.blue_left_in_part(world, selected)
                            <= self.blue_in_part(world, selected)
                        ),
                    ),
                )
            )
        if observed_outside_blue is not None:
            groups.append(
                EventGroup.one(
                    "observation:outside-blue",
                    lambda world: (
                        self.outside_blue(world) == observed_outside_blue
                    ),
                )
            )
        return FiniteHistoryOracle(variable_domains, groups)

    def red_in_part(self, world: Mapping[str, int], index: int) -> int:
        return world[self._red_in_id(index)]

    def blue_in_part(self, world: Mapping[str, int], index: int) -> int:
        return self.part_sizes[index] - self.red_in_part(world, index)

    def red_left_in_part(self, world: Mapping[str, int], index: int) -> int:
        return world[self._red_left_id(index)]

    def blue_left_in_part(self, world: Mapping[str, int], index: int) -> int:
        leftover_size = self.part_sizes[index] - self.final_draws[index]
        return leftover_size - self.red_left_in_part(world, index)

    def red_to_final_from_part(
        self,
        world: Mapping[str, int],
        index: int,
    ) -> int:
        return self.red_in_part(world, index) - self.red_left_in_part(
            world,
            index,
        )

    def blue_to_final_from_part(
        self,
        world: Mapping[str, int],
        index: int,
    ) -> int:
        return self.final_draws[index] - self.red_to_final_from_part(
            world,
            index,
        )

    def red_in_parts(self, world: Mapping[str, int]) -> int:
        return sum(
            self.red_in_part(world, index) for index in range(self.part_count)
        )

    def blue_in_parts(self, world: Mapping[str, int]) -> int:
        return sum(
            self.blue_in_part(world, index) for index in range(self.part_count)
        )

    def red_final(self, world: Mapping[str, int]) -> int:
        return sum(
            self.red_to_final_from_part(world, index)
            for index in range(self.part_count)
        )

    def blue_final(self, world: Mapping[str, int]) -> int:
        return self.final_size - self.red_final(world)

    def source_red_remaining(self, world: Mapping[str, int]) -> int:
        return self.opening_red - self.red_in_parts(world)

    def source_blue_remaining(self, world: Mapping[str, int]) -> int:
        return self.opening_blue - self.blue_in_parts(world)

    def outside_red(self, world: Mapping[str, int]) -> int:
        return self.source_red_remaining(world) + sum(
            self.red_left_in_part(world, index)
            for index in range(self.part_count)
        )

    def outside_blue(self, world: Mapping[str, int]) -> int:
        return self.source_blue_remaining(world) + sum(
            self.blue_left_in_part(world, index)
            for index in range(self.part_count)
        )

    def complement_outside_red(self, world: Mapping[str, int]) -> int:
        """Derive the outside red total independently from final ancestry."""

        return self.opening_red - self.red_final(world)

    def complement_outside_blue(self, world: Mapping[str, int]) -> int:
        """Derive the outside blue total independently from final ancestry."""

        return self.opening_blue - self.blue_final(world)

    @staticmethod
    def _red_in_id(index: int) -> str:
        return f"red_in_part_{index}"

    @staticmethod
    def _red_left_id(index: int) -> str:
        return f"red_left_in_part_{index}"
