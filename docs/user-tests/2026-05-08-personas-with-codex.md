# Re-test con personas — 2026-05-08 (Codex real)

Re-corrida de las 3 pruebas de [2026-05-07-personas.md](2026-05-07-personas.md)
ahora que el cliente Codex CLI funciona. Validamos:

1. PR #74 (mergeado): fallback automático a research determinístico cuando
   Codex no está disponible.
2. PR #75 (en revisión): drop del flag `--non-interactive` que rechazan las
   versiones recientes del Codex CLI.

## Setup

- Cada persona arrancó con su servidor en puertos `8765/8766/8767`,
  store-dir limpio, y `OVERTURE_CODEX_EXECUTABLE=/Applications/Codex.app/
  Contents/Resources/codex` configurado en el launcher (transparente para
  la persona — ninguno tocó env vars).
- Codex CLI version: `codex-cli 0.129.0-alpha.15`.
- Tiempo aproximado por llamada de Codex: 20-90 segundos.

## Resumen de resultados

| Persona | Antes (sin Codex) | Después (con Codex real) |
|---|---|---|
| Carla | Bloqueada por error de Codex; recuperó tras reiniciar con env var | Llegó a research approval con **5 sources reales relevantes** |
| Tomás | Abandonó en research approval (no podía resolver el error) | Llegó a research approval con **5 sources reales relevantes** |
| Rocío | Abandonó, derivó al CTO | Llegó a research approval con **5 sources reales relevantes** |

**Resultado neto**: el muro de Codex desapareció para los 3 perfiles. Las
fricciones documentadas previamente (placeholder en `/ticket`, peer-onboarding
viewer-only, copy designer-céntrico) **siguen existiendo** y no se abordaron en
estos PRs.

**Hallazgo nuevo**: la página `POST /research/approval` del wizard devuelve
**HTTP 400 Bad Request** consistentemente en este test. La sesión pierde los
candidatos entre el render y el submit, así que los personas no pueden
guardar sus aprobaciones desde la UI. El CLI (`overture research <id>`) sí
funciona end-to-end. Detalles en la sección "Hallazgo nuevo" abajo.

---

## Test 1 — Carla, post-fix

**Idea**: misma del round anterior — *Add session metadata to the peer
onboarding template…*

### Lo que cambió

Antes Carla tenía que reiniciar el servidor con `OVERTURE_LLM_CLIENT=fake`.
Ahora abre `localhost:8765/intake`, login, escribe su idea, click "Start
research approval", **espera ~20s**, y ve 5 fuentes reales y relevantes
sin tocar la terminal.

### Sources que Codex sugirió

(Capturadas por la corrida CLI equivalente con la misma intake.)

1. **Meeting Minutes Template** — `atlassian.com/software/confluence/templates/meeting-notes` — *"timestamps, participant context, decisions, and action items make a session record reusable"*.
2. **Add Measurements and Annotate Designs** — `help.figma.com/.../Add-measurements-and-annotate-designs` — *"annotations and measurements to add contextual handoff details"*.
3. **Share User Insights Async with Loom to Speed Up Decisions** — Loom — *"asynchronous screen recordings to preserve context"*.
4. **Team Playbook poster** — `atlassian.com/team-playbook/plays/team-poster` — pattern para distillar contexto de equipo.
5. **UX Research Field Guide — Interviews** — `userinterviews.com/...` — research field-guide para interviewing.

Cinco fuentes reales, relevantes a "session metadata + designer #1 → #2
handoff". Cero `example.test/...` placeholders.

### Reacción de Carla (in-character)

> "Ahora sí. Las fuentes son inspectables y todas tienen que ver con mi
> idea. La de Atlassian habla literal de los campos que mencioné
> (timestamps, decisiones, action items). La de Figma me sirve si quiero
> que el handoff incluya anotaciones in-design. Y Loom para los screen
> recordings. […] Cuando le doy 'Save approved sources' me sale un error
> raro y me devuelve a la página vacía — ¿se cayó? Le doy refresh y
> arranca a buscar fuentes de nuevo. Esto del save está roto."

### Fricciones todavía presentes (vs. pre-fix)

| Finding (carryover) | Estado | Notas |
|---|---|---|
| #4 Pre-aprobación de sources | Sigue | "Approve" pre-marcado en los 5 |
| #6 `/research/complete` sin botón siguiente | Pendiente verificar | No alcancé a ver porque save falla |
| #7 Synthesis brief templated | Pendiente verificar | Idem |
| #8 Candidate ticket title cortado | Pendiente verificar | Idem |
| #9 `/ticket` placeholder | Sigue (no se tocó) | — |
| #10 Peer-onboarding viewer-only | Sigue (no se tocó) | — |

---

## Test 2 — Tomás, post-fix

**Idea**: *Show a sidebar of recent intakes on the wizard so I can reuse
phrasing from past ideas instead of starting from a blank page every time.*

### Lo que cambió

Antes Tomás se atascaba con el error "Codex CLI executable not found", no
podía resolverlo, y abandonaba. Ahora ve la página de research approval
poblada con 5 fuentes inspectables.

### Sources que Codex sugirió

1. **Confluence navigation** — `support.atlassian.com/confluence-cloud/docs/improved-confluence-navigation/` — patrones de sidebar.
2. **Recent Items - Win32 apps** — `learn.microsoft.com/.../windowsribbon-controls-recentitems` — MRU pattern, ordering, list limits, pinning.
3. **View recent items** — Adobe Workfront — bounded recent-items menu.
4. **Issue templates** — patrón de plantillas reutilizables.
5. **10 Usability Heuristics for User Interface Design** — Nielsen heuristics (probablemente NN Group).

Estas fuentes cubren exactamente el espacio de "sidebar + recent items +
reuse" que Tomás describió. Para él (semi-técnico), inspectarlas y entender
si se aplican es hacer su trabajo de diseñador, no debugging.

### Reacción de Tomás (in-character)

> "Espera, esto sí investigó. Cinco fuentes de productos reales que tienen
> 'recent items' en su UI: Microsoft, Adobe, Atlassian. Y Nielsen
> heuristics — eso lo conozco del bootcamp. Voy a abrir un par antes de
> aprobar […] OK, le doy approve a 3, los otros 2 no me convencen del
> todo. Save. Hmm, error. Refresh. Salen otras 5 fuentes diferentes…
> ¿la herramienta no recuerda lo que yo dije?"

### Comparación con pre-fix

- **Antes**: muro absoluto. Tomás llamó a Carla por Slack para preguntar
  cómo arrancar el server con env vars.
- **Ahora**: completamente desbloqueado en research approval. Solo
  encuentra fricción en el save.

---

## Test 3 — Rocío, post-fix

**Idea**: *We need to send a weekly digest email to onboarded users
summarizing what they did in the product that week. Right now they sign up,
use the product once, and never come back. The digest should highlight
2-3 specific things they did and gently remind them of the next step in
onboarding.*

### Lo que cambió

Antes Rocío veía "Codex CLI executable not found on PATH. Install the Codex
CLI, set OVERTURE_CODEX_EXECUTABLE…" — palabras alienígenas para una
founder no técnica. Cerraba el tab y derivaba a su CTO.

Ahora ve 5 fuentes especialmente bien escogidas para su problema.

### Sources que Codex sugirió

1. **How Weekly Digest Emails Work in Heartbeat** — `help.heartbeat.chat/.../How-Weekly-Digest-Emails…` — match directo en "weekly digest".
2. **Common questions about weekly Grammarly Insights reports** — `support.grammarly.com/...` — patrón weekly insights digest, exactamente el formato que Rocío imagina.
3. **Get started with emails — Userpilot Knowledge Base** — `docs.userpilot.com/in-app-engagement/emails/...` — onboarding email setup paso a paso.
4. **6 lifecycle emails that'll elevate your engagement game** — `customer.io/learn/lifecycle-marketing/emails` — lifecycle marketing 101.
5. **Retain customers that are slipping away** — `intercom.com/help/.../retain-customers-that-are-slipping` — match perfecto al pain "they sign up, use once, never come back".

Cinco fuentes en URLs reales que Rocío reconoce (Intercom, Customer.io,
Userpilot — herramientas de su mundo). Cero referencia a Codex,
environment variables, executables.

### Reacción de Rocío (in-character)

> "Oh. Esto sí me sirve. Reconozco a Intercom, Customer.io, Userpilot —
> son herramientas que considero o uso. Y la de Heartbeat habla *exacto*
> de lo que yo pedí: 'weekly digest emails'. Y la de Intercom habla del
> problema real, retener usuarios que se están escapando. Le doy approve
> a 4 y… error. ¿Se rompió? Le doy refresh. […] Misma vibe de antes:
> esto está sin terminar."

### Comparación con pre-fix

- **Antes**: lenguaje técnico ininteligible, abandonó.
- **Ahora**: research aprobable, hasta el primer save donde se rompe la
  sesión.

---

## Hallazgo nuevo — wizard pierde sesión en POST /research/approval

Detectado en los 3 tests, consistente. Síntomas:

1. POST /intake guarda el intake, redirige a /research/approval. ✓
2. GET /research/approval llama a Codex, devuelve la página con sources. ✓
3. Usuario clickea "Save approved sources" → POST /research/approval
4. Server responde **HTTP 400 Bad Request** y rerendea con error
   "No suggested sources are available for this intake."
5. Si el usuario refresca, la sesión re-entra a (2) — Codex se vuelve a
   llamar (otros 20-90s) y la página rerenderiza con potencialmente
   distintas 5 sources.

Evidencia capturada en `preview_network`:

```
GET /auth/login?next=/intake → 200 OK
POST /auth/magic-link → 200 OK
GET /intake → 200 OK
GET /research/approval → 200 OK   (Codex llamado, render OK)
POST /research/approval → 400 Bad Request   ← bug
GET /research/approval → 200 OK   (Codex re-llamado, render OK)
```

**Hipótesis**: la sesión pierde `intake_id` o los candidatos en cookie
storage entre el GET y el POST a `/research/approval`. El CLI
(`overture research <id>`) no usa esta capa de sesión y funciona end-to-end.

**Impacto**: independiente de Codex, este bug bloquea a los 3 personas
desde el wizard. Hay que reproducirlo con un browser real (no Claude
Preview) para descartar que sea un artefacto del runner.

Recomendación: investigar si:
- El cookie de sesión es HttpOnly + SameSite y el browser de Preview lo
  filtra en POSTs cross-form.
- El `_store_session_candidates` no persiste a disco (sólo memoria) y se
  pierde si el server hace algo entre requests.
- El CSRF/anti-replay invalida la sesión post-render.

## Validación del fix de Codex

A pesar del bug nuevo del wizard, **la fix sí cumple su objetivo**:

- Los 3 personas ven research approval con sources reales.
- El CLI completo funciona: `python -m overture research <id>` produce un
  JSON válido con 5 items y 0 errores para los 3 intakes.
- Sin necesidad de tocar `OVERTURE_LLM_CLIENT=fake`.

## Recomendaciones priorizadas

### P0 (nuevo — investigar y reportar bug del wizard)

- **Reproducir HTTP 400 en POST /research/approval con un browser real**.
  Si confirma, abrir issue/ticket separado.
- Mientras tanto, los personas reales que usen el wizard hoy se atorarán
  ahí.

### P1-P2 (carryover de la primera ronda)

Sin cambio. La lista en
[2026-05-07-personas.md → Recomendaciones priorizadas](2026-05-07-personas.md)
sigue vigente: `/ticket` placeholder, fallback toggle UI, pre-aprobación
de sources, copy designer-céntrico, peer onboarding edit flow.

### Investigación adicional pendiente

- **Ejecutar el flow CLI completo end-to-end** (intake → research →
  synthesis → ticket → export) con una idea de cada persona, capturando
  outputs reales con Codex. Esto desempata si las fricciones #7 (brief
  templated) y #8 (title truncado) eran efectos del modo fake o si
  persisten con Codex real.

## Apéndice — comandos de reproducción

```sh
# Setup común
export OVERTURE_CODEX_EXECUTABLE=/Applications/Codex.app/Contents/Resources/codex

# Por persona (ejemplo Carla)
mkdir -p /tmp/overture-test-carla
python -m overture ui --port 8765 --store-dir /tmp/overture-test-carla
# → navegar a localhost:8765/intake, login, intake, intentar research approval

# Validación CLI equivalente (no rompe en el save, sirve como ground truth)
python -m overture intake "<idea>" --store-dir /tmp/overture-test-carla
python -m overture research <intake-id> --store-dir /tmp/overture-test-carla
# Aprobar sources interactivamente; produce /tmp/overture-test-carla/research/<id>.json
```
