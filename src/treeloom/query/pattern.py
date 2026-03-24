"""Pattern matching for structural code queries."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from treeloom.model.edges import EdgeKind
from treeloom.model.nodes import CpgNode, NodeKind

if TYPE_CHECKING:
    from treeloom.graph.cpg import CodePropertyGraph

# Maximum BFS depth when matching wildcard steps.
_WILDCARD_MAX_DEPTH = 20


@dataclass
class StepMatcher:
    """Matches a single node in a chain pattern.

    All non-None fields must match for the step to accept a node.
    If ``wildcard`` is True, the step matches zero or more intermediate
    nodes before the next concrete step.
    """

    kind: NodeKind | None = None
    name_pattern: str | None = None
    annotation_key: str | None = None
    annotation_value: Any = None
    wildcard: bool = False

    def matches(self, node: CpgNode, cpg: CodePropertyGraph) -> bool:
        """Return True if *node* satisfies every non-None constraint."""
        if self.wildcard:
            return True
        if self.kind is not None and node.kind != self.kind:
            return False
        if self.name_pattern is not None and not re.search(self.name_pattern, node.name):
            return False
        if self.annotation_key is not None:
            ann = cpg.get_annotation(node.id, self.annotation_key)
            if ann is None:
                return False
            if self.annotation_value is not None and ann != self.annotation_value:
                return False
        return True


@dataclass
class ChainPattern:
    """A sequence of :class:`StepMatcher` describing a path through the graph.

    ``edge_kind`` optionally restricts traversal to a single edge type.
    """

    steps: list[StepMatcher] = field(default_factory=list)
    edge_kind: EdgeKind | None = None


def match_chain(cpg: CodePropertyGraph, pattern: ChainPattern) -> list[list[CpgNode]]:
    """Find all node chains in *cpg* matching *pattern*.

    Returns a list of chains, where each chain is a list of :class:`CpgNode`
    corresponding to the concrete (non-wildcard) steps in the pattern.
    """
    if not pattern.steps:
        return []

    # Collect concrete (non-wildcard) step indices so we know what to match.
    concrete_indices = [i for i, s in enumerate(pattern.steps) if not s.wildcard]
    if not concrete_indices:
        return []

    first_step = pattern.steps[concrete_indices[0]]

    # Seed: all nodes matching the first concrete step.
    seeds = [n for n in cpg.nodes() if first_step.matches(n, cpg)]

    results: list[list[CpgNode]] = []
    for seed in seeds:
        _extend_chain(cpg, pattern, concrete_indices, 0, [seed], results)
    return results


def _extend_chain(
    cpg: CodePropertyGraph,
    pattern: ChainPattern,
    concrete_indices: list[int],
    ci_pos: int,
    current_chain: list[CpgNode],
    results: list[list[CpgNode]],
) -> None:
    """Recursively extend *current_chain* by matching subsequent steps."""
    if ci_pos >= len(concrete_indices) - 1:
        # All concrete steps matched.
        results.append(list(current_chain))
        return

    current_ci = concrete_indices[ci_pos]
    next_ci = concrete_indices[ci_pos + 1]
    next_step = pattern.steps[next_ci]

    # Determine whether there is a wildcard between the two concrete steps.
    has_wildcard = (next_ci - current_ci) > 1

    last_node = current_chain[-1]

    if has_wildcard:
        # BFS up to _WILDCARD_MAX_DEPTH looking for nodes matching next_step.
        visited: set[CpgNode] = {last_node}
        queue: deque[tuple[CpgNode, int]] = deque()
        for succ in _successors(cpg, last_node, pattern.edge_kind):
            if succ not in visited:
                queue.append((succ, 1))
                visited.add(succ)

        while queue:
            node, depth = queue.popleft()
            if next_step.matches(node, cpg):
                _extend_chain(
                    cpg, pattern, concrete_indices, ci_pos + 1,
                    current_chain + [node], results,
                )
            if depth < _WILDCARD_MAX_DEPTH:
                for succ in _successors(cpg, node, pattern.edge_kind):
                    if succ not in visited:
                        visited.add(succ)
                        queue.append((succ, depth + 1))
    else:
        # Direct hop: the next concrete step must match an immediate successor.
        for succ in _successors(cpg, last_node, pattern.edge_kind):
            if next_step.matches(succ, cpg):
                _extend_chain(
                    cpg, pattern, concrete_indices, ci_pos + 1,
                    current_chain + [succ], results,
                )


def _successors(
    cpg: CodePropertyGraph, node: CpgNode, edge_kind: EdgeKind | None
) -> list[CpgNode]:
    """Return successors of *node*, optionally filtered by *edge_kind*."""
    return cpg.successors(node.id, edge_kind=edge_kind)
