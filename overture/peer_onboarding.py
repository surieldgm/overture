"""Designer peer onboarding artifact records and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .graph import GraphRecord
from .graph_store import SqliteGraphStore

TEMPLATE_NODE_ID = "component_peer_onboarding_template"
FILLED_ARTIFACT_NODE_ID = "component_designer_one_filled_artifact"
FRICTION_LOG_NODE_ID = "m1_friction_log"
INTAKE_STAGE_NODE_ID = "capability_intake_stage"
TRANSFER_NEED_NODE_ID = "need_peer_transfer_artifact"
DESIGNER_ONE_AUTHOR_ID = "designer_1"
DESIGNER_ONE_AUTHOR_EMAIL = "designer1@overture.local"

PEER_ONBOARDING_ROUTE = "/peer-onboarding/designer-one"


@dataclass(frozen=True)
class PeerOnboardingArtifact:
    id: str
    title: str
    author_id: str
    author_email: str
    template_id: str
    route: str
    sections: tuple[dict[str, Any], ...]
    intake_examples: tuple[dict[str, str], ...]
    source_nodes: tuple[str, ...]


def designer_one_peer_onboarding_records() -> tuple[GraphRecord, ...]:
    """Return the seeded graph records for Designer #1's peer handoff artifact."""

    artifact = designer_one_peer_onboarding_artifact()
    records = [
        GraphRecord(
            kind="Component",
            key=TEMPLATE_NODE_ID,
            properties={
                "label": "Peer onboarding template",
                "summary": "Shared peer onboarding template for designer-to-designer transfer.",
                "section_titles": [section["title"] for section in artifact.sections],
                "route_pattern": "/peer-onboarding/<artifact>",
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
                "sections": list(artifact.sections),
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
    ]
    return tuple(records)


def seed_designer_one_peer_onboarding_artifact(store: SqliteGraphStore) -> PeerOnboardingArtifact:
    store.upsert_records(designer_one_peer_onboarding_records())
    return load_designer_one_peer_onboarding_artifact(store)


def load_designer_one_peer_onboarding_artifact(store: SqliteGraphStore) -> PeerOnboardingArtifact:
    node = _node_by_id(store, FILLED_ARTIFACT_NODE_ID)
    if node is None:
        return seed_designer_one_peer_onboarding_artifact(store)
    return _artifact_from_node(node)


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
    for section in artifact.sections:
        title = str(section.get("title") or "").strip()
        body = str(section.get("body") or "").strip()
        bullets = section.get("bullets")
        has_bullets = isinstance(bullets, list) and any(str(item).strip() for item in bullets)
        if not title:
            errors.append("artifact section is missing a title")
        if not body and not has_bullets:
            errors.append(f"artifact section is empty: {title or '<untitled>'}")
    return errors


def designer_one_peer_onboarding_artifact() -> PeerOnboardingArtifact:
    examples = (
        {
            "title": "Feature intake: idea persistence",
            "href": "examples/intake_examples/feature-idea-persistence.md",
            "raw_intake": "Add idea persistence to Overture",
            "why_it_helped": "It showed that a short feature sentence can still preserve enough product memory to make later synthesis cite prior graph context.",
        },
        {
            "title": "Bug/friction intake: research approval latency",
            "href": "examples/intake_examples/bug-research-approval-latency.md",
            "raw_intake": "Confirmed operator friction [slow] in session m1 run run-1: research approval took too long",
            "why_it_helped": "It turned a felt workflow delay into a specific intake with a validation path instead of a vague complaint.",
        },
        {
            "title": "Integration intake: Linear export dry run",
            "href": "examples/intake_examples/integration-linear-export-dry-run.md",
            "raw_intake": "Validate an export-ready ticket payload before creating a Linear issue",
            "why_it_helped": "It kept the external Linear boundary testable without credentials and gave the ticket a crisp dry-run acceptance path.",
        },
    )
    sections = (
        {
            "title": "Start with the smallest intake sentence that still names the work",
            "body": "Designer #1 found that terse, verb-led intake worked best when it named the product object and the intended movement. The idea-persistence example started as one sentence, then the pipeline preserved its source and graph context instead of forcing a long brief at intake time.",
            "bullets": [
                "Use an imperative verb when the work is already implementation-shaped.",
                "Name the product surface or capability in the first sentence.",
                "Leave research and ticket structure for later stages unless the raw idea already contains that detail.",
            ],
        },
        {
            "title": "Treat research approval as a quality gate, not a waiting room",
            "body": "The approval step was useful when each source had a clear approve or reject decision and enough context to judge relevance. It became frustrating when source review felt slow enough to lose the intake thread, which is why Designer #1 watches for approval latency as real friction.",
            "bullets": [
                "Approve sources that directly support the acceptance criteria or validation plan.",
                "Reject sources that only restate the idea without new evidence.",
                "If approval feels slow, capture that as friction immediately while the context is fresh.",
            ],
        },
        {
            "title": "Use the wizard as a checkpoint sequence",
            "body": "Designer #1 used the wizard moments as deliberate gates: intake preserves the raw idea, research explains why the ticket is grounded, synthesis checks the product argument, and ticket review protects the Linear handoff. The confusing moments were mostly around whether the current session had enough saved context to continue.",
            "bullets": [
                "Before advancing, check that the current page names the intake or artifact being reviewed.",
                "Do not rewrite the ticket to hide missing research; go back to the earlier checkpoint.",
                "When a page feels like a placeholder, look for the saved artifact path or route before assuming work is lost.",
            ],
        },
        {
            "title": "Heuristics Designer #1 would give Designer #2",
            "body": "The strongest tickets came from pairing one concrete intake with explicit validation and graph provenance. Designer #1 would tell Designer #2 to keep examples close, preserve the original intake words, and make every claim trace back to a source file, graph node, or observed friction note.",
            "bullets": [
                "Prefer three distinct example shapes before generalizing a pattern.",
                "Keep the original intake link beside any rewritten summary.",
                "Write acceptance criteria so a smoke test can prove the artifact still has substance.",
            ],
        },
        {
            "title": "Examples to read before the first solo pass",
            "body": "Designer #2 should read the three embedded intakes in order: feature, friction, then integration. Together they show how Designer #1 moved from raw idea, to evidence, to a Linear-ready ticket without losing the original operator signal.",
            "examples": list(examples),
        },
        {
            "title": "Watch-outs from earlier friction",
            "body": "The M1 friction log is most useful as a warning system. Slow approval and unclear handoff context are not side notes; they are signals that the artifact or wizard page should expose the current source, author, and next review decision more clearly.",
            "bullets": [
                "If the next action is unclear, stop and record the ambiguity rather than filling in silence.",
                "If export or approval needs credentials, run a dry-run or fake-client path first.",
                "If a peer cannot identify the source intake from the artifact, the handoff is not ready.",
            ],
        },
    )
    return PeerOnboardingArtifact(
        id=FILLED_ARTIFACT_NODE_ID,
        title="Designer #1 peer onboarding artifact",
        author_id=DESIGNER_ONE_AUTHOR_ID,
        author_email=DESIGNER_ONE_AUTHOR_EMAIL,
        template_id=TEMPLATE_NODE_ID,
        route=PEER_ONBOARDING_ROUTE,
        sections=sections,
        intake_examples=examples,
        source_nodes=(TEMPLATE_NODE_ID, FRICTION_LOG_NODE_ID, INTAKE_STAGE_NODE_ID, TRANSFER_NEED_NODE_ID),
    )


def _node_by_id(store: SqliteGraphStore, node_id: str) -> Mapping[str, Any] | None:
    for node in store.list_nodes(kind="Component"):
        if str(node.get("id")) == node_id:
            return node
    return None


def _artifact_from_node(node: Mapping[str, Any]) -> PeerOnboardingArtifact:
    properties = node.get("properties")
    payload = properties if isinstance(properties, Mapping) else node
    sections = tuple(item for item in payload.get("sections", ()) if isinstance(item, dict))
    examples = tuple(item for item in payload.get("intake_examples", ()) if isinstance(item, dict))
    source_nodes = tuple(str(item) for item in payload.get("source_nodes", ()))
    return PeerOnboardingArtifact(
        id=str(node.get("id") or FILLED_ARTIFACT_NODE_ID),
        title=str(payload.get("label") or payload.get("title") or "Designer #1 peer onboarding artifact"),
        author_id=str(payload.get("author_id") or ""),
        author_email=str(payload.get("author_email") or ""),
        template_id=str(payload.get("template_id") or ""),
        route=str(payload.get("viewer_route") or PEER_ONBOARDING_ROUTE),
        sections=sections,
        intake_examples=examples,
        source_nodes=source_nodes,
    )
