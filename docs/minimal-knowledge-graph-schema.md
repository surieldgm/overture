# Minimal Knowledge Graph Schema

This schema defines the minimum graph contract Overture needs for the MVP idea
intake, research, synthesis, and ticket-generation loop. The graph preserves
relationship topology and provenance so isolated ideas can later connect to
existing knowledge instead of being reduced to a flat summary.

## Goals

- Preserve non-hierarchical relationships between product ideas, needs, claims,
  evidence, sources, constraints, risks, components, and ticket candidates.
- Make every claim and synthesized insight traceable to user input, evidence, or
  prior graph nodes.
- Allow new ideas to enter as sparse islands and gain links as research and
  synthesis discover related graph knowledge.
- Keep the MVP schema small enough to serialize as JSON records, graph database
  nodes, or in-memory dataclasses without changing semantics.

## Graph Record Shape

Every graph is a set of nodes and directed edges:

```json
{
  "schema_version": "kg-minimal-v1",
  "nodes": [],
  "edges": []
}
```

### Node Required Fields

Every node, regardless of type, has these required fields:

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Stable node ID. Prefix with the lowercase node type, such as `idea_overture_mvp`. |
| `type` | enum | One of the node types defined below. |
| `label` | string | Short human-readable label for graph review and ticket generation. |
| `summary` | string | Concise factual summary of the node content. |
| `status` | enum | `proposed`, `active`, `superseded`, `rejected`, or `resolved`. |
| `created_at` | ISO-8601 string | Time the node was first written to the graph. |
| `updated_at` | ISO-8601 string | Time the node was last changed. |
| `provenance` | object | Provenance bundle defined in [Provenance](#provenance). |

Optional fields may be added per node type, but they must not replace the
required fields.

### Edge Required Fields

Every edge has these required fields:

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Stable edge ID, usually `<from>__<type>__<to>`. |
| `type` | enum | One of the edge types defined below. |
| `from` | string | Source node ID. |
| `to` | string | Target node ID. |
| `summary` | string | Short statement explaining why the relationship exists. |
| `confidence` | enum | `high`, `medium`, or `low`. |
| `created_at` | ISO-8601 string | Time the edge was first written to the graph. |
| `provenance` | object | Provenance bundle defined in [Provenance](#provenance). |

Edges are directed. Reciprocal meaning requires a second edge. Use `relates_to`
for weak or exploratory topology when the stronger relationship is not yet
known.

## Provenance

Every node and edge includes a provenance bundle:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `origin` | enum | yes | `user_input`, `research`, `synthesis`, `system`, or `human_review`. |
| `source_node_ids` | string array | yes | Graph nodes that directly produced this record. Empty only for initial `UserInput` nodes. |
| `source_refs` | string array | yes | External or internal stable references such as URLs, file paths, Linear issue IDs, or intake IDs. |
| `created_by` | string | yes | Actor or system component that created the record, such as `overture-intake` or `codex`. |
| `confidence` | enum | yes | `high`, `medium`, or `low` confidence in the record content. |
| `rationale` | string | yes | One-sentence reason this record was created. |

Additional provenance fields are allowed when useful:

- `quoted_span`: Exact source span when the node or edge is grounded in
  user-provided or cited text.
- `retrieved_at`: Retrieval time for external research sources.
- `method`: Synthesis method, prompt, adapter, or review process used.

Claims and synthesized insights have stricter rules:

- A `Claim` must have at least one `derived_from`, `supports`, or
  `contradicts` edge connecting it to `UserInput`, `Evidence`, or another
  `Claim`.
- Synthesized `Need`, `Constraint`, `Risk`, `Component`, and
  `TicketCandidate` nodes must list every direct input node in
  `provenance.source_node_ids`.
- Low-confidence synthesized nodes must have a related `Risk` or `Constraint`
  when the uncertainty affects implementation.

## Node Types

### Idea

Represents a product, workflow, or implementation idea before it is decomposed.

Required type-specific fields:

| Field | Type | Description |
| --- | --- | --- |
| `problem_area` | string | Domain or workflow the idea concerns. |
| `intake_id` | string | Stable intake record ID when available. |

Typical edges:

- `derived_from` a `UserInput`.
- `relates_to` existing `Idea`, `Need`, `Component`, or `Constraint` nodes.
- `suggests` `TicketCandidate` nodes after synthesis.

### UserInput

Represents raw input from a user, stakeholder, issue, interview, or CLI intake.

Required type-specific fields:

| Field | Type | Description |
| --- | --- | --- |
| `raw_text` | string | Original user-provided text or exact imported issue text. |
| `source_type` | enum | `cli`, `linear`, `interview`, `document`, or `manual`. |
| `submitted_by` | string | User, system, or imported source label. |

Typical edges:

- `suggests` one or more `Idea` nodes.
- `derived_from` a `Source` when imported from an external document.

### Claim

Represents an assertion that can be supported, contradicted, refined, or used to
derive implementation insight.

Required type-specific fields:

| Field | Type | Description |
| --- | --- | --- |
| `statement` | string | Atomic assertion. |
| `claim_kind` | enum | `fact`, `interpretation`, `decision`, `assumption`, or `hypothesis`. |
| `confidence` | enum | `high`, `medium`, or `low`. |

Typical edges:

- `derived_from` `UserInput`, `Evidence`, or `Claim` nodes.
- `supports` or `contradicts` other `Claim`, `Need`, `Risk`, or
  `TicketCandidate` nodes.
- `refines` a broader `Claim`.

### Evidence

Represents a specific observation, research note, test result, quote, or
repository finding.

Required type-specific fields:

| Field | Type | Description |
| --- | --- | --- |
| `evidence_kind` | enum | `quote`, `research_note`, `repo_observation`, `test_result`, or `metric`. |
| `content` | string | Evidence content or concise observation. |
| `source_id` | string | Referenced `Source` node ID. |

Typical edges:

- `derived_from` a `Source`.
- `supports` or `contradicts` `Claim`, `Need`, `Risk`, or `TicketCandidate`
  nodes.

### Source

Represents the stable origin of evidence or imported input.

Required type-specific fields:

| Field | Type | Description |
| --- | --- | --- |
| `source_kind` | enum | `url`, `file`, `linear_issue`, `pull_request`, `command`, or `person`. |
| `reference` | string | Stable URL, path, issue ID, command, or person/source label. |
| `title` | string | Source title or label. |

Typical edges:

- Usually has incoming `derived_from` edges from `UserInput` or `Evidence`.

### Need

Represents a user, operator, developer, or business need derived from inputs and
claims.

Required type-specific fields:

| Field | Type | Description |
| --- | --- | --- |
| `actor` | string | User or system actor with the need. |
| `desired_outcome` | string | Outcome the actor needs. |
| `priority` | enum | `must`, `should`, or `could`. |

Typical edges:

- `derived_from` `UserInput`, `Claim`, or `Evidence`.
- `addresses` from `Component` or `TicketCandidate`.
- `blocks` or `depends_on` other needs when sequencing matters.

### Component

Represents a product surface, module, service, document, command, or data model.

Required type-specific fields:

| Field | Type | Description |
| --- | --- | --- |
| `component_kind` | enum | `module`, `document`, `workflow`, `service`, `cli`, `schema`, or `integration`. |
| `owner_hint` | string | Team, package, path, or system area likely to own the component. |

Typical edges:

- `addresses` `Need` nodes.
- `depends_on` other `Component` or `Constraint` nodes.
- `blocks` `TicketCandidate` nodes when unavailable.

### Constraint

Represents a boundary condition that shapes valid solutions.

Required type-specific fields:

| Field | Type | Description |
| --- | --- | --- |
| `constraint_kind` | enum | `technical`, `product`, `operational`, `legal`, `security`, or `scope`. |
| `requirement` | string | Constraint statement. |
| `severity` | enum | `hard`, `soft`, or `unknown`. |

Typical edges:

- `derived_from` `UserInput`, `Claim`, or `Evidence`.
- `blocks` incompatible `TicketCandidate` or `Component` nodes.
- `refines` `Need` or `Component` nodes.

### Risk

Represents uncertainty or a failure mode that could affect value, schedule, or
implementation correctness.

Required type-specific fields:

| Field | Type | Description |
| --- | --- | --- |
| `risk_kind` | enum | `product`, `technical`, `evidence`, `delivery`, or `adoption`. |
| `impact` | enum | `high`, `medium`, or `low`. |
| `mitigation` | string | Planned mitigation or validation method. |

Typical edges:

- `derived_from` `Claim`, `Evidence`, or `Constraint`.
- `blocks` `TicketCandidate`, `Component`, or `Need` nodes.
- `contradicts` overconfident `Claim` nodes when evidence is weak.

### TicketCandidate

Represents a candidate Linear issue before or during ticket generation.

Required type-specific fields:

| Field | Type | Description |
| --- | --- | --- |
| `title` | string | Candidate ticket title. |
| `scope` | string | Implementation boundary for the candidate. |
| `validation_plan` | string array | Executable validation steps or explicit fallback checks. |
| `readiness` | enum | `draft`, `ready`, `blocked`, or `discarded`. |

Typical edges:

- `derived_from` `Idea`, `Need`, `Claim`, `Evidence`, `Risk`, or
  `Constraint`.
- `addresses` `Need`, `Risk`, or `Constraint` nodes.
- `depends_on` prerequisite `TicketCandidate` or `Component` nodes.

## Edge Types

| Type | Meaning | Common source -> target |
| --- | --- | --- |
| `supports` | Source node increases confidence in target node. | `Evidence` -> `Claim`, `Claim` -> `Need`, `Evidence` -> `TicketCandidate` |
| `contradicts` | Source node conflicts with or weakens target node. | `Evidence` -> `Claim`, `Claim` -> `Claim`, `Risk` -> `TicketCandidate` |
| `relates_to` | Weak non-hierarchical association without stronger semantics yet. | any -> any |
| `refines` | Source narrows, clarifies, or decomposes target. | `Claim` -> `Claim`, `Constraint` -> `Need`, `TicketCandidate` -> `Idea` |
| `depends_on` | Source cannot be completed or interpreted without target. | `TicketCandidate` -> `Component`, `Component` -> `Constraint` |
| `derived_from` | Source was created from target content or evidence. | synthesized node -> input/evidence/source node |
| `addresses` | Source satisfies, mitigates, or implements target. | `Component` -> `Need`, `TicketCandidate` -> `Risk` |
| `blocks` | Source prevents or materially delays target. | `Risk` -> `TicketCandidate`, `Constraint` -> `Component` |
| `suggests` | Source implies a possible next idea, component, risk, or ticket. | `UserInput` -> `Idea`, `Idea` -> `TicketCandidate` |

## Isolated Idea Linking

New user ideas may enter the graph before research or synthesis has enough
context to connect them. The MVP lifecycle is:

1. Create a `UserInput` node with raw text and empty `source_node_ids`.
2. Create an `Idea` node with `status: proposed`, a `derived_from` edge to the
   `UserInput`, and no required edges to existing graph knowledge.
3. During research or graph lookup, add low-confidence `relates_to` edges to
   potentially matching `Idea`, `Need`, `Component`, or `Constraint` nodes.
4. Promote links to stronger edge types such as `supports`, `refines`,
   `depends_on`, or `suggests` when evidence or synthesis justifies them.
5. Keep the original `UserInput` and `derived_from` edge even after the idea is
   connected, so the intake provenance remains stable.

This allows sparse islands to exist without losing their later topology.

## Example Graph: Overture MVP Idea

Sample intake idea:

> Build Overture so a rough product idea can become research-backed graph
> knowledge and then Symphony-ready Linear tickets without losing provenance.

Example graph:

```json
{
  "schema_version": "kg-minimal-v1",
  "nodes": [
    {
      "id": "userinput_overture_mvp_intake",
      "type": "UserInput",
      "label": "Overture MVP intake",
      "summary": "User wants rough product ideas converted into research-backed graph knowledge and Symphony-ready Linear tickets.",
      "status": "active",
      "created_at": "2026-05-05T00:00:00-06:00",
      "updated_at": "2026-05-05T00:00:00-06:00",
      "raw_text": "Build Overture so a rough product idea can become research-backed graph knowledge and then Symphony-ready Linear tickets without losing provenance.",
      "source_type": "linear",
      "submitted_by": "ERI-8",
      "provenance": {
        "origin": "user_input",
        "source_node_ids": [],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "Initial user-authored ticket text defines the MVP graph need."
      }
    },
    {
      "id": "idea_overture_mvp_knowledge_graph",
      "type": "Idea",
      "label": "Overture MVP knowledge graph",
      "summary": "Represent intake, research, synthesis, and ticket candidates as connected graph knowledge.",
      "status": "proposed",
      "created_at": "2026-05-05T00:01:00-06:00",
      "updated_at": "2026-05-05T00:01:00-06:00",
      "problem_area": "idea-to-ticket synthesis",
      "intake_id": "ERI-8",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["userinput_overture_mvp_intake"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The intake describes the core graph-backed Overture workflow."
      }
    },
    {
      "id": "need_preserve_topology_and_provenance",
      "type": "Need",
      "label": "Preserve topology and provenance",
      "summary": "Autonomous implementation agents need graph outputs that show why insights exist and how they relate.",
      "status": "active",
      "created_at": "2026-05-05T00:02:00-06:00",
      "updated_at": "2026-05-05T00:02:00-06:00",
      "actor": "Symphony/Codex implementer",
      "desired_outcome": "Trace generated tickets back to ideas, evidence, claims, risks, and constraints.",
      "priority": "must",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["userinput_overture_mvp_intake", "idea_overture_mvp_knowledge_graph"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The issue states that topology and provenance matter more than text summarization."
      }
    },
    {
      "id": "claim_graph_must_be_non_hierarchical",
      "type": "Claim",
      "label": "Graph must be non-hierarchical",
      "summary": "The MVP graph needs typed relationships across concepts rather than a parent-child outline.",
      "status": "active",
      "created_at": "2026-05-05T00:03:00-06:00",
      "updated_at": "2026-05-05T00:03:00-06:00",
      "statement": "Typed graph edges are required to preserve non-hierarchical relationships between Overture concepts.",
      "claim_kind": "interpretation",
      "confidence": "high",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["userinput_overture_mvp_intake"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The issue explicitly asks for non-hierarchical relationships between core node types."
      }
    },
    {
      "id": "source_repo_graph_module",
      "type": "Source",
      "label": "Current graph module",
      "summary": "Existing graph module contains research ingestion records but not the full MVP schema.",
      "status": "active",
      "created_at": "2026-05-05T00:04:00-06:00",
      "updated_at": "2026-05-05T00:04:00-06:00",
      "source_kind": "file",
      "reference": "overture/graph.py",
      "title": "Overture graph ingestion records",
      "provenance": {
        "origin": "system",
        "source_node_ids": [],
        "source_refs": ["overture/graph.py"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "Repository inspection identified current graph record coverage."
      }
    },
    {
      "id": "evidence_graph_module_scope",
      "type": "Evidence",
      "label": "Graph module scope observation",
      "summary": "The current graph module defines Source, ResearchItem, Claim, CITES, and HAS_CLAIM records.",
      "status": "active",
      "created_at": "2026-05-05T00:05:00-06:00",
      "updated_at": "2026-05-05T00:05:00-06:00",
      "evidence_kind": "repo_observation",
      "content": "overture/graph.py currently models research ingestion records and does not document Need, Component, Constraint, Risk, or TicketCandidate nodes.",
      "source_id": "source_repo_graph_module",
      "provenance": {
        "origin": "research",
        "source_node_ids": ["source_repo_graph_module"],
        "source_refs": ["overture/graph.py"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "Direct repository inspection provides implementation context for the schema design."
      }
    },
    {
      "id": "component_minimal_kg_schema_doc",
      "type": "Component",
      "label": "Minimal KG schema document",
      "summary": "A documentation artifact defining Overture MVP node types, edge types, and provenance rules.",
      "status": "active",
      "created_at": "2026-05-05T00:06:00-06:00",
      "updated_at": "2026-05-05T00:06:00-06:00",
      "component_kind": "document",
      "owner_hint": "docs/minimal-knowledge-graph-schema.md",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["idea_overture_mvp_knowledge_graph", "need_preserve_topology_and_provenance"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "A documented schema is the minimal component needed to satisfy the issue."
      }
    },
    {
      "id": "constraint_claims_need_provenance",
      "type": "Constraint",
      "label": "Claims require provenance",
      "summary": "Every claim and synthesized insight must trace to source graph nodes or stable references.",
      "status": "active",
      "created_at": "2026-05-05T00:07:00-06:00",
      "updated_at": "2026-05-05T00:07:00-06:00",
      "constraint_kind": "technical",
      "requirement": "Claims and synthesized insights must include provenance and supporting graph edges.",
      "severity": "hard",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["userinput_overture_mvp_intake", "claim_graph_must_be_non_hierarchical"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The issue requires provenance for every claim and synthesized insight."
      }
    },
    {
      "id": "risk_flat_summary_loses_ticket_context",
      "type": "Risk",
      "label": "Flat summary loses context",
      "summary": "Ticket generation may lose why a candidate exists if graph topology is not preserved.",
      "status": "active",
      "created_at": "2026-05-05T00:08:00-06:00",
      "updated_at": "2026-05-05T00:08:00-06:00",
      "risk_kind": "product",
      "impact": "medium",
      "mitigation": "Require Graph provenance and Sources / evidence sections in generated tickets.",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["need_preserve_topology_and_provenance", "constraint_claims_need_provenance"],
        "source_refs": ["Linear:ERI-8", "docs/symphony-ready-ticket-schema.md"],
        "created_by": "codex",
        "confidence": "medium",
        "rationale": "Without preserved topology, downstream tickets may be hard to audit."
      }
    },
    {
      "id": "ticketcandidate_document_minimal_kg_schema",
      "type": "TicketCandidate",
      "label": "Document minimal KG schema",
      "summary": "Add documentation for the Overture MVP graph schema and validation walkthrough.",
      "status": "active",
      "created_at": "2026-05-05T00:09:00-06:00",
      "updated_at": "2026-05-05T00:09:00-06:00",
      "title": "Document minimal knowledge graph schema",
      "scope": "Define node fields, edge fields, provenance rules, isolated idea linking, and an Overture MVP example graph.",
      "validation_plan": [
        "Review the sample intake walkthrough and confirm each produced node and edge has required fields.",
        "Run repository tests to confirm no existing behavior regressed."
      ],
      "readiness": "ready",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": [
          "idea_overture_mvp_knowledge_graph",
          "need_preserve_topology_and_provenance",
          "constraint_claims_need_provenance",
          "risk_flat_summary_loses_ticket_context"
        ],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The candidate directly satisfies the documented schema acceptance criteria."
      }
    }
  ],
  "edges": [
    {
      "id": "idea_overture_mvp_knowledge_graph__derived_from__userinput_overture_mvp_intake",
      "type": "derived_from",
      "from": "idea_overture_mvp_knowledge_graph",
      "to": "userinput_overture_mvp_intake",
      "summary": "The idea was synthesized from the raw Overture MVP intake.",
      "confidence": "high",
      "created_at": "2026-05-05T00:01:30-06:00",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["idea_overture_mvp_knowledge_graph", "userinput_overture_mvp_intake"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The idea is a normalized form of the intake text."
      }
    },
    {
      "id": "need_preserve_topology_and_provenance__derived_from__idea_overture_mvp_knowledge_graph",
      "type": "derived_from",
      "from": "need_preserve_topology_and_provenance",
      "to": "idea_overture_mvp_knowledge_graph",
      "summary": "The need is derived from the Overture MVP graph idea.",
      "confidence": "high",
      "created_at": "2026-05-05T00:02:30-06:00",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["need_preserve_topology_and_provenance", "idea_overture_mvp_knowledge_graph"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The intake explicitly names topology and provenance as goals."
      }
    },
    {
      "id": "claim_graph_must_be_non_hierarchical__derived_from__userinput_overture_mvp_intake",
      "type": "derived_from",
      "from": "claim_graph_must_be_non_hierarchical",
      "to": "userinput_overture_mvp_intake",
      "summary": "The claim interprets the user's non-hierarchical relationship requirement.",
      "confidence": "high",
      "created_at": "2026-05-05T00:03:30-06:00",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["claim_graph_must_be_non_hierarchical", "userinput_overture_mvp_intake"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The issue lists non-hierarchical relationships as the graph purpose."
      }
    },
    {
      "id": "evidence_graph_module_scope__derived_from__source_repo_graph_module",
      "type": "derived_from",
      "from": "evidence_graph_module_scope",
      "to": "source_repo_graph_module",
      "summary": "The evidence is a direct observation from the current graph module.",
      "confidence": "high",
      "created_at": "2026-05-05T00:05:30-06:00",
      "provenance": {
        "origin": "research",
        "source_node_ids": ["evidence_graph_module_scope", "source_repo_graph_module"],
        "source_refs": ["overture/graph.py"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The file content grounds the evidence node."
      }
    },
    {
      "id": "evidence_graph_module_scope__supports__component_minimal_kg_schema_doc",
      "type": "supports",
      "from": "evidence_graph_module_scope",
      "to": "component_minimal_kg_schema_doc",
      "summary": "The current module scope supports adding a separate schema document for MVP design.",
      "confidence": "medium",
      "created_at": "2026-05-05T00:06:30-06:00",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["evidence_graph_module_scope", "component_minimal_kg_schema_doc"],
        "source_refs": ["overture/graph.py", "Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "medium",
        "rationale": "Documentation is the lowest-risk way to define the schema before implementation."
      }
    },
    {
      "id": "component_minimal_kg_schema_doc__addresses__need_preserve_topology_and_provenance",
      "type": "addresses",
      "from": "component_minimal_kg_schema_doc",
      "to": "need_preserve_topology_and_provenance",
      "summary": "The schema document defines how topology and provenance are represented.",
      "confidence": "high",
      "created_at": "2026-05-05T00:07:30-06:00",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["component_minimal_kg_schema_doc", "need_preserve_topology_and_provenance"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The component directly satisfies the need."
      }
    },
    {
      "id": "constraint_claims_need_provenance__refines__need_preserve_topology_and_provenance",
      "type": "refines",
      "from": "constraint_claims_need_provenance",
      "to": "need_preserve_topology_and_provenance",
      "summary": "The constraint makes provenance mandatory for claims and synthesized insights.",
      "confidence": "high",
      "created_at": "2026-05-05T00:08:30-06:00",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["constraint_claims_need_provenance", "need_preserve_topology_and_provenance"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "Mandatory provenance is the enforceable form of the need."
      }
    },
    {
      "id": "risk_flat_summary_loses_ticket_context__blocks__ticketcandidate_document_minimal_kg_schema",
      "type": "blocks",
      "from": "risk_flat_summary_loses_ticket_context",
      "to": "ticketcandidate_document_minimal_kg_schema",
      "summary": "The ticket candidate must address flat-summary risk before being considered complete.",
      "confidence": "medium",
      "created_at": "2026-05-05T00:09:30-06:00",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["risk_flat_summary_loses_ticket_context", "ticketcandidate_document_minimal_kg_schema"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "medium",
        "rationale": "The risk identifies why the schema needs explicit topology and provenance."
      }
    },
    {
      "id": "ticketcandidate_document_minimal_kg_schema__addresses__constraint_claims_need_provenance",
      "type": "addresses",
      "from": "ticketcandidate_document_minimal_kg_schema",
      "to": "constraint_claims_need_provenance",
      "summary": "The candidate defines required provenance fields and claim linkage rules.",
      "confidence": "high",
      "created_at": "2026-05-05T00:10:30-06:00",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["ticketcandidate_document_minimal_kg_schema", "constraint_claims_need_provenance"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The ticket candidate includes schema rules for provenance."
      }
    },
    {
      "id": "idea_overture_mvp_knowledge_graph__suggests__ticketcandidate_document_minimal_kg_schema",
      "type": "suggests",
      "from": "idea_overture_mvp_knowledge_graph",
      "to": "ticketcandidate_document_minimal_kg_schema",
      "summary": "The MVP graph idea suggests documenting the schema as the first deliverable.",
      "confidence": "high",
      "created_at": "2026-05-05T00:11:30-06:00",
      "provenance": {
        "origin": "synthesis",
        "source_node_ids": ["idea_overture_mvp_knowledge_graph", "ticketcandidate_document_minimal_kg_schema"],
        "source_refs": ["Linear:ERI-8"],
        "created_by": "codex",
        "confidence": "high",
        "rationale": "The issue acceptance criteria require a documented schema."
      }
    }
  ]
}
```

## Validation Walkthrough

Input:

```text
Build Overture so a rough product idea can become research-backed graph
knowledge and then Symphony-ready Linear tickets without losing provenance.
```

Mapping:

1. Store the raw text as `userinput_overture_mvp_intake`.
   - Required fields are present: `id`, `type`, `label`, `summary`, `status`,
     timestamps, `raw_text`, `source_type`, `submitted_by`, and `provenance`.
   - `provenance.source_node_ids` is empty because this is an initial input.
2. Synthesize `idea_overture_mvp_knowledge_graph` from the input.
   - Add `derived_from` edge from the `Idea` to the `UserInput`.
   - The `Idea` provenance lists the `UserInput` node and `Linear:ERI-8`.
3. Extract the core need as `need_preserve_topology_and_provenance`.
   - Add `derived_from` edge from the `Need` to the `Idea`.
   - The node records actor, desired outcome, priority, and provenance.
4. Convert the non-hierarchical graph requirement into
   `claim_graph_must_be_non_hierarchical`.
   - Add `derived_from` edge from the `Claim` to the `UserInput`.
   - The claim has a statement, kind, confidence, and required provenance.
5. Attach repository evidence as `source_repo_graph_module` and
   `evidence_graph_module_scope`.
   - Add `derived_from` edge from the `Evidence` to the `Source`.
   - Add `supports` edge from the `Evidence` to the schema document component.
6. Create synthesized nodes for implementation shape:
   `component_minimal_kg_schema_doc`, `constraint_claims_need_provenance`,
   `risk_flat_summary_loses_ticket_context`, and
   `ticketcandidate_document_minimal_kg_schema`.
   - Each synthesized node lists its direct input nodes in provenance.
   - The risk has a mitigation.
   - The ticket candidate has scope, readiness, and validation plan.
7. Connect the topology with typed edges:
   - `addresses` links show how the schema document and ticket candidate satisfy
     needs and constraints.
   - `refines` shows the provenance constraint narrowing the broader topology
     need.
   - `blocks` captures the flat-summary risk that the ticket must mitigate.
   - `suggests` links the original idea to the candidate implementation ticket.

The walkthrough satisfies the ticket validation requirement because the sample
intake is transformed into explicit nodes and edges, and each claim or
synthesized insight is traceable to source nodes and stable references.
