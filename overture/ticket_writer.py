"""Linear issue draft generation from synthesized Overture briefs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .synthesis import (
    CandidateTicket,
    ClaimReference,
    ConnectedConcept,
    EvidenceReference,
    RelevantEvidence,
    SynthesisBrief,
)


REQUIRED_SECTION_HEADINGS = (
    "## Context",
    "## Problem",
    "## Proposed change",
    "## Acceptance criteria",
    "## Validation plan",
    "## Sources / evidence",
    "## Graph provenance",
    "## Dependencies",
    "## Out of scope",
    "## Risk / uncertainty",
    "## Follow-up candidates",
)

PRECISE_IMPERATIVE_VERBS = {
    "add",
    "define",
    "fix",
    "remove",
    "migrate",
    "expose",
    "review",
    "validate",
    "document",
    "draft",
}

IMPERATIVE_TITLE_REWRITES = {
    "build": "Add",
    "create": "Add",
    "implement": "Add",
    "improve": "Add",
    "make": "Add",
    "support": "Add",
}


@dataclass(frozen=True)
class LinearIssueDraft:
    title: str
    description: str

    def to_dict(self) -> dict[str, str]:
        """Return the payload shape expected by a future Linear adapter."""

        return {"title": self.title, "description": self.description}


def generate_linear_issue_draft(
    synthesis: SynthesisBrief | Mapping[str, Any],
    *,
    candidate_index: int = 0,
    dependencies: Sequence[str] | None = None,
    out_of_scope: Sequence[str] | None = None,
    follow_up_candidates: Sequence[str] | None = None,
) -> LinearIssueDraft:
    """Create a schema-valid Linear issue draft from synthesis output."""

    brief = _coerce_brief(synthesis)
    candidate = _candidate_at(brief, candidate_index)
    title = _imperative_title(candidate.title)
    dependencies = tuple(dependencies or ("None.",))
    out_of_scope = tuple(
        out_of_scope
        or (
            "Do not create the Linear issue automatically.",
            "Do not expand into unrelated graph schema or research ingestion changes.",
        )
    )
    follow_up_candidates = tuple(follow_up_candidates or ("None.",))

    description = "\n\n".join(
        (
            *_frontmatter_lines(candidate),
            f"# {title}",
            "## Context\n\n" + _context(brief),
            "## Problem\n\n" + _problem(brief),
            "## Proposed change\n\n" + _proposed_change(candidate),
            "## Acceptance criteria\n\n" + _acceptance_criteria(candidate),
            "## Validation plan\n\n" + _validation_plan(candidate),
            "## Sources / evidence\n\n" + _sources(brief),
            "## Graph provenance\n\n" + _graph_provenance(brief, candidate),
            "## Dependencies\n\n" + _bullets(dependencies),
            "## Out of scope\n\n" + _bullets(out_of_scope),
            "## Risk / uncertainty\n\n" + _risk_uncertainty(brief),
            "## Follow-up candidates\n\n" + _bullets(follow_up_candidates),
        )
    )
    draft = LinearIssueDraft(title=title, description=description)
    validate_linear_issue_draft(draft)
    return draft


def validate_linear_issue_draft(draft: LinearIssueDraft | Mapping[str, str]) -> None:
    """Raise ValueError when a generated issue draft violates the schema."""

    title = draft.title if isinstance(draft, LinearIssueDraft) else str(draft.get("title", ""))
    description = draft.description if isinstance(draft, LinearIssueDraft) else str(draft.get("description", ""))
    errors = validate_linear_issue_payload(title, description)
    if errors:
        raise ValueError("; ".join(errors))


def validate_linear_issue_payload(title: str, description: str) -> tuple[str, ...]:
    """Return schema validation errors for a generated Linear issue payload."""

    errors: list[str] = []
    lines = description.splitlines()
    headings = [line.strip() for line in lines if line.startswith("#")]
    expected_headings = (f"# {title}", *REQUIRED_SECTION_HEADINGS)

    if not title.strip():
        errors.append("title is required")
    elif len(title.split()) > 12:
        errors.append("title must be 12 words or fewer")
    elif title.split()[0].lower() not in PRECISE_IMPERATIVE_VERBS:
        errors.append("title must start with a precise imperative verb")

    if headings[: len(expected_headings)] != list(expected_headings):
        errors.append("required sections must appear in canonical order")

    sections = _section_bodies(description)
    missing = [heading for heading in REQUIRED_SECTION_HEADINGS if not sections.get(heading, "").strip()]
    if missing:
        errors.append("required sections cannot be empty: " + ", ".join(missing))

    acceptance = sections.get("## Acceptance criteria", "")
    if acceptance.count("- [ ]") < 3:
        errors.append("Acceptance criteria must include at least three checkboxes")

    validation = sections.get("## Validation plan", "")
    if "`" not in validation and "Run " not in validation:
        errors.append("Validation plan must include executable commands or explicit run steps")

    provenance = sections.get("## Graph provenance", "")
    for required in ("Nodes:", "Edges:", "Confidence:", "Conflicts:"):
        if required not in provenance:
            errors.append(f"Graph provenance missing {required}")

    if "None" not in sections.get("## Dependencies", "") and "-" not in sections.get("## Dependencies", ""):
        errors.append("Dependencies must be explicit")
    if "-" not in sections.get("## Out of scope", ""):
        errors.append("Out of scope must include at least one explicit non-goal")

    return tuple(errors)


def _coerce_brief(synthesis: SynthesisBrief | Mapping[str, Any]) -> SynthesisBrief:
    if isinstance(synthesis, SynthesisBrief):
        return synthesis
    if not isinstance(synthesis, Mapping):
        raise TypeError("synthesis must be a SynthesisBrief or mapping")

    evidence = synthesis.get("relevant_evidence", {})
    evidence = evidence if isinstance(evidence, Mapping) else {}
    return SynthesisBrief(
        problem=str(synthesis.get("problem", "")).strip(),
        user_need=str(synthesis.get("user_need", "")).strip(),
        relevant_evidence=RelevantEvidence(
            evidence=tuple(_evidence_reference(item) for item in _sequence(evidence.get("evidence", ()))),
            evidence_backed_claims=tuple(_claim_reference(item) for item in _sequence(evidence.get("evidence_backed_claims", ()))),
            assumptions=tuple(_claim_reference(item) for item in _sequence(evidence.get("assumptions", ()))),
        ),
        connected_concepts=tuple(_connected_concept(item) for item in _sequence(synthesis.get("connected_concepts", ()))),
        proposed_capability=str(synthesis.get("proposed_capability", "")).strip(),
        risks_uncertainty=tuple(str(item).strip() for item in _sequence(synthesis.get("risks_uncertainty", ()))),
        open_questions=tuple(str(item).strip() for item in _sequence(synthesis.get("open_questions", ()))),
        candidate_ticket_breakdown=tuple(_candidate_ticket(item) for item in _sequence(synthesis.get("candidate_ticket_breakdown", ()))),
        section_order=tuple(str(item).strip() for item in _sequence(synthesis.get("section_order", ()))),
    )


def _candidate_at(brief: SynthesisBrief, index: int) -> CandidateTicket:
    if index < 0 or index >= len(brief.candidate_ticket_breakdown):
        raise IndexError("candidate_index does not identify a candidate ticket")
    return brief.candidate_ticket_breakdown[index]


def _imperative_title(title: str) -> str:
    words = title.strip().split()
    if not words:
        return "Add generated Linear issue draft"
    first = words[0].lower()
    if first in IMPERATIVE_TITLE_REWRITES:
        words[0] = IMPERATIVE_TITLE_REWRITES[first]
    return " ".join(words[:12])


def _context(brief: SynthesisBrief) -> str:
    return (
        f"{brief.problem} This task fits the Overture idea-to-research-to-graph-to-ticket flow by turning "
        f"`SynthesisBrief` output from `overture/synthesis.py` into a paste-ready Linear issue draft."
    )


def _problem(brief: SynthesisBrief) -> str:
    return (
        f"{brief.user_need} Without a validated ticket-writing step, Symphony cannot reliably start from the "
        "synthesis output because the required Linear title, Markdown sections, validation commands, sources, "
        "and graph provenance may be missing."
    )


def _proposed_change(candidate: CandidateTicket) -> str:
    return "\n".join(
        (
            f"Generate a Linear issue draft for `{candidate.id}`.",
            "",
            "Required behavior:",
            "",
            "- Accept the synthesis output as structured input.",
            f"- Use the candidate scope: {candidate.scope}",
            "- Emit a `title` field and a Markdown `description` field.",
            "- Format the description with the canonical Symphony-ready ticket sections.",
            "- Validate the generated payload before it is sent to Linear.",
        )
    )


def _acceptance_criteria(candidate: CandidateTicket) -> str:
    criteria = [
        "The ticket writer accepts a synthesis output and selects a candidate ticket.",
        "The generated payload includes a Linear-ready title and Markdown description.",
        "The description includes context, proposed change, acceptance criteria, validation, sources, and out-of-scope.",
        "The description includes graph provenance with source nodes, relationships, confidence, and conflicts.",
        "The payload validates against the Symphony-ready ticket schema before handoff.",
    ]
    if candidate.readiness:
        criteria.append(f"The selected candidate readiness is preserved as `{candidate.readiness}` in the generated task context.")
    return "\n".join(f"- [ ] {criterion}" for criterion in criteria)


def _validation_plan(candidate: CandidateTicket) -> str:
    plan = list(candidate.validation_plan) or ["Run the ticket writer on the sample synthesis and confirm a schema-valid draft is returned."]
    plan.append("Run `python -m pytest` and confirm the ticket writer tests pass.")
    return "\n".join(f"- {step}" for step in plan)


def _sources(brief: SynthesisBrief) -> str:
    rows: list[str] = []
    for evidence in brief.relevant_evidence.evidence:
        refs = ", ".join(evidence.source_refs) or evidence.id
        rows.append(f"- `{refs}`: {evidence.summary}")
    for claim in (*brief.relevant_evidence.evidence_backed_claims, *brief.relevant_evidence.assumptions):
        refs = ", ".join(claim.source_refs) or claim.id
        rows.append(f"- `{refs}`: {claim.statement}")
    return "\n".join(rows) if rows else "- Internal graph-only evidence: synthesis provided no external sources."


def _graph_provenance(brief: SynthesisBrief, candidate: CandidateTicket) -> str:
    concept_node_ids = (
        f"prior:{concept.id}" if concept.from_prior else concept.id
        for concept in brief.connected_concepts
        if concept.id
    )
    node_ids = tuple(dict.fromkeys((*candidate.source_node_ids, *concept_node_ids)))
    edges = tuple(
        relationship
        for concept in brief.connected_concepts
        for relationship in concept.relationships
        if relationship
    )
    return "\n".join(
        (
            f"- Nodes: {', '.join(f'`{node_id}`' for node_id in node_ids) if node_ids else 'None'}",
            f"- Edges: {'; '.join(edges) if edges else 'None'}",
            f"- Confidence: {_confidence(brief)}.",
            "- Conflicts: None.",
        )
    )


def _risk_uncertainty(brief: SynthesisBrief) -> str:
    risks = tuple(risk for risk in brief.risks_uncertainty if risk)
    if not risks:
        return "- None identified."
    return "\n".join(f"- {risk}" for risk in risks)


def _bullets(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _confidence(brief: SynthesisBrief) -> str:
    values = [
        str(claim.confidence).lower()
        for claim in (*brief.relevant_evidence.evidence_backed_claims, *brief.relevant_evidence.assumptions)
        if claim.confidence
    ]
    if "low" in values:
        return "low"
    if "medium" in values:
        return "medium"
    return "high"


def _section_bodies(description: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in description.splitlines():
        if line in REQUIRED_SECTION_HEADINGS:
            current = line
            sections[current] = []
            continue
        if current:
            sections[current].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(value)
    return ()


def _evidence_reference(value: Any) -> EvidenceReference:
    item = value if isinstance(value, Mapping) else {}
    return EvidenceReference(
        id=str(item.get("id", "")).strip(),
        summary=str(item.get("summary", "")).strip(),
        source_refs=tuple(str(ref) for ref in _sequence(item.get("source_refs", ()))),
        supports=tuple(str(ref) for ref in _sequence(item.get("supports", ()))),
    )


def _claim_reference(value: Any) -> ClaimReference:
    item = value if isinstance(value, Mapping) else {}
    return ClaimReference(
        id=str(item.get("id", "")).strip(),
        statement=str(item.get("statement", "")).strip(),
        confidence=item.get("confidence"),
        source_refs=tuple(str(ref) for ref in _sequence(item.get("source_refs", ()))),
    )


def _connected_concept(value: Any) -> ConnectedConcept:
    item = value if isinstance(value, Mapping) else {}
    return ConnectedConcept(
        id=str(item.get("id", "")).strip(),
        type=str(item.get("type", "")).strip(),
        label=str(item.get("label", "")).strip(),
        summary=str(item.get("summary", "")).strip(),
        relationships=tuple(str(ref) for ref in _sequence(item.get("relationships", ()))),
        from_prior=bool(item.get("from_prior", False)),
    )


def _candidate_ticket(value: Any) -> CandidateTicket:
    item = value if isinstance(value, Mapping) else {}
    return CandidateTicket(
        id=str(item.get("id", "")).strip(),
        title=str(item.get("title", "")).strip(),
        scope=str(item.get("scope", "")).strip(),
        validation_plan=tuple(str(step) for step in _sequence(item.get("validation_plan", ()))),
        source_node_ids=tuple(str(node_id) for node_id in _sequence(item.get("source_node_ids", ()))),
        readiness=str(item.get("readiness") or "").strip() or None,
        sprint_label=str(item.get("sprint_label") or "").strip() or None,
        priority=_priority_metadata(item.get("priority")),
        milestone=str(item.get("milestone") or "").strip() or None,
    )


def _frontmatter_lines(candidate: CandidateTicket) -> tuple[str, ...]:
    lines = ["---"]
    if candidate.sprint_label:
        lines.append(f'sprint_label = "{_toml_string(candidate.sprint_label)}"')
    if candidate.priority is not None:
        lines.append(f"priority = {candidate.priority}")
    if candidate.milestone:
        lines.append(f'milestone = "{_toml_string(candidate.milestone)}"')
    if len(lines) == 1:
        return ()
    lines.append("---")
    return ("\n".join(lines),)


def _toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _priority_metadata(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None
