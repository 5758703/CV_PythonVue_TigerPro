# GitHub 标签约定（LABELS）

创建 Issue 后请打齐标签。维护者可用 GitHub UI 或 `gh label create` 批量创建。

## 类型（必选其一）

| Name | Color（建议） | Description |
|------|---------------|-------------|
| `bug` | `d73a4a` | Something isn't working |
| `feature` | `a2eeef` | New feature request |
| `enhancement` | `84b6eb` | Improve existing capability |
| `docs` | `0075ca` | Documentation only |
| `refactor` | `fbca04` | Code change without behavior change |

## 模块（可多选）

| Name | Color | Description |
|------|-------|-------------|
| `backend` | `5319e7` | Flask / server |
| `frontend` | `bfdadc` | Vue frontend |
| `ai` | `e99695` | Inference / models / CV / speech |
| `devops` | `0e8a16` | Deploy / CI / scripts |
| `database` | `c5def5` | Schema / migration / seed |

## 状态

| Name | Color | Description |
|------|-------|-------------|
| `needs-triage` | `ededed` | Needs maintainer triage |
| `ready` | `c2e0c6` | Ready to be claimed |
| `in-progress` | `1d76db` | Someone is working on it |
| `blocked` | `b60205` | Blocked by dependency/decision |

## 优先级

| Name | Color | Description |
|------|-------|-------------|
| `P0` | `b60205` | Critical |
| `P1` | `d93f0b` | High |
| `P2` | `fbca04` | Medium |
| `P3` | `fef2c0` | Low |

## 难度

| Name | Color | Description |
|------|-------|-------------|
| `good-first-issue` | `7057ff` | Good for newcomers |
| `help-wanted` | `008672` | Extra attention needed |
| `advanced` | `e4e669` | Requires domain expertise |

## 批量创建示例（gh CLI）

```bash
gh label create "bug" --color d73a4a --description "Something isn't working"
gh label create "feature" --color a2eeef --description "New feature request"
gh label create "enhancement" --color 84b6eb --description "Improve existing capability"
gh label create "docs" --color 0075ca --description "Documentation only"
gh label create "refactor" --color fbca04 --description "Refactor without behavior change"
gh label create "backend" --color 5319e7 --description "Flask / server"
gh label create "frontend" --color bfdadc --description "Vue frontend"
gh label create "ai" --color e99695 --description "Inference / models"
gh label create "devops" --color 0e8a16 --description "Deploy / CI / scripts"
gh label create "database" --color c5def5 --description "Schema / migration / seed"
gh label create "needs-triage" --color ededed --description "Needs triage"
gh label create "ready" --color c2e0c6 --description "Ready to claim"
gh label create "in-progress" --color 1d76db --description "In progress"
gh label create "blocked" --color b60205 --description "Blocked"
gh label create "P0" --color b60205 --description "Priority critical"
gh label create "P1" --color d93f0b --description "Priority high"
gh label create "P2" --color fbca04 --description "Priority medium"
gh label create "P3" --color fef2c0 --description "Priority low"
gh label create "good-first-issue" --color 7057ff --description "Good for newcomers"
gh label create "help-wanted" --color 008672 --description "Help wanted"
gh label create "advanced" --color e4e669 --description "Advanced"
```
