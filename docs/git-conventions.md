# Git Conventions

## Branch

```
feat/<n>     → Feature
fix/<n>      → Bugfix
refactor/<n> → Umbau
```

## Commit

```
<type>(<scope>): <beschreibung>

Types: feat, fix, refactor, test, docs
Scopes: ib, state, ui, config
```

## Beispiele

```
feat(ib): add trailing stop
fix(state): handle null positions
test(ib): add reconnect fixture
```

## Workflow

```bash
# Branch
git checkout -b feat/trailing-stop

# Commits
git commit -m "feat(ib): add trailing stop"
git commit -m "feat(state): integrate trailing stop"

# Merge
git checkout main
git merge feat/trailing-stop
```
