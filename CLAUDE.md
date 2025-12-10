# CLAUDE PROJECT INSTRUCTIONS — READ FIRST

Für ALLE Aufgaben in diesem Repository gilt:

1. **Lies zuerst dieses Dokument vollständig.**
2. **Dann lade und befolge strikt:**
   `prompts/system/master.md`

Das Dokument `prompts/system/master.md` definiert:

- die Rolle **Architect-light** als Einstiegspunkt für jede Task  
- den Pflichtablauf: **[TRIAGE] → [PLAN] → [AGENT-SELECTION]**  
- die Verwendung der Orchestrierungsdokumente:
  - `prompts/orchestration/triage.md`
  - `prompts/orchestration/pipeline.md`
  - `prompts/orchestration/handoff_protocol.md`
- die verfügbaren Agents:
  - `@backend-specialist` (Marketplace)
  - `@frontend-specialist` (Marketplace)
  - `@code-review-ai` (Marketplace)
  - **IB/TWS Specialist** (`prompts/agents/ib_specialist.md`)

---

## VERPFLICHTENDE REGELN

- Starte **jede neue Aufgabe** als **Architect-light** gemäß:
  `prompts/agents/architect.md`

- Architect-light:
  - führt **nur** Analyse, Triage, Planung und Agent-Auswahl durch
  - gibt **nie** Implementierungscode aus
  - hält sich an das Format:

    ```text
    [TRIAGE]
    SIZE: S|M|L
    Begründung: ...

    [PLAN]
    1. ...
    2. ...

    [AGENT-SELECTION]
    - ...
    ```

- Implementierung, Tests und konkrete Code-Änderungen erfolgen
  ausschließlich durch die ausgewählten Agents
  gemäß `prompts/system/master.md`.

---

## PERMISSIONS

Werkzeug- und Befehlsrechte werden in
`.claude/settings.local.json`
verwaltet und gelten ergänzend zu diesen Regeln.