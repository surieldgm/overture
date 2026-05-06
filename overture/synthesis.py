"""Deterministic synthesis from graph context into product briefs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


PRIOR_CONTEXT_LIMIT = 20
CONCEPT_NODE_TYPES = {"Idea", "Need", "Component", "Capability", "Constraint", "Risk", "TicketCandidate"}

BRIEF_SECTION_ORDER = (
    "Problem",
    "User need",
    "Relevant evidence",
    "Connected concepts",
    "Proposed capability",
    "Risks / uncertainty",
    "Open questions",
    "Candidate ticket breakdown",
)


@dataclass(frozen=True)
class GraphContext:
    nodes: tuple[Mapping[str, Any], ...] = ()
    edges: tuple[Mapping[str, Any], ...] = ()
    claims: tuple[Mapping[str, Any], ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class EvidenceReference:
    id: str
    summary: str
    source_refs: tuple[str, ...] = ()
    supports: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimReference:
    id: str
    statement: str
    confidence: str | float | None = None
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConnectedConcept:
    id: str
    type: str
    label: str
    summary: str
    relationships: tuple[str, ...] = ()
    from_prior: bool = False


@dataclass(frozen=True)
class CandidateTicket:
    id: str
    title: str
    scope: str
    validation_plan: tuple[str, ...] = ()
    source_node_ids: tuple[str, ...] = ()
    readiness: str | None = None


@dataclass(frozen=True)
class RelevantEvidence:
    evidence: tuple[EvidenceReference, ...] = ()
    evidence_backed_claims: tuple[ClaimReference, ...] = ()
    assumptions: tuple[ClaimReference, ...] = ()


@dataclass(frozen=True)
class SynthesisBrief:
    problem: str
    user_need: str
    relevant_evidence: RelevantEvidence
    connected_concepts: tuple[ConnectedConcept, ...]
    proposed_capability: str
    risks_uncertainty: tuple[str, ...]
    open_questions: tuple[str, ...]
    candidate_ticket_breakdown: tuple[CandidateTicket, ...]
    section_order: tuple[str, ...] = BRIEF_SECTION_ORDER

    def to_dict(self) -> dict[str, Any]:
        """Return a stable plain-Python representation for downstream tools."""

        return asdict(self)


def synthesize_graph_context(
    context: GraphContext | Mapping[str, Any],
    *,
    prior_context: GraphContext | Mapping[str, Any] | None = None,
) -> SynthesisBrief:
    """Convert graph context into a structured product/engineering brief.

    The synthesizer is intentionally deterministic: it organizes the graph
    facts already present instead of inventing new product direction.
    """

    normalized = _normalize_context(context)
    prior = _normalize_context(prior_context) if prior_context is not None else None
    nodes = normalized.nodes
    edges = normalized.edges
    explicit_claims = normalized.claims
    explicit_evidence = normalized.evidence
    prior_nodes = prior.nodes if prior else ()
    prior_edges = prior.edges if prior else ()

    nodes_by_id = _nodes_by_id((*nodes, *prior_nodes) if prior else nodes)
    all_edges = (*edges, *prior_edges) if prior else edges
    all_claims = (*_nodes_of_type(nodes, "Claim"), *explicit_claims)
    all_evidence = (*_nodes_of_type(nodes, "Evidence"), *explicit_evidence)
    if prior:
        all_claims = _dedupe_by_id((*all_claims, *_nodes_of_type(prior_nodes, "Claim"), *prior.claims))
        all_evidence = _dedupe_by_id((*all_evidence, *_nodes_of_type(prior_nodes, "Evidence"), *prior.evidence))
    ticket_nodes = _nodes_of_type(nodes, "TicketCandidate")

    problem_node = _first_of_type(nodes, ("Idea", "UserInput")) or _first_node(nodes)
    need_node = _first_of_type(nodes, ("Need",))
    capability_node = _first_of_type(nodes, ("Component", "Capability", "Idea")) or problem_node

    evidence_refs = tuple(_evidence_reference(item, all_edges, nodes_by_id) for item in all_evidence)
    evidence_backed_claims, assumptions = _split_claims(all_claims, all_edges, nodes_by_id)
    tickets = tuple(_candidate_ticket(node) for node in ticket_nodes) or (_fallback_ticket(problem_node, need_node),)

    connected_concepts = _connected_concepts(nodes, edges, prior)

    risks = tuple(_risk_text(node) for node in _nodes_of_type(nodes, "Risk"))
    if not risks and assumptions:
        risks = tuple(f"Assumption needs validation: {claim.statement}" for claim in assumptions)
    if not risks:
        risks = ("No explicit risks were provided in the graph context.",)

    open_questions = tuple(_summary(node) for node in _nodes_of_type(nodes, "Question"))
    if not open_questions:
        open_questions = ("Which generated ticket should be prioritized first after synthesis review?",)

    return SynthesisBrief(
        problem=_problem_text(problem_node, risks),
        user_need=_summary(need_node) or "No explicit user need node was provided.",
        relevant_evidence=RelevantEvidence(
            evidence=evidence_refs,
            evidence_backed_claims=evidence_backed_claims,
            assumptions=assumptions,
        ),
        connected_concepts=connected_concepts,
        proposed_capability=_proposed_capability(capability_node, tickets),
        risks_uncertainty=risks,
        open_questions=open_questions,
        candidate_ticket_breakdown=tickets,
    )


def _normalize_context(context: GraphContext | Mapping[str, Any]) -> GraphContext:
    if isinstance(context, GraphContext):
        return context
    return GraphContext(
        nodes=tuple(_as_mappings(context.get("nodes", ()))),
        edges=tuple(_as_mappings(context.get("edges", ()))),
        claims=tuple(_as_mappings(context.get("claims", ()))),
        evidence=tuple(_as_mappings(context.get("evidence", ()))),
    )


def _as_mappings(values: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return ()
    return tuple(value for value in values if isinstance(value, Mapping))


def _nodes_by_id(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {_node_id(node): node for node in nodes if _node_id(node)}


def _dedupe_by_id(values: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    deduped: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        value_id = _node_id(value)
        if value_id and value_id in seen:
            continue
        if value_id:
            seen.add(value_id)
        deduped.append(value)
    return tuple(deduped)


def _nodes_of_type(nodes: Sequence[Mapping[str, Any]], node_type: str) -> tuple[Mapping[str, Any], ...]:
    return tuple(node for node in nodes if _node_type(node) == node_type)


def _connected_concepts(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    prior: GraphContext | None,
) -> tuple[ConnectedConcept, ...]:
    concepts = [_connected_concept(node, edges) for node in nodes if _node_type(node) in CONCEPT_NODE_TYPES]
    if prior is None:
        return tuple(concepts)

    seen = {concept.id for concept in concepts if concept.id}
    prior_count = 0
    for node in sorted(
        (node for node in prior.nodes if _node_type(node) in CONCEPT_NODE_TYPES),
        key=_created_at_sort_key,
        reverse=True,
    ):
        node_id = _node_id(node)
        if node_id in seen:
            continue
        concepts.append(_connected_concept(node, prior.edges, from_prior=True))
        if node_id:
            seen.add(node_id)
        prior_count += 1
        if prior_count >= PRIOR_CONTEXT_LIMIT:
            break
    return tuple(concepts)


def _created_at_sort_key(node: Mapping[str, Any]) -> str:
    return str(node.get("created_at") or _properties(node).get("created_at") or "")


def _first_of_type(nodes: Sequence[Mapping[str, Any]], node_types: tuple[str, ...]) -> Mapping[str, Any] | None:
    return next((node for node in nodes if _node_type(node) in node_types), None)


def _first_node(nodes: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return nodes[0] if nodes else None


def _node_id(node: Mapping[str, Any] | None) -> str:
    return str(node.get("id") or node.get("key") or "").strip() if node else ""


def _node_type(node: Mapping[str, Any]) -> str:
    return str(node.get("type") or node.get("kind") or "").strip()


def _label(node: Mapping[str, Any] | None) -> str:
    properties = _properties(node)
    return str((node or {}).get("label") or (node or {}).get("title") or properties.get("title") or _node_id(node) or "").strip()


def _summary(node: Mapping[str, Any] | None) -> str:
    if not node:
        return ""
    properties = _properties(node)
    return str(
        node.get("summary")
        or node.get("statement")
        or node.get("content")
        or node.get("requirement")
        or node.get("scope")
        or node.get("raw_text")
        or properties.get("summary")
        or properties.get("text")
        or properties.get("content")
        or properties.get("requirement")
        or properties.get("scope")
        or ""
    ).strip()


def _properties(node: Mapping[str, Any] | None) -> Mapping[str, Any]:
    value = (node or {}).get("properties", {})
    return value if isinstance(value, Mapping) else {}


def _provenance(node: Mapping[str, Any]) -> Mapping[str, Any]:
    value = node.get("provenance")
    return value if isinstance(value, Mapping) else {}


def _source_refs(node: Mapping[str, Any]) -> tuple[str, ...]:
    refs = _provenance(node).get("source_refs", node.get("source_refs", _properties(node).get("source_refs", ())))
    return tuple(str(ref) for ref in refs if str(ref).strip()) if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes)) else ()


def _source_node_ids(node: Mapping[str, Any]) -> tuple[str, ...]:
    ids = _provenance(node).get("source_node_ids", node.get("source_node_ids", _properties(node).get("source_node_ids", ())))
    return tuple(str(node_id) for node_id in ids if str(node_id).strip()) if isinstance(ids, Sequence) and not isinstance(ids, (str, bytes)) else ()


def _edge_from(edge: Mapping[str, Any]) -> str:
    properties = _properties(edge)
    return str(edge.get("from") or edge.get("source") or edge.get("source_id") or properties.get("from") or "")


def _edge_to(edge: Mapping[str, Any]) -> str:
    properties = _properties(edge)
    return str(edge.get("to") or edge.get("target") or edge.get("target_id") or properties.get("to") or "")


def _edge_type(edge: Mapping[str, Any]) -> str:
    return str(edge.get("type") or edge.get("kind") or "").strip()


def _incoming_edges(node_id: str, edges: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    return tuple(edge for edge in edges if _edge_to(edge) == node_id)


def _outgoing_edges(node_id: str, edges: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    return tuple(edge for edge in edges if _edge_from(edge) == node_id)


def _evidence_reference(
    evidence: Mapping[str, Any],
    edges: Sequence[Mapping[str, Any]],
    nodes_by_id: Mapping[str, Mapping[str, Any]],
) -> EvidenceReference:
    evidence_id = _node_id(evidence)
    supports = []
    for edge in _outgoing_edges(evidence_id, edges):
        target = nodes_by_id.get(_edge_to(edge))
        if target:
            supports.append(_label(target) or _edge_to(edge))
    return EvidenceReference(
        id=evidence_id,
        summary=_summary(evidence),
        source_refs=_source_refs(evidence),
        supports=tuple(supports),
    )


def _split_claims(
    claims: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    nodes_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[ClaimReference, ...], tuple[ClaimReference, ...]]:
    backed: list[ClaimReference] = []
    assumptions: list[ClaimReference] = []
    for claim in claims:
        reference = ClaimReference(
            id=_node_id(claim),
            statement=_summary(claim),
            confidence=claim.get("confidence") or _properties(claim).get("confidence") or _provenance(claim).get("confidence"),
            source_refs=_source_refs(claim),
        )
        if _is_assumption(claim, edges, nodes_by_id):
            assumptions.append(reference)
        else:
            backed.append(reference)
    return tuple(backed), tuple(assumptions)


def _is_assumption(
    claim: Mapping[str, Any],
    edges: Sequence[Mapping[str, Any]],
    nodes_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    properties = _properties(claim)
    claim_kind = str(claim.get("claim_kind") or properties.get("claim_kind") or properties.get("kind") or claim.get("kind") or "").lower()
    if claim_kind in {"assumption", "hypothesis", "inference"}:
        return True

    provenance = _provenance(claim)
    if provenance.get("origin") in {"research", "user_input", "system"} or _source_refs(claim):
        return False

    claim_id = _node_id(claim)
    for edge in _incoming_edges(claim_id, edges):
        source = nodes_by_id.get(_edge_from(edge))
        if source and _node_type(source) in {"Evidence", "Source", "UserInput"} and _edge_type(edge) in {"supports", "derived_from", "cites"}:
            return False

    return bool(claim_id)


def _connected_concept(node: Mapping[str, Any], edges: Sequence[Mapping[str, Any]], *, from_prior: bool = False) -> ConnectedConcept:
    node_id = _node_id(node)
    relationships = tuple(
        f"{_edge_type(edge)} -> {_edge_to(edge)}"
        for edge in _outgoing_edges(node_id, edges)
        if _edge_type(edge) and _edge_to(edge)
    )
    return ConnectedConcept(
        id=node_id,
        type=_node_type(node),
        label=_label(node),
        summary=_summary(node),
        relationships=relationships,
        from_prior=from_prior,
    )


def _risk_text(node: Mapping[str, Any]) -> str:
    mitigation = str(node.get("mitigation") or "").strip()
    label = _label(node)
    summary = _summary(node)
    text = f"{label}: {summary}" if label and label != summary else summary
    return f"{text} Mitigation: {mitigation}" if mitigation else text


def _candidate_ticket(node: Mapping[str, Any]) -> CandidateTicket:
    properties = _properties(node)
    plan = node.get("validation_plan", properties.get("validation_plan", ()))
    validation_plan = tuple(str(item) for item in plan if str(item).strip()) if isinstance(plan, Sequence) and not isinstance(plan, (str, bytes)) else ()
    return CandidateTicket(
        id=_node_id(node),
        title=str(node.get("title") or properties.get("title") or _label(node) or "Implement graph synthesis output").strip(),
        scope=str(node.get("scope") or properties.get("scope") or _summary(node) or "Convert synthesized graph context into an actionable implementation ticket.").strip(),
        validation_plan=validation_plan,
        source_node_ids=_source_node_ids(node),
        readiness=str(node.get("readiness") or properties.get("readiness") or "").strip() or None,
    )


def _fallback_ticket(problem_node: Mapping[str, Any] | None, need_node: Mapping[str, Any] | None) -> CandidateTicket:
    source_ids = tuple(node_id for node_id in (_node_id(problem_node), _node_id(need_node)) if node_id)
    return CandidateTicket(
        id="ticketcandidate_synthesize_graph_context",
        title="Implement graph-context synthesis brief",
        scope=_summary(need_node)
        or _summary(problem_node)
        or "Create a structured brief from relevant graph context so downstream ticket generation has concrete inputs.",
        validation_plan=("Run synthesis on the sample graph and confirm candidate ticket fields are populated.",),
        source_node_ids=source_ids,
        readiness="draft",
    )


def _problem_text(problem_node: Mapping[str, Any] | None, risks: Sequence[str]) -> str:
    problem = _summary(problem_node) or "Graph context needs to become a concise product and engineering brief."
    if risks:
        return f"{problem} Primary risk: {risks[0]}"
    return problem


def _proposed_capability(capability_node: Mapping[str, Any] | None, tickets: Sequence[CandidateTicket]) -> str:
    capability = _summary(capability_node) or "Synthesize graph context into a stable structured brief."
    if tickets:
        return f"{capability} First candidate: {tickets[0].title}."
    return capability
