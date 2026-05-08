"""Peer onboarding template schema, filled artifact, and validation helpers."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .graph import GraphRecord
from .graph_store import SqliteGraphStore

PEER_ONBOARDING_SCHEMA_VERSION = "2026-05-07"

TEMPLATE_NODE_ID = "component_peer_onboarding_template"
SECOND_GENERATION_TEMPLATE_NODE_ID = "component_peer_template_v2"
FILLED_ARTIFACT_NODE_ID = "component_designer_one_filled_artifact"
SECOND_GENERATION_FILLED_ARTIFACT_NODE_ID = "component_designer_three_peer_onboarding_artifact"
SPRINT_FIVE_OBSERVATION_NODE_ID = "component_observation_log"
FRICTION_LOG_NODE_ID = "m1_friction_log"
INTAKE_STAGE_NODE_ID = "capability_intake_stage"
TRANSFER_NEED_NODE_ID = "need_peer_transfer_artifact"
TRANSFER_EVOLUTION_NEED_NODE_ID = "need_peer_transfer_evolves"
DESIGNER_ONE_AUTHOR_ID = "designer_1"
DESIGNER_ONE_AUTHOR_EMAIL = "designer1@overture.local"
DESIGNER_TWO_AUTHOR_ID = "designer_2"
DESIGNER_TWO_AUTHOR_EMAIL = "designer2@overture.local"
PEER_ONBOARDING_ROUTE = "/peer-onboarding"

PEER_ONBOARDING_SCHEMA: tuple[dict[str, object], ...] = (
    {
        "id": "intake_worked",
        "order": 1,
        "title": "What intake worked",
        "description": "Capture the prompts, examples, and constraints that helped the first designer start cleanly.",
        "fields": (
            {
                "id": "summary",
                "label": "Useful intake pattern",
                "kind": "free_text",
                "required": False,
            },
            {
                "id": "example_prompts",
                "label": "Example prompts",
                "kind": "list_text",
                "required": False,
            },
        ),
    },
    {
        "id": "research_approval",
        "order": 2,
        "title": "What research approval looked like",
        "description": "Explain how sources were inspected and what made a source acceptable to carry forward.",
        "fields": (
            {
                "id": "approval_summary",
                "label": "Approval summary",
                "kind": "free_text",
                "required": False,
            },
            {
                "id": "approved_source_traits",
                "label": "Approved source traits",
                "kind": "list_text",
                "required": False,
            },
        ),
    },
    {
        "id": "wizard_watchouts",
        "order": 3,
        "title": "What to watch out for at each wizard step",
        "description": "Structured notes for each current wizard step so the next designer can keep context while running a session.",
        "fields": (
            {
                "id": "step_notes",
                "label": "Wizard step notes",
                "kind": "wizard_step_notes",
                "required": False,
                "steps": ("Intake", "Research", "Synthesis", "Ticket", "Export"),
            },
        ),
    },
    {
        "id": "sprint5_observation_patterns",
        "order": 4,
        "title": "Sprint 5 observation patterns to carry forward",
        "description": "Ground the next handoff in observed Designer #2 friction so Designer #3 does not rediscover the same workflow gaps.",
        "fields": (
            {
                "id": "pattern_summary",
                "label": "Observation pattern summary",
                "kind": "free_text",
                "required": False,
                "source_node": SPRINT_FIVE_OBSERVATION_NODE_ID,
            },
            {
                "id": "handoff_adjustments",
                "label": "Handoff adjustments",
                "kind": "list_text",
                "required": False,
                "source_node": SPRINT_FIVE_OBSERVATION_NODE_ID,
            },
        ),
    },
)


@dataclass(frozen=True)
class PeerOnboardingArtifact:
    id: str
    title: str
    author_id: str
    author_email: str
    template_id: str
    route: str
    template: dict[str, object]
    intake_examples: tuple[dict[str, str], ...]
    source_nodes: tuple[str, ...]
    generation: int = 1
    audience_id: str = "designer_2"
    coauthor_ids: tuple[str, ...] = ()

    @property
    def sections(self) -> list[dict[str, object]]:
        return ordered_peer_onboarding_sections(self.template)


def initialize_peer_onboarding_template(author_id: str, author_email: str) -> dict[str, object]:
    """Return an empty active-version peer onboarding template for an author."""

    return {
        "schema_version": PEER_ONBOARDING_SCHEMA_VERSION,
        "author": {
            "id": str(author_id),
            "email": str(author_email),
        },
        "sections": [_empty_section(section) for section in PEER_ONBOARDING_SCHEMA],
    }


def ordered_peer_onboarding_sections(template: Mapping[str, object]) -> list[dict[str, object]]:
    """Return template sections sorted by order while tolerating future extensions."""

    raw_sections = template.get("sections", [])
    if not isinstance(raw_sections, list):
        return []
    sections = [section for section in raw_sections if isinstance(section, dict)]
    return sorted(sections, key=_section_order)


def designer_one_peer_onboarding_records() -> tuple[GraphRecord, ...]:
    """Return the seeded graph records for Designer #1's peer handoff artifact."""

    artifact = designer_one_peer_onboarding_artifact()
    return (
        GraphRecord(
            kind="Component",
            key=TEMPLATE_NODE_ID,
            properties={
                "label": "Peer onboarding template",
                "summary": "Shared peer onboarding template for designer-to-designer transfer.",
                "schema_version": PEER_ONBOARDING_SCHEMA_VERSION,
                "section_ids": [section["id"] for section in PEER_ONBOARDING_SCHEMA],
                "route_pattern": PEER_ONBOARDING_ROUTE,
            },
        ),
        GraphRecord(
            kind="Need",
            key=TRANSFER_NEED_NODE_ID,
            properties={
                "label": "Peer transfer artifact",
                "summary": "Designer #2 needs a concrete artifact grounded in Designer #1's intake and research workflow.",
            },
        ),
        GraphRecord(
            kind="Component",
            key=FRICTION_LOG_NODE_ID,
            properties={
                "label": "M1 friction log",
                "summary": "Confirmed early dogfooding friction, including slow research approval and unclear handoff context.",
                "source_refs": ["tests/test_friction_log.py", "tests/test_dogfooding_day_one_smoke.py"],
            },
        ),
        GraphRecord(
            kind="Capability",
            key=INTAKE_STAGE_NODE_ID,
            properties={
                "label": "Intake stage",
                "summary": "The Overture intake capability that turns raw designer ideas into durable records for research, synthesis, and ticket drafting.",
                "source_refs": [example["href"] for example in artifact.intake_examples],
            },
        ),
        GraphRecord(
            kind="Component",
            key=FILLED_ARTIFACT_NODE_ID,
            properties={
                "label": artifact.title,
                "summary": "Designer #1's filled peer onboarding artifact for Designer #2.",
                "author_id": artifact.author_id,
                "author_email": artifact.author_email,
                "template_id": artifact.template_id,
                "viewer_route": artifact.route,
                "template": artifact.template,
                "intake_examples": list(artifact.intake_examples),
                "source_nodes": list(artifact.source_nodes),
            },
        ),
        GraphRecord(
            kind="requires",
            key=f"{TRANSFER_NEED_NODE_ID}:requires:{FILLED_ARTIFACT_NODE_ID}",
            properties={"from": TRANSFER_NEED_NODE_ID, "to": FILLED_ARTIFACT_NODE_ID},
        ),
        GraphRecord(
            kind="instantiates",
            key=f"{FILLED_ARTIFACT_NODE_ID}:instantiates:{TEMPLATE_NODE_ID}",
            properties={"from": FILLED_ARTIFACT_NODE_ID, "to": TEMPLATE_NODE_ID},
        ),
        GraphRecord(
            kind="references",
            key=f"{FILLED_ARTIFACT_NODE_ID}:references:{FRICTION_LOG_NODE_ID}",
            properties={"from": FILLED_ARTIFACT_NODE_ID, "to": FRICTION_LOG_NODE_ID},
        ),
        GraphRecord(
            kind="embeds",
            key=f"{FILLED_ARTIFACT_NODE_ID}:embeds:{INTAKE_STAGE_NODE_ID}",
            properties={"from": FILLED_ARTIFACT_NODE_ID, "to": INTAKE_STAGE_NODE_ID},
        ),
    )


def peer_onboarding_records() -> tuple[GraphRecord, ...]:
    """Return all seeded peer onboarding records across generations."""

    return designer_one_peer_onboarding_records() + second_generation_peer_onboarding_records()


def seed_designer_one_peer_onboarding_artifact(store: SqliteGraphStore) -> PeerOnboardingArtifact:
    store.upsert_records(designer_one_peer_onboarding_records())
    return load_designer_one_peer_onboarding_artifact(store)


def seed_peer_onboarding_artifacts(store: SqliteGraphStore) -> tuple[PeerOnboardingArtifact, ...]:
    store.upsert_records(peer_onboarding_records())
    return load_peer_onboarding_artifacts(store)


def load_designer_one_peer_onboarding_artifact(store: SqliteGraphStore) -> PeerOnboardingArtifact:
    node = _node_by_id(store, FILLED_ARTIFACT_NODE_ID)
    if node is None:
        return seed_designer_one_peer_onboarding_artifact(store)
    return _artifact_from_node(node)


def load_peer_onboarding_artifacts(store: SqliteGraphStore) -> tuple[PeerOnboardingArtifact, ...]:
    nodes = [
        node
        for node in store.list_nodes(kind="Component")
        if _artifact_payload(node).get("viewer_route") == PEER_ONBOARDING_ROUTE
        and _artifact_payload(node).get("template")
    ]
    if not nodes:
        return seed_peer_onboarding_artifacts(store)
    artifacts = tuple(_artifact_from_node(node) for node in nodes)
    return tuple(sorted(artifacts, key=lambda artifact: (artifact.generation, artifact.title)))


def load_latest_peer_onboarding_artifact(store: SqliteGraphStore) -> PeerOnboardingArtifact:
    artifacts = load_peer_onboarding_artifacts(store)
    return max(artifacts, key=lambda artifact: (artifact.generation, artifact.title))


def validate_designer_one_peer_onboarding_artifact(artifact: PeerOnboardingArtifact) -> list[str]:
    errors: list[str] = []
    if artifact.id != FILLED_ARTIFACT_NODE_ID:
        errors.append("filled artifact node id is incorrect")
    if artifact.author_id != DESIGNER_ONE_AUTHOR_ID:
        errors.append("filled artifact author is not Designer #1")
    if artifact.template_id != TEMPLATE_NODE_ID:
        errors.append("filled artifact does not instantiate the peer onboarding template")
    if len(artifact.intake_examples) < 3:
        errors.append("filled artifact includes fewer than three intake examples")
    for index, example in enumerate(artifact.intake_examples, start=1):
        if not example.get("title") or not example.get("href") or not example.get("raw_intake"):
            errors.append(f"intake example {index} is missing title, link, or raw intake")
        elif not Path(example["href"]).exists():
            errors.append(f"intake example {index} link does not exist: {example['href']}")
    for section in ordered_peer_onboarding_sections(artifact.template):
        section_id = str(section.get("id") or "<unknown>")
        for field in section.get("fields", ()):
            if not isinstance(field, Mapping):
                errors.append(f"artifact section {section_id} has a malformed field")
                continue
            if not _value_is_non_empty(field.get("value")):
                errors.append(f"artifact field is empty: {section_id}.{field.get('id', '<unknown>')}")
    return errors


def validate_peer_onboarding_artifact(artifact: PeerOnboardingArtifact) -> list[str]:
    errors: list[str] = []
    if artifact.template_id not in {TEMPLATE_NODE_ID, SECOND_GENERATION_TEMPLATE_NODE_ID}:
        errors.append("filled artifact does not instantiate a peer onboarding template")
    if artifact.generation < 1:
        errors.append("filled artifact generation is invalid")
    if not artifact.audience_id:
        errors.append("filled artifact audience is missing")
    if not artifact.author_id:
        errors.append("filled artifact author is missing")
    if artifact.generation >= 2 and len(artifact.coauthor_ids) < 2:
        errors.append("second-generation artifact must list Designer #1 and Designer #2 as coauthors")
    if len(artifact.intake_examples) < 3:
        errors.append("filled artifact includes fewer than three intake examples")
    for index, example in enumerate(artifact.intake_examples, start=1):
        if not example.get("title") or not example.get("href") or not example.get("raw_intake"):
            errors.append(f"intake example {index} is missing title, link, or raw intake")
        elif not Path(example["href"]).exists():
            errors.append(f"intake example {index} link does not exist: {example['href']}")
    for section in ordered_peer_onboarding_sections(artifact.template):
        section_id = str(section.get("id") or "<unknown>")
        for field in section.get("fields", ()):
            if not isinstance(field, Mapping):
                errors.append(f"artifact section {section_id} has a malformed field")
                continue
            if not _value_is_non_empty(field.get("value")):
                errors.append(f"artifact field is empty: {section_id}.{field.get('id', '<unknown>')}")
    if artifact.generation >= 2:
        section_ids = {str(section.get("id")) for section in ordered_peer_onboarding_sections(artifact.template)}
        if "sprint5_observation_patterns" not in section_ids:
            errors.append("second-generation artifact is missing Sprint 5 observation patterns")
        if SPRINT_FIVE_OBSERVATION_NODE_ID not in artifact.source_nodes:
            errors.append("second-generation artifact does not cite the observation log")
    return errors


def designer_one_peer_onboarding_artifact() -> PeerOnboardingArtifact:
    examples = (
        {
            "title": "Feature intake: idea persistence",
            "href": "examples/intake_examples/feature-idea-persistence.md",
            "raw_intake": "Add idea persistence to Overture",
            "why_it_helped": "A terse feature sentence preserved enough product memory for later synthesis to cite prior graph context.",
        },
        {
            "title": "Bug/friction intake: research approval latency",
            "href": "examples/intake_examples/bug-research-approval-latency.md",
            "raw_intake": "Confirmed operator friction [slow] in session m1 run run-1: research approval took too long",
            "why_it_helped": "A felt workflow delay became a specific intake with a validation path instead of a vague complaint.",
        },
        {
            "title": "Integration intake: Linear export dry run",
            "href": "examples/intake_examples/integration-linear-export-dry-run.md",
            "raw_intake": "Validate an export-ready ticket payload before creating a Linear issue",
            "why_it_helped": "The external Linear boundary stayed testable without credentials and produced crisp dry-run acceptance criteria.",
        },
    )
    template = initialize_peer_onboarding_template(DESIGNER_ONE_AUTHOR_ID, DESIGNER_ONE_AUTHOR_EMAIL)
    template["sections"] = [
        section
        for section in template["sections"]
        if isinstance(section, dict) and section.get("id") != "sprint5_observation_patterns"
    ]
    _set_field(
        template,
        "intake_worked",
        "summary",
        "Start from the smallest verb-led intake sentence that still names the product object and movement. Designer #1's strongest examples kept original words close, then let research and synthesis add structure later.",
    )
    _set_field(
        template,
        "intake_worked",
        "example_prompts",
        [f"{example['raw_intake']} ({example['href']})" for example in examples],
    )
    _set_field(
        template,
        "research_approval",
        "approval_summary",
        "Research approval worked when each candidate source had a clear approve or reject decision and enough context to judge relevance. It became confusing when source review took long enough for Designer #1 to lose the intake thread.",
    )
    _set_field(
        template,
        "research_approval",
        "approved_source_traits",
        [
            "Directly supports the acceptance criteria or validation plan.",
            "Preserves a source link or file path that Designer #2 can reopen.",
            "Adds evidence beyond restating the raw intake.",
            "Keeps manual approval explicit instead of hiding it behind generated prose.",
        ],
    )
    _set_field(
        template,
        "wizard_watchouts",
        "step_notes",
        [
            {
                "step": "Intake",
                "note": "Keep the original intake words visible; do not over-brief before the idea is preserved.",
            },
            {
                "step": "Research",
                "note": "Approve only sources that make the ticket easier to validate, and record approval latency as friction when it interrupts flow.",
            },
            {
                "step": "Synthesis",
                "note": "Check that the brief still cites the source intake and prior graph context before drafting the ticket.",
            },
            {
                "step": "Ticket",
                "note": "Write acceptance criteria so a smoke test can prove the artifact has substance, not only structure.",
            },
            {
                "step": "Export",
                "note": "Use dry-run export or fake-client paths before credentials are available; never let integration setup block content review.",
            },
        ],
    )
    return PeerOnboardingArtifact(
        id=FILLED_ARTIFACT_NODE_ID,
        title="Designer #1 peer onboarding artifact",
        author_id=DESIGNER_ONE_AUTHOR_ID,
        author_email=DESIGNER_ONE_AUTHOR_EMAIL,
        template_id=TEMPLATE_NODE_ID,
        route=PEER_ONBOARDING_ROUTE,
        template=template,
        intake_examples=examples,
        source_nodes=(TEMPLATE_NODE_ID, FRICTION_LOG_NODE_ID, INTAKE_STAGE_NODE_ID, TRANSFER_NEED_NODE_ID),
        generation=1,
        audience_id="designer_2",
        coauthor_ids=(DESIGNER_ONE_AUTHOR_ID,),
    )


def second_generation_peer_onboarding_records() -> tuple[GraphRecord, ...]:
    """Return graph records for the Designer #3 second-generation handoff."""

    artifact = second_generation_peer_onboarding_artifact()
    return (
        GraphRecord(
            kind="Component",
            key=SECOND_GENERATION_TEMPLATE_NODE_ID,
            properties={
                "label": "Second-generation peer onboarding template",
                "summary": "Extended peer onboarding template carrying Sprint 5 observation-log learnings into Designer #3 onboarding.",
                "schema_version": PEER_ONBOARDING_SCHEMA_VERSION,
                "extends": TEMPLATE_NODE_ID,
                "section_ids": [section["id"] for section in PEER_ONBOARDING_SCHEMA],
                "route_pattern": PEER_ONBOARDING_ROUTE,
            },
        ),
        GraphRecord(
            kind="Need",
            key=TRANSFER_EVOLUTION_NEED_NODE_ID,
            properties={
                "label": "Peer transfer evolves",
                "summary": "Each onboarding generation should absorb observed friction from the previous designer handoff.",
            },
        ),
        GraphRecord(
            kind="Component",
            key=SPRINT_FIVE_OBSERVATION_NODE_ID,
            properties={
                "label": "Sprint 5 observation log",
                "summary": "Designer #2 solo-session observations surfaced context loss at route transitions, unclear source approval expectations, and uncertainty about preserving intake wording.",
                "source_refs": ["tests/test_ui_wizard_smoke.py", "overture/observation_log.py"],
            },
        ),
        GraphRecord(
            kind="Component",
            key=SECOND_GENERATION_FILLED_ARTIFACT_NODE_ID,
            properties={
                "label": artifact.title,
                "summary": "Designer #1 and Designer #2's second-generation peer onboarding artifact for Designer #3.",
                "author_id": artifact.author_id,
                "author_email": artifact.author_email,
                "coauthor_ids": list(artifact.coauthor_ids),
                "generation": artifact.generation,
                "audience_id": artifact.audience_id,
                "template_id": artifact.template_id,
                "viewer_route": artifact.route,
                "template": artifact.template,
                "intake_examples": list(artifact.intake_examples),
                "source_nodes": list(artifact.source_nodes),
            },
        ),
        GraphRecord(
            kind="requires",
            key=f"{TRANSFER_EVOLUTION_NEED_NODE_ID}:requires:{SECOND_GENERATION_FILLED_ARTIFACT_NODE_ID}",
            properties={"from": TRANSFER_EVOLUTION_NEED_NODE_ID, "to": SECOND_GENERATION_FILLED_ARTIFACT_NODE_ID},
        ),
        GraphRecord(
            kind="instantiates",
            key=f"{SECOND_GENERATION_FILLED_ARTIFACT_NODE_ID}:instantiates:{SECOND_GENERATION_TEMPLATE_NODE_ID}",
            properties={"from": SECOND_GENERATION_FILLED_ARTIFACT_NODE_ID, "to": SECOND_GENERATION_TEMPLATE_NODE_ID},
        ),
        GraphRecord(
            kind="references",
            key=f"{SECOND_GENERATION_FILLED_ARTIFACT_NODE_ID}:references:{SPRINT_FIVE_OBSERVATION_NODE_ID}",
            properties={"from": SECOND_GENERATION_FILLED_ARTIFACT_NODE_ID, "to": SPRINT_FIVE_OBSERVATION_NODE_ID},
        ),
        GraphRecord(
            kind="references",
            key=f"{SECOND_GENERATION_FILLED_ARTIFACT_NODE_ID}:references:{FILLED_ARTIFACT_NODE_ID}",
            properties={"from": SECOND_GENERATION_FILLED_ARTIFACT_NODE_ID, "to": FILLED_ARTIFACT_NODE_ID},
        ),
    )


def second_generation_peer_onboarding_artifact() -> PeerOnboardingArtifact:
    first_generation = designer_one_peer_onboarding_artifact()
    coauthor_email = f"{DESIGNER_ONE_AUTHOR_EMAIL},{DESIGNER_TWO_AUTHOR_EMAIL}"
    template = initialize_peer_onboarding_template("designer_1+designer_2", coauthor_email)

    _set_field(
        template,
        "intake_worked",
        "summary",
        "Designer #1's verb-led intake pattern still works, but Designer #2 added a handoff rule: keep the original wording visible beside any refined brief so Designer #3 can recover intent after navigation or review delays.",
    )
    _set_field(
        template,
        "intake_worked",
        "example_prompts",
        [f"{example['raw_intake']} ({example['href']})" for example in first_generation.intake_examples],
    )
    _set_field(
        template,
        "research_approval",
        "approval_summary",
        "Designer #2's Sprint 5 observation log showed that source approval expectations must be stated before review. Designer #3 should approve sources only when the source directly sharpens acceptance criteria, validation, or graph provenance.",
    )
    _set_field(
        template,
        "research_approval",
        "approved_source_traits",
        [
            "Names the ticket behavior or artifact it proves.",
            "Keeps enough path, URL, or citation detail for a reviewer to reopen it.",
            "Separates evidence from inference so synthesis does not overclaim.",
            "Makes the next manual approval decision obvious.",
        ],
    )
    _set_field(
        template,
        "wizard_watchouts",
        "step_notes",
        [
            {
                "step": "Intake",
                "note": "Preserve Designer #3's first sentence and add constraints after it; Designer #2 lost confidence when the raw ask disappeared too early.",
            },
            {
                "step": "Research",
                "note": "Review candidate sources against acceptance criteria before reading generated summaries, then record rejected-source rationale while context is fresh.",
            },
            {
                "step": "Synthesis",
                "note": "Check that every synthesized claim traces back to an approved source or graph node, especially after a route transition.",
            },
            {
                "step": "Ticket",
                "note": "Include a validation command and one UI path when the behavior is app-facing; Designer #2 needed both to hand work off cleanly.",
            },
            {
                "step": "Export",
                "note": "Use dry-run payload review first, then export only after the ticket has explicit acceptance criteria and no missing source links.",
            },
        ],
    )
    _set_field(
        template,
        "sprint5_observation_patterns",
        "pattern_summary",
        "Sprint 5 observations from Designer #2's solo flow clustered around three frictions: losing the raw intake wording across transitions, delayed source approval decisions, and unclear proof expectations when the ticket became app-facing.",
    )
    _set_field(
        template,
        "sprint5_observation_patterns",
        "handoff_adjustments",
        [
            "Carry a short source-of-truth note into each wizard stage: raw ask, current decision, and next proof.",
            "Name the approval rule before reviewing sources so Designer #3 can reject weak evidence quickly.",
            "Turn every app-facing recommendation into a visible route check plus a unittest command.",
        ],
    )
    return PeerOnboardingArtifact(
        id=SECOND_GENERATION_FILLED_ARTIFACT_NODE_ID,
        title="Designer #1 + Designer #2 peer onboarding artifact for Designer #3",
        author_id="designer_1+designer_2",
        author_email=coauthor_email,
        template_id=SECOND_GENERATION_TEMPLATE_NODE_ID,
        route=PEER_ONBOARDING_ROUTE,
        template=template,
        intake_examples=first_generation.intake_examples,
        source_nodes=(
            SECOND_GENERATION_TEMPLATE_NODE_ID,
            TEMPLATE_NODE_ID,
            SPRINT_FIVE_OBSERVATION_NODE_ID,
            FILLED_ARTIFACT_NODE_ID,
            TRANSFER_EVOLUTION_NEED_NODE_ID,
        ),
        generation=2,
        audience_id="designer_3",
        coauthor_ids=(DESIGNER_ONE_AUTHOR_ID, DESIGNER_TWO_AUTHOR_ID),
    )


def _empty_section(section_schema: Mapping[str, object]) -> dict[str, object]:
    section = {
        "id": section_schema["id"],
        "order": section_schema["order"],
        "title": section_schema["title"],
        "description": section_schema["description"],
        "fields": [],
    }
    for field_schema in section_schema.get("fields", ()):
        if not isinstance(field_schema, Mapping):
            continue
        field = deepcopy(dict(field_schema))
        field["value"] = _empty_value_for_kind(str(field.get("kind", "")), field)
        section["fields"].append(field)
    return section


def _empty_value_for_kind(kind: str, field: Mapping[str, object]) -> object:
    if kind == "list_text":
        return []
    if kind == "wizard_step_notes":
        steps = field.get("steps", ())
        if not isinstance(steps, tuple):
            steps = tuple(steps) if isinstance(steps, list) else ()
        return [{"step": str(step), "note": ""} for step in steps]
    return ""


def _section_order(section: Mapping[str, object]) -> int:
    try:
        return int(section.get("order", 10_000))
    except (TypeError, ValueError):
        return 10_000


def _set_field(template: dict[str, object], section_id: str, field_id: str, value: object) -> None:
    for section in ordered_peer_onboarding_sections(template):
        if section.get("id") != section_id:
            continue
        fields = section.get("fields")
        if not isinstance(fields, list):
            return
        for field in fields:
            if isinstance(field, dict) and field.get("id") == field_id:
                field["value"] = value
                return


def _value_is_non_empty(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        if not value:
            return False
        for item in value:
            if isinstance(item, Mapping):
                if not any(str(value).strip() for key, value in item.items() if key != "step"):
                    return False
            elif not str(item).strip():
                return False
        return True
    if isinstance(value, Mapping):
        return any(str(item).strip() for item in value.values())
    return value is not None


def _node_by_id(store: SqliteGraphStore, node_id: str) -> Mapping[str, Any] | None:
    for node in store.list_nodes(kind="Component"):
        if str(node.get("id")) == node_id:
            return node
    return None


def _artifact_payload(node: Mapping[str, Any]) -> Mapping[str, Any]:
    properties = node.get("properties")
    return properties if isinstance(properties, Mapping) else node


def _artifact_from_node(node: Mapping[str, Any]) -> PeerOnboardingArtifact:
    payload = _artifact_payload(node)
    template = payload.get("template")
    template_payload = template if isinstance(template, dict) else initialize_peer_onboarding_template("", "")
    examples = tuple(item for item in payload.get("intake_examples", ()) if isinstance(item, dict))
    source_nodes = tuple(str(item) for item in payload.get("source_nodes", ()))
    coauthor_ids = tuple(str(item) for item in payload.get("coauthor_ids", ()))
    return PeerOnboardingArtifact(
        id=str(node.get("id") or FILLED_ARTIFACT_NODE_ID),
        title=str(payload.get("label") or payload.get("title") or "Designer #1 peer onboarding artifact"),
        author_id=str(payload.get("author_id") or ""),
        author_email=str(payload.get("author_email") or ""),
        template_id=str(payload.get("template_id") or ""),
        route=str(payload.get("viewer_route") or PEER_ONBOARDING_ROUTE),
        template=template_payload,
        intake_examples=examples,
        source_nodes=source_nodes,
        generation=int(payload.get("generation") or 1),
        audience_id=str(payload.get("audience_id") or "designer_2"),
        coauthor_ids=coauthor_ids,
    )
