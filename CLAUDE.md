# CLAUDE.md — MyEngineAPI

This file provides context, conventions, and workflows for AI assistants (and human developers) working in this repository.

> **Current State:** This repository is newly initialized and contains no source code yet. This document should be updated as the project takes shape.

---

## Repository Overview

| Field        | Value                                      |
|--------------|--------------------------------------------|
| **Name**     | MyEngineAPI                                |
| **Remote**   | stefanfrost1/MyEngineAPI                   |
| **Branch**   | Work on feature branches; never push directly to `main` |
| **Status**   | Empty — project scaffolding not yet added  |

---

## Repository Structure (Expected)

As code is added, this section should be updated to reflect the actual layout. A typical API project structure might look like:

```
MyEngineAPI/
├── CLAUDE.md              # This file
├── README.md              # Human-facing project documentation
├── .gitignore
├── src/                   # Primary source code
│   ├── main.*             # Entry point
│   ├── routes/            # HTTP route handlers
│   ├── controllers/       # Business logic
│   ├── models/            # Data models / ORM schemas
│   ├── services/          # External integrations, domain services
│   └── utils/             # Shared utilities
├── tests/                 # Test suite
│   ├── unit/
│   └── integration/
├── docs/                  # API documentation, architecture notes
└── config/                # Environment-specific configuration
```

**Update this section** with the real structure once files are added.

---

## Development Setup

> These commands are placeholders. Replace them with actual commands once the stack is chosen.

### Prerequisites

- Document runtime versions here (e.g., Node 20+, Python 3.11+, Go 1.22+)
- Document any required environment variables or `.env` setup

### Install Dependencies

```bash
# Example — replace with actual command
npm install          # Node.js
pip install -r requirements.txt  # Python
go mod download      # Go
```

### Run Locally

```bash
# Example — replace with actual command
npm run dev
python -m uvicorn main:app --reload
go run ./cmd/server
```

### Environment Variables

Document all required environment variables here. Example:

```
PORT=8080
DATABASE_URL=postgres://...
API_KEY=...
```

---

## Testing

### Run Tests

```bash
# Example — replace with actual commands
npm test
pytest
go test ./...
```

### Test Conventions

- Unit tests live alongside source files or in `tests/unit/`
- Integration tests live in `tests/integration/`
- All new features should include tests
- Do not commit code that breaks existing tests

---

## Build & Deployment

```bash
# Example — replace with actual build command
npm run build
docker build -t myengineapi .
```

Document any CI/CD pipelines here once configured.

---

## Git Workflow

### Branching

- `main` — stable, production-ready code
- Feature branches: `feature/<short-description>`
- Bug fixes: `fix/<short-description>`
- Claude AI branches follow the pattern: `claude/<session-id>`

### Commit Messages

Use conventional commit format:

```
<type>(<scope>): <short summary>

<optional body>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Examples:
```
feat(api): add engine status endpoint
fix(auth): correct token expiration handling
docs: update CLAUDE.md with project structure
```

### Pull Requests

- All changes go through pull requests; direct pushes to `main` are discouraged
- PRs should include a description of what changed and why
- Link relevant issues in the PR description

---

## Code Conventions

> Update this section once the language and framework are decided.

### General

- Prefer clarity over cleverness
- Keep functions small and focused on a single responsibility
- Avoid over-engineering — solve the problem at hand, not hypothetical future problems
- Do not add unnecessary comments; code should be self-documenting where possible

### Naming

- Use consistent naming conventions for the chosen language (e.g., `camelCase` for JS, `snake_case` for Python)
- Name variables and functions to reflect their purpose
- Avoid abbreviations unless they are universally understood

### Error Handling

- Surface errors explicitly; do not silently swallow exceptions
- Return meaningful error messages to API callers
- Log errors with enough context to debug in production

### Security

- Never commit secrets, API keys, or credentials
- Validate all user input at API boundaries
- Use parameterized queries or ORMs to prevent SQL injection
- Apply least-privilege principles to service accounts and database users

---

## API Conventions

> Fill in once the API design is established.

- Base path: `/api/v1/`
- Authentication: (TBD — e.g., Bearer token, API key)
- Response format: JSON
- HTTP status codes should be used semantically (200, 201, 400, 401, 404, 500, etc.)

### Example Response Shape

```json
{
  "data": { ... },
  "error": null
}
```

Error response:

```json
{
  "data": null,
  "error": {
    "code": "NOT_FOUND",
    "message": "Resource not found"
  }
}
```

---

## For AI Assistants

### Key Principles

1. **Read before editing.** Always read relevant files before making changes.
2. **Minimal changes.** Only change what is necessary to fulfill the request.
3. **No speculation.** Do not add features, error handling, or abstractions that weren't asked for.
4. **Test first.** After implementing changes, verify that tests pass before committing.
5. **Branch discipline.** Always work on the designated branch; never push to `main` directly.
6. **Commit clearly.** Write descriptive commit messages that explain the "why."
7. **No secrets.** Never commit environment variables, tokens, or credentials.

### Branch for AI Work

Claude agents must develop on branches matching the pattern `claude/<session-id>`. Push to that branch and open a PR — do not merge to `main`.

### Common Tasks

| Task                  | Command (update once stack is set)    |
|-----------------------|---------------------------------------|
| Run tests             | `npm test` / `pytest` / `go test`     |
| Start dev server      | `npm run dev` / `uvicorn` / `go run`  |
| Lint                  | `npm run lint` / `flake8` / `golint`  |
| Format code           | `prettier` / `black` / `gofmt`        |
| Check types           | `tsc --noEmit` / `mypy`               |

---

## Maintenance

This CLAUDE.md should be updated whenever:

- The project stack or language is finalized
- New services or major components are added
- Development workflows change
- New conventions are adopted by the team

*Last updated: 2026-02-26 (initial creation — empty repository)*
