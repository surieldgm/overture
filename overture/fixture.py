"""End-to-end fixture for the Overture MVP pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from time import perf_counter
from typing import Any, Callable, Mapping, TextIO, TypeVar
from uuid import uuid4

from .graph import GraphRecord, research_result_to_graph_records
from .graph_store import DEFAULT_GRAPH_DB_PATH, SqliteGraphStore
from .intake import IntakeRecord, create_intake_record
from .metrics_store import MetricsStore, StageMetric
from .research import CuratedSourceResearchAdapter, ResearchError, ResearchItem, ResearchResult
from .synthesis import GraphContext, SynthesisBrief, synthesize_graph_context
from .ticket_writer import validate_linear_issue_payload

DEFAULT_FIXTURE_IDEA = (
    "Use Overture itself as the MVP idea: turn a raw product idea into durable "
    "intake, curated research notes, graph records, synthesis, and a "
    "Symphony-ready Linear ticket draft with provenance."
)

TICKET_SECTION_ORDER = (
    "Context",
    "Problem",
    "Proposed change",
    "Acceptance criteria",
    "Validation plan",
    "Sources / evidence",
    "Graph provenance",
    "Dependencies",
    "Out of scope",
    "Risk / uncertainty",
    "Follow-up candidates",
)

IMPERATIVE_TITLE_VERBS = (
    "Add",
    "Define",
    "Fix",
    "Remove",
    "Migrate",
    "Expose",
    "Validate",
    "Document",
)

T = TypeVar("T")
StageObserver = Callable[["StageTransition"], None]


@dataclass(frozen=True)
class StageTransition:
    run_id: str
    intake_id: str | None
    stage_name: str
    state: str
    started_at: str
    completed_at: str | None = None
    duration_ms: int | None = None
    error_message: str | None = None


class PipelineStageError(RuntimeError):
    """Raised when a fixture stage fails with stage-specific context."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message


class TicketSchemaError(ValueError):
    """Raised when generated ticket Markdown does not match the MVP schema."""


def run_overture_fixture(
    output_dir: Path | str = Path(".overture") / "fixtures" / "overture-mvp",
    *,
    idea: str = DEFAULT_FIXTURE_IDEA,
    graph_store_base_path: Path | str | None = None,
    metrics_db_path: Path | str | None = None,
    quiet_progress: bool = False,
    progress_stream: TextIO | None = None,
    intake_factory: Callable[[str, Path], tuple[IntakeRecord, Path]] | None = None,
) -> dict[str, Path | str]:
    """Run the deterministic Overture MVP fixture and persist every stage."""

    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    metrics = _open_metrics_store(metrics_db_path)
    observers = _fixture_stage_observers(
        metrics,
        quiet_progress=quiet_progress,
        progress_stream=progress_stream,
    )
    intake_id: str | None = None
    artifacts: dict[str, Path | str] = {"run_id": run_id}

    try:
        intake_record, intake_path = _record_fixture_stage(
            observers,
            run_id,
            "intake",
            intake_id,
            lambda: (intake_factory or _create_fixture_intake)(idea, base_dir / "intake"),
        )
        intake_id = intake_record.id
        artifacts["intake"] = intake_path
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        _raise_stage("intake", exc)

    try:
        research_result, research_path = _record_fixture_stage(
            observers,
            run_id,
            "research",
            intake_id,
            lambda: _run_research_stage(base_dir, intake_record),
        )
        artifacts["research"] = research_path
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        _raise_stage("research", exc)

    try:
        graph_records, prior_context, graph_context, graph_path = _record_fixture_stage(
            observers,
            run_id,
            "graph",
            intake_id,
            lambda: _run_graph_stage(
                base_dir,
                graph_store_base_path,
                intake_record,
                research_result,
            ),
        )
        artifacts["graph"] = graph_path
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        _raise_stage("graph", exc)

    try:
        synthesis, synthesis_path = _record_fixture_stage(
            observers,
            run_id,
            "synthesis",
            intake_id,
            lambda: _run_synthesis_stage(base_dir, graph_context, prior_context),
        )
        artifacts["synthesis"] = synthesis_path
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        _raise_stage("synthesis", exc)

    try:
        ticket_path = _record_fixture_stage(
            observers,
            run_id,
            "ticket_draft",
            intake_id,
            lambda: _run_ticket_draft_stage(base_dir, synthesis, graph_context),
        )
        artifacts["ticket_draft"] = ticket_path
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        _raise_stage("ticket_draft", exc)

    return artifacts


def _record_fixture_stage(
    observers: tuple[StageObserver, ...],
    run_id: str,
    stage_name: str,
    intake_id: str | None,
    operation: Callable[[], T],
) -> T:
    started_at = _utc_now_iso()
    started_monotonic = perf_counter()
    terminal_state = "completed"
    error_message: str | None = None
    _emit_stage_transition(
        observers,
        StageTransition(
            run_id=run_id,
            intake_id=intake_id,
            stage_name=stage_name,
            state="started",
            started_at=started_at,
        ),
    )
    try:
        return operation()
    except Exception as exc:
        terminal_state = "failed"
        error_message = str(exc)
        raise
    finally:
        completed_at = _utc_now_iso()
        duration_ms = max(0, int((perf_counter() - started_monotonic) * 1000))
        _emit_stage_transition(
            observers,
            StageTransition(
                run_id=run_id,
                intake_id=intake_id,
                stage_name=stage_name,
                state=terminal_state,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                error_message=error_message,
            ),
        )


def _fixture_stage_observers(
    metrics: MetricsStore | None,
    *,
    quiet_progress: bool,
    progress_stream: TextIO | None,
) -> tuple[StageObserver, ...]:
    observers: list[StageObserver] = []
    if metrics is not None:
        observers.append(_record_stage_metric(metrics))
    if not quiet_progress:
        observers.append(_emit_progress(progress_stream or sys.stderr))
    return tuple(observers)


def _record_stage_metric(metrics: MetricsStore) -> StageObserver:
    def observe(transition: StageTransition) -> None:
        if transition.state == "started":
            return
        try:
            metrics.record(
                StageMetric(
                    run_id=transition.run_id,
                    intake_id=transition.intake_id,
                    stage_name=transition.stage_name,
                    started_at=transition.started_at,
                    completed_at=transition.completed_at or transition.started_at,
                    duration_ms=transition.duration_ms or 0,
                    status="success" if transition.state == "completed" else "failure",
                    error_message=transition.error_message,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive metrics boundary
            print(
                f"failed to record stage metric for {transition.stage_name}: {exc}",
                file=sys.stderr,
            )

    return observe


def _emit_progress(stream: TextIO) -> StageObserver:
    def observe(transition: StageTransition) -> None:
        if transition.state == "started":
            print(f"{transition.stage_name} started", file=stream)
            return
        assert transition.duration_ms is not None
        if transition.state == "completed":
            print(
                f"{transition.stage_name} completed {transition.duration_ms}ms",
                file=stream,
            )
            return
        detail = f": {transition.error_message}" if transition.error_message else ""
        print(
            f"{transition.stage_name} failed {transition.duration_ms}ms{detail}",
            file=stream,
        )

    return observe


def _emit_stage_transition(
    observers: tuple[StageObserver, ...],
    transition: StageTransition,
) -> None:
    for observer in observers:
        observer(transition)


def _run_research_stage(base_dir: Path, intake_record: IntakeRecord) -> tuple[ResearchResult, Path]:
    research_result = _research_overture(intake_record)
    if not research_result.ok:
        raise ValueError(_research_errors_text(research_result.errors))
    research_path = _write_json(base_dir / "research" / "research-notes.json", research_result)
    return research_result, research_path


def _run_graph_stage(
    base_dir: Path,
    graph_store_base_path: Path | str | None,
    intake_record: IntakeRecord,
    research_result: ResearchResult,
) -> tuple[tuple[GraphRecord, ...], GraphContext, GraphContext, Path]:
    graph_records = research_result_to_graph_records(research_result)
    store = SqliteGraphStore(_graph_store_db_path(graph_store_base_path))
    prior_context = store.load_context()
    for record in graph_records:
        store.upsert_record(record)
    graph_context = _graph_context_from_fixture(intake_record, research_result, graph_records)
    for record in _graph_context_to_records(graph_context):
        store.upsert_record(record)
    graph_path = _write_json(
        base_dir / "graph" / "graph-records.json",
        {
            "schema_version": "kg-minimal-v1",
            "ingestion_records": graph_records,
            "context": graph_context,
        },
    )
    return graph_records, prior_context, graph_context, graph_path


def _run_ticket_draft_stage(base_dir: Path, synthesis: SynthesisBrief, graph_context: GraphContext) -> Path:
    ticket = render_ticket_draft(synthesis, graph_context)
    validate_ticket_draft(ticket)
    ticket_path = base_dir / "ticket" / "symphony-ticket-draft.md"
    ticket_path.parent.mkdir(parents=True, exist_ok=True)
    ticket_path.write_text(ticket, encoding="utf-8")
    return ticket_path


def _run_synthesis_stage(
    base_dir: Path,
    graph_context: GraphContext,
    prior_context: GraphContext,
) -> tuple[SynthesisBrief, Path]:
    synthesis = synthesize_graph_context(graph_context, prior_context=prior_context)
    synthesis_path = _write_json(base_dir / "synthesis" / "synthesis-brief.json", synthesis)
    return synthesis, synthesis_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def render_ticket_draft(synthesis: SynthesisBrief, graph_context: GraphContext) -> str:
    """Render a Symphony-ready Linear ticket from a synthesis brief."""

    ticket = synthesis.candidate_ticket_breakdown[0]
    evidence = synthesis.relevant_evidence.evidence
    backed_claims = synthesis.relevant_evidence.evidence_backed_claims
    assumptions = synthesis.relevant_evidence.assumptions
    graph_relationships = _relationship_lines(graph_context)
    source_node_ids = _source_node_ids(graph_context, synthesis)

    evidence_lines = [
        f"- `{item.id}`: {item.summary} Reference: {', '.join(item.source_refs) or 'internal graph evidence'}."
        for item in evidence
    ]
    evidence_lines.extend(
        f"- `{claim.id}`: {claim.statement} Confidence: {_confidence_text(claim.confidence)}."
        for claim in backed_claims
    )

    risk_lines = [f"- {risk} Verification: run the fixture and inspect persisted artifacts." for risk in synthesis.risks_uncertainty]
    if assumptions:
        risk_lines.extend(
            f"- Assumption `{claim.id}`: {claim.statement} Mitigation: preserve it in graph provenance for review."
            for claim in assumptions
        )

    return "\n".join(
        [
            "# Add Overture end-to-end fixture",
            "",
            "## Context",
            (
                "Overture must prove its MVP flow can start with a raw idea and preserve each stage through "
                "research, graph records, synthesis, and a Symphony-ready ticket. The current CLI entrypoint "
                "`python -m overture` only exposes intake, so there is no single command that exercises "
                "`overture/intake.py`, `overture/research.py`, `overture/graph.py`, and `overture/synthesis.py` together."
            ),
            "",
            "## Problem",
            (
                "Generated implementation work is blocked because Symphony cannot inspect a persisted full-pipeline "
                "example. The expected outcome is a deterministic fixture that writes every intermediate artifact "
                "and rejects a non-conforming ticket draft before handoff."
            ),
            "",
            "## Proposed change",
            (
                "Add a fixture command that accepts or defaults a raw Overture idea string, creates an intake record, "
                "runs curated research notes, converts them into graph ingestion records, synthesizes a brief, and "
                "renders `symphony-ticket-draft.md`. Required behavior: persist `intake/`, `research/`, `graph/`, "
                "`synthesis/`, and `ticket/` outputs under the selected fixture directory and include the failing "
                "stage name in any pipeline error."
            ),
            "",
            "## Acceptance criteria",
            "- [ ] `python -m overture fixture --output-dir <dir>` runs the full pipeline from the default raw idea string.",
            "- [ ] The output directory contains persisted intake, research, graph, synthesis, and ticket draft artifacts.",
            "- [ ] The generated ticket draft passes the Symphony-ready ticket schema checks before it is written.",
            "- [ ] Stage failures report the stage name, such as `research` or `ticket_draft`.",
            "",
            "## Validation plan",
            "- Run `python -m overture fixture --output-dir /tmp/overture-fixture` and expect all artifact paths to print.",
            "- Run `python -m pytest -q` and expect the fixture and existing pipeline tests to pass.",
            "- Inspect `/tmp/overture-fixture/ticket/symphony-ticket-draft.md` and confirm every required ticket section is present in canonical order.",
            "",
            "## Sources / evidence",
            *(evidence_lines or ["- Internal graph-only evidence from the Overture fixture context."]),
            "",
            "## Graph provenance",
            f"- Nodes: {', '.join(f'`{node_id}`' for node_id in source_node_ids)}.",
            f"- Edges: {'; '.join(graph_relationships)}.",
            "- Confidence: high.",
            "- Conflicts: None.",
            "",
            "## Dependencies",
            "None",
            "",
            "## Out of scope",
            "- Do not add autonomous web browsing, Linear issue creation, or a persistent graph database in this fixture.",
            "",
            "## Risk / uncertainty",
            *risk_lines,
            "",
            "## Follow-up candidates",
            "- Add Linear issue creation from validated ticket drafts.",
        ]
    ) + "\n"


def validate_ticket_draft(markdown: str) -> None:
    """Validate the generated ticket draft against the documented contract."""

    lines = markdown.splitlines()
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), "")
    if not title:
        raise TicketSchemaError("missing Title heading")
    if len(title.split()) > 12:
        raise TicketSchemaError("title must be 12 words or fewer")
    if not title.startswith(IMPERATIVE_TITLE_VERBS):
        raise TicketSchemaError("title must start with an accepted imperative verb")

    headings = [line[3:].strip() for line in lines if line.startswith("## ")]
    if headings[: len(TICKET_SECTION_ORDER)] != list(TICKET_SECTION_ORDER):
        raise TicketSchemaError("required sections are missing or out of canonical order")

    sections = _sections(markdown)
    for section in TICKET_SECTION_ORDER:
        if not sections.get(section, "").strip():
            raise TicketSchemaError(f"{section} section cannot be empty")

    acceptance_lines = _section_lines(sections["Acceptance criteria"])
    if sum(line.startswith("- [ ] ") or line.startswith("- [x] ") for line in acceptance_lines) < 3:
        raise TicketSchemaError("Acceptance criteria must include at least three checkboxes")
    if not any("test" in line.lower() or "pass" in line.lower() or "validation" in line.lower() for line in acceptance_lines):
        raise TicketSchemaError("Acceptance criteria must include a validation/test criterion")

    validation_lines = _section_lines(sections["Validation plan"])
    if not any("python -m " in line or "/" in line or "`" in line for line in validation_lines):
        raise TicketSchemaError("Validation plan must include executable commands or paths")

    errors = validate_linear_issue_payload(title, markdown)
    if errors:
        raise TicketSchemaError("; ".join(errors))


def _create_fixture_intake(idea: str, store_dir: Path) -> tuple[IntakeRecord, Path]:
    return create_intake_record(idea, store_dir, source_type="fixture")


def _research_overture(intake: IntakeRecord) -> ResearchResult:
    adapter = CuratedSourceResearchAdapter(
        [
            {
                "title": "Symphony-ready Linear ticket schema",
                "citation": "docs/symphony-ready-ticket-schema.md",
                "summary": (
                    "Overture generated tickets must include canonical sections, acceptance criteria, "
                    "validation plans, sources or evidence, graph provenance, dependencies, out-of-scope "
                    "boundaries, risks, and follow-up candidates."
                ),
                "evidence_claims": [
                    "The ticket schema requires all generated tickets to include sources or internal graph evidence.",
                    "The ticket schema requires graph provenance with node identifiers, relationship labels, confidence, and conflicts.",
                    "The validation plan must include exact commands, paths, manual steps, or API calls with expected results.",
                ],
                "inference_claims": [
                    "An end-to-end fixture can prove Overture preserves enough information for Symphony to start work.",
                ],
            },
            {
                "title": "Minimal knowledge graph schema",
                "citation": "docs/minimal-knowledge-graph-schema.md",
                "summary": (
                    "The MVP graph schema preserves non-hierarchical relationships and provenance for ideas, "
                    "needs, claims, evidence, sources, risks, components, and ticket candidates."
                ),
                "evidence_claims": [
                    "The graph schema requires nodes and edges to preserve provenance source identifiers.",
                    "TicketCandidate nodes represent implementation work derived from idea, evidence, and synthesis records.",
                ],
            },
        ],
        min_relevance=0,
    )
    return adapter.research(intake)


def _graph_context_from_fixture(
    intake: IntakeRecord,
    research: ResearchResult,
    graph_records: tuple[GraphRecord, ...],
) -> GraphContext:
    timestamp = intake.created_at
    source_nodes = [
        {
            "id": record.key,
            "type": "Source",
            "label": record.properties["title"],
            "summary": f"Fixture source for {record.properties['title']}",
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
            "source_kind": "file",
            "reference": record.properties["reference"],
            "title": record.properties["title"],
            "provenance": _provenance("research", [], [record.properties["reference"]], "Source curated for the fixture."),
        }
        for record in graph_records
        if record.kind == "Source"
    ]
    evidence_nodes = [
        {
            "id": record.key,
            "type": "Evidence",
            "label": f"Research note {index + 1}",
            "summary": record.properties["summary"],
            "content": record.properties["summary"],
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
            "evidence_kind": "research_note",
            "source_id": _source_key_for_item(graph_records, record.key),
            "provenance": _provenance(
                "research",
                [f"userinput_{intake.id}"],
                [_source_reference_for_item(graph_records, record.key)],
                "Curated research note used by the MVP fixture.",
            ),
        }
        for index, record in enumerate(record for record in graph_records if record.kind == "ResearchItem")
    ]
    claim_nodes = [
        {
            "id": record.key,
            "type": "Claim",
            "label": f"Fixture claim {index + 1}",
            "summary": record.properties["text"],
            "statement": record.properties["text"],
            "claim_kind": "assumption" if record.properties["kind"] == "inference" else "fact",
            "confidence": _confidence_text(record.properties["confidence"]),
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
            "provenance": _provenance("research", [node["id"] for node in evidence_nodes], ["fixture-research"], "Research claim extracted for graph synthesis."),
        }
        for index, record in enumerate(record for record in graph_records if record.kind == "Claim")
    ]

    user_input_id = f"userinput_{intake.id}"
    idea_id = f"idea_{intake.id}"
    need_id = f"need_{intake.id}"
    component_id = f"component_{intake.id}"
    risk_id = f"risk_{intake.id}"
    ticket_id = f"ticketcandidate_{intake.id}"

    nodes: list[Mapping[str, Any]] = [
        {
            "id": user_input_id,
            "type": "UserInput",
            "label": "Overture MVP raw idea",
            "summary": intake.normalized_summary,
            "raw_text": intake.raw_text,
            "source_type": intake.source_type,
            "submitted_by": "overture-fixture",
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
            "provenance": _provenance("user_input", [], [intake.id], "Raw fixture idea entered the Overture pipeline."),
        },
        {
            "id": idea_id,
            "type": "Idea",
            "label": "Overture MVP fixture",
            "summary": "Demonstrate the complete Overture MVP pipeline with Overture as the test idea.",
            "problem_area": "idea-to-ticket orchestration",
            "intake_id": intake.id,
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
            "provenance": _provenance("synthesis", [user_input_id], [intake.id], "The fixture idea is derived from the raw intake."),
        },
        *source_nodes,
        *evidence_nodes,
        *claim_nodes,
        {
            "id": need_id,
            "type": "Need",
            "label": "Demonstrate full pipeline",
            "summary": "Maintainers need one deterministic command that proves Overture can persist every MVP stage before Symphony consumes a ticket.",
            "actor": "Overture maintainers",
            "desired_outcome": "A repeatable fixture that writes inspectable artifacts and a validated ticket draft.",
            "priority": "must",
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
            "provenance": _provenance("synthesis", [user_input_id, *[node["id"] for node in evidence_nodes]], ["fixture-synthesis"], "Need is synthesized from intake and research evidence."),
        },
        {
            "id": component_id,
            "type": "Component",
            "label": "Fixture command",
            "summary": "A CLI-accessible fixture runner that orchestrates intake, research, graph, synthesis, and ticket draft generation.",
            "component_kind": "cli",
            "owner_hint": "overture",
            "status": "proposed",
            "created_at": timestamp,
            "updated_at": timestamp,
            "provenance": _provenance("synthesis", [need_id], ["fixture-synthesis"], "A command is the smallest usable interface for fixture validation."),
        },
        {
            "id": risk_id,
            "type": "Risk",
            "label": "Fixture drift",
            "summary": "The fixture could pass while diverging from the documented ticket schema if validation is not automated.",
            "mitigation": "Validate the generated Markdown against the schema shape during the ticket draft stage.",
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
            "provenance": _provenance("synthesis", [component_id], ["docs/symphony-ready-ticket-schema.md"], "Schema drift is the primary fixture risk."),
        },
        {
            "id": ticket_id,
            "type": "TicketCandidate",
            "label": "Add Overture end-to-end fixture",
            "title": "Add Overture end-to-end fixture",
            "scope": "Create one deterministic fixture command that persists intake, research, graph, synthesis, and Symphony-ready ticket draft artifacts.",
            "validation_plan": [
                "Run the fixture command locally and confirm all artifact paths exist.",
                "Run the test suite and confirm the generated ticket draft passes schema validation.",
            ],
            "readiness": "ready",
            "status": "proposed",
            "created_at": timestamp,
            "updated_at": timestamp,
            "provenance": _provenance("synthesis", [idea_id, need_id, component_id, risk_id], ["fixture-synthesis"], "Candidate ticket closes the fixture demonstration gap."),
        },
    ]

    edges = [
        _edge(idea_id, "derived_from", user_input_id, timestamp, "Raw intake suggests the Overture fixture idea."),
        _edge(need_id, "derived_from", idea_id, timestamp, "The full-pipeline need is derived from the fixture idea."),
        *[
            _edge(node["id"], "derived_from", source_nodes[index % len(source_nodes)]["id"], timestamp, "Research note cites a curated schema source.")
            for index, node in enumerate(evidence_nodes)
        ],
        *[
            _edge(node["id"], "derived_from", evidence_nodes[index % len(evidence_nodes)]["id"], timestamp, "Claim is extracted from research evidence.")
            for index, node in enumerate(claim_nodes)
        ],
        *[
            _edge(evidence_nodes[index % len(evidence_nodes)]["id"], "supports", node["id"], timestamp, "Research evidence supports the extracted claim.")
            for index, node in enumerate(claim_nodes)
        ],
        _edge(component_id, "addresses", need_id, timestamp, "The fixture command addresses the repeatable pipeline validation need."),
        _edge(risk_id, "derived_from", component_id, timestamp, "The command must guard against schema drift."),
        _edge(ticket_id, "addresses", need_id, timestamp, "The ticket candidate implements the fixture need."),
        _edge(ticket_id, "depends_on", component_id, timestamp, "The ticket changes the fixture CLI component."),
    ]

    return GraphContext(nodes=tuple(nodes), edges=tuple(edges), claims=(), evidence=())


def _graph_store_db_path(base_path: Path | str | None) -> Path:
    if base_path is None:
        return DEFAULT_GRAPH_DB_PATH
    return Path(base_path) / "graph.sqlite"


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_plain(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _graph_context_to_records(graph_context: GraphContext) -> tuple[GraphRecord, ...]:
    records: list[GraphRecord] = []
    for node in graph_context.nodes:
        node_id = str(node.get("id") or "")
        node_type = str(node.get("type") or node.get("kind") or "")
        if not node_id or not node_type:
            continue
        records.append(
            GraphRecord(
                kind=node_type,
                key=node_id,
                properties={str(key): value for key, value in node.items() if key != "id"},
            )
        )
    for edge in graph_context.edges:
        from_id = str(edge.get("from") or "")
        to_id = str(edge.get("to") or "")
        edge_type = str(edge.get("type") or edge.get("kind") or "")
        if not from_id or not to_id or not edge_type:
            continue
        edge_id = str(edge.get("id") or f"{from_id}:{edge_type}:{to_id}")
        records.append(
            GraphRecord(
                kind=edge_type,
                key=edge_id,
                properties={str(key): value for key, value in edge.items() if key != "id"},
            )
        )
    return tuple(records)


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _open_metrics_store(db_path: Path | str | None) -> MetricsStore | None:
    try:
        if db_path is None:
            return MetricsStore()
        return MetricsStore(db_path)
    except Exception as exc:  # pragma: no cover - defensive metrics boundary
        print(f"failed to open metrics store: {exc}", file=sys.stderr)
        return None


def _raise_stage(stage: str, exc: Exception) -> None:
    if isinstance(exc, PipelineStageError):
        raise exc
    raise PipelineStageError(stage, str(exc)) from exc


def _research_errors_text(errors: tuple[ResearchError, ...]) -> str:
    return "; ".join(f"{error.code}: {error.message}" for error in errors) or "research produced no items"


def _sections(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current:
            sections[current].append(line)
    return {section: "\n".join(lines).strip() for section, lines in sections.items()}


def _section_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _relationship_lines(graph_context: GraphContext) -> list[str]:
    return [
        f"`{edge['from']}` `{edge['type']}` `{edge['to']}`"
        for edge in graph_context.edges
        if edge.get("from") and edge.get("type") and edge.get("to")
    ]


def _source_node_ids(graph_context: GraphContext, synthesis: SynthesisBrief) -> list[str]:
    current_ids = [str(node["id"]) for node in graph_context.nodes if node.get("id")]
    prior_ids = [f"prior:{concept.id}" for concept in synthesis.connected_concepts if concept.id and concept.from_prior]
    return list(dict.fromkeys((*current_ids, *prior_ids)))


def _confidence_text(value: str | float | None) -> str:
    if isinstance(value, str) and value in {"high", "medium", "low"}:
        return value
    if isinstance(value, (int, float)):
        if value >= 0.75:
            return "high"
        if value >= 0.45:
            return "medium"
    return "low"


def _provenance(origin: str, source_node_ids: list[str], source_refs: list[str], rationale: str) -> dict[str, Any]:
    return {
        "origin": origin,
        "source_node_ids": source_node_ids,
        "source_refs": source_refs,
        "created_by": "overture-fixture",
        "confidence": "high",
        "rationale": rationale,
    }


def _edge(source: str, edge_type: str, target: str, timestamp: str, summary: str) -> Mapping[str, Any]:
    return {
        "id": f"{source}__{edge_type}__{target}",
        "type": edge_type,
        "from": source,
        "to": target,
        "summary": summary,
        "confidence": "high",
        "created_at": timestamp,
        "provenance": _provenance("synthesis", [source, target], ["fixture-graph"], summary),
    }


def _source_key_for_item(records: tuple[GraphRecord, ...], item_key: str) -> str:
    for record in records:
        if record.kind == "CITES" and record.properties.get("from") == item_key:
            return str(record.properties.get("to") or "")
    return ""


def _source_reference_for_item(records: tuple[GraphRecord, ...], item_key: str) -> str:
    source_key = _source_key_for_item(records, item_key)
    for record in records:
        if record.kind == "Source" and record.key == source_key:
            return str(record.properties.get("reference") or record.properties.get("title") or source_key)
    return "fixture-research"
