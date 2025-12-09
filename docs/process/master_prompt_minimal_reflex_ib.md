KONTEXT (fix, bleibt immer gleich):
- Projektgröße: klein bis mittel, Solo-Dev, Fokus auf hohe Qualität bei hoher Geschwindigkeit.
- Tech-Stack: Reflex.dev (Frontend + Backend in Python).
- Trennung nach Verantwortlichkeit, nicht nach Sprache:
  • Frontend: UI/UX, Komponenten, Layout, Routing, responsive Darstellung, UI-nahe States.
  • Backend: Business-States, Datenzugriff, Auth-Checks, Services, Integrationen.
- Broker: Interactive Brokers TWS API.
  • Zentrale Broker-Datei: broker.py
  • IB/TWS-Subagent existiert.
  • Offline-Wissen: docs/ib/ib_bible.md
- Kein großer Architekturumbau ohne explizite Anforderung.
- Ziel: Micro-Slices, kurze Iterationen, tests-first genug für Stabilität.

=====================================================================
ZIEL (einziger Block, den ich pro Aufgabe ersetze):
<1–6 Sätze: Feature/Bug/Redesign/Verbesserung>

Optionale Zusatzinfos:
- Observed symptom/log:
  <kurz>
- Erwartetes Verhalten:
  <kurz>
- Relevante Dateien falls bekannt:
  <Liste>

=====================================================================
AGENT-STACK (verfügbar):
- Architect-light (Planung)
- Backend Specialist (Reflex-Business)
- Frontend Specialist (Reflex-UI)
- IB/TWS Specialist (nur broker.py + tests/ib + docs/ib)
- code-review-ai (Review-Gate)
- QA/Test Gate (Test-Gate)

Hinweis:
- Security/Perf/Deploy nur bei explizitem Zielbedarf (nicht Standard im kleinen Projekt).

=====================================================================
AGENT-REGELN (Pflicht, immer):
- Jeder Schritt MUSS mit einem Header starten:
  [AGENT: <Name>]
  [MODE: Plan | Implement | Review]
  [SCOPE: <allowed files>]
- Jeder Agent bestätigt zu Beginn in 1 Satz:
  "Ich bin <Agent> und arbeite nur in <Scope>."
- Am Ende jedes Schritts:
  "Hand-off complete. Next agent: <Name>."
- Kein Agent arbeitet außerhalb seines SCOPE.
- Neues Wissen/Entscheidungen werden dauerhaft in Artefakte ausgelagert:
  • Tests
  • falls nötig kurze Projekt-Doku
  • bei IB: docs/ib/ib_bible.md
  Kein “Wissen nur im Chat”.

=====================================================================
AGENT-SELECTION-REGELN (Pflicht, immer):
Schritt 1 MUSS anhand des Ziels die minimal nötigen Agenten auswählen
und alle anderen Schritte explizit “SKIP” markieren.

Auswahl-Heuristik:
- Wenn Ziel Broker/TWS/ib_insync/Orders/Market Rules/MinTick/Trading Hours erwähnt:
  → IB/TWS Specialist ist Pflicht.
  → Backend/Frontend nur wenn Reflex-States/UI dafür angepasst werden müssen.
- Wenn Ziel primär UI/UX/Layout/Komponenten/Responsive betrifft:
  → Frontend Specialist ist Pflicht.
- Wenn Ziel primär Business-States/DB/Auth/API betrifft (ohne Broker):
  → Backend Specialist ist Pflicht.
- Security nur wenn Auth/Permissions/PII explizit betroffen sind.
- Performance/Speed nur wenn explizit gefordert.
- code-review-ai + QA/Test Gate sind Standard-Gates,
  dürfen bei sehr kleinen IB-only Fixes als “light mode” ausgeführt werden.

=====================================================================
SICHTBARKEITS-REGEL (Pflicht):
Schritt 1 MUSS diese Box ausgeben:

[AGENT-SELECTION]
Selected:
- <Agent> — warum nötig (1 Satz)
Skipped:
- <Agent> — warum nicht nötig (1 Satz)
Order of execution:
1) <Agent>
2) <Agent>
Scopes summary:
- <Agent>: <allowed files>
[/AGENT-SELECTION]

=====================================================================
GIT-REGELN (Pflicht):
- Nach Plan-Freigabe wird ein Feature-Branch angelegt, bevor implementiert wird.
- Branch-Schema:
  • feat/<kurz>
  • fix/<kurz>
  • refactor/<kurz>
  • perf/<kurz>
- Wenn IB betroffen: Branch ist verpflichtend.
- Conventional Commits:
  feat|fix|refactor|perf|test|docs|chore(scope): ...
- Scope-Beispiele:
  ib, reflex, auth, ui, tests
- Kein “WIP”-Commit.
- IB-Änderungen (falls vorhanden) in eigenem Commit-Block.

=====================================================================
PIPELINE (dynamisch, wird von Schritt 1 reduziert):

1) PLAN-GATE (Architect-light, read-only):
   - KEIN Code.
   - Optional: full-stack-orchestration darf NUR zur Plan-Erstellung genutzt werden.
   - Output MUSS enthalten:
     a) Micro-Slices
     b) Acceptance Criteria
     c) Risiken/Edge Cases
     d) vermutete konkrete Dateien/Module
     e) IB betroffen: ja/nein
     f) [AGENT-SELECTION]-Box
     g) Reduzierte Pipeline mit SKIPs
     h) Branch-Vorschlag + 2–4 Commit-Titel

2) GIT-GATE:
   - Branch anlegen gemäß Vorschlag aus Schritt 1.

3) IMPLEMENTIERUNG (nur ausgewählte Agenten):
   3a) Backend Specialist (Reflex-Business)
       - Implementiere Business-States/Services/DB/Auth passend zum Plan.
       - Keine UI-Änderungen.
   3b) Frontend Specialist (Reflex-UI)
       - Implementiere UI/UX/Komponenten/Responsive/Flows passend zum Plan.
       - Keine Business-/Auth-Regellogik ändern.
   3c) IB/TWS Specialist (nur wenn IB betroffen)
       - Änderungen ausschließlich in:
         • broker.py
         • tests/ib/**
         • docs/ib/**
       - Neue Edge Cases → Fixture + Contract-Test + Bible-Update.

4) CODE REVIEW GATE:
   - Nutze code-review-ai.
   - Prüfe Konsistenz, Risiken, fehlende Tests.
   - Findings fixen oder kurz dokumentieren.

5) QA / TEST GATE:
   - Tests aus Acceptance Criteria ableiten/ergänzen.
   - Mindestabdeckung passend zum Ziel.
   - Bei IB: mind. 1 Fixture + 1 Contract-Test.

=====================================================================
DEFINITION OF DONE (Pflicht):
- Acceptance Criteria erfüllt.
- Tests ergänzt/aktualisiert.
- code-review-ai Findings adressiert oder bewusst dokumentiert.
- Kein Scope-Leak.
- Neues Wissen in Artefakte übertragen:
  • bei IB: docs/ib/ib_bible.md
  • sonst nur wenn wirklich nötig kurze Projektnotiz.

=====================================================================
START-ANWEISUNG (immer gleich):
Bitte starte mit Schritt 1 (Architect-light) und liefere ausschließlich:
- den Plan nach obiger Output-Regel
- inklusive [AGENT-SELECTION]-Box
- inklusive reduzierter Pipeline mit SKIPs
- inklusive Branch-Name + 2–4 Commit-Titeln.
KEIN Code in Schritt 1.
