# Repository Guidelines

## Project Structure and Module Organization

- `agent1/bugfix_agent1/` implements defect ingestion and the `bugfix-agent` CLI. Agent 1 produces `defect-batch.json` outside LangGraph.
- `platform/bugfix_platform/` contains Agent 2 (`agents/cartographer/`), Agent 3 (`agents/analyst/`), Claude SDK integration (`sdk/`), and LangGraph orchestration (`workflow/`). Keep Agent 1 and the platform independent. Share Pydantic artifact models through `contracts/bugfix_contracts/`.
- Built-in skills live under `agent1/skills/` and `platform/skills/`. Find architecture and artifact documentation in `docs/`, evaluation scripts in `evals/`, and release tooling in `packaging/`.

## Build, Test, and Development Commands

Use Python 3.11 or later. Run these commands from the repository root.

- `python -m pip install -e ".[dev]"` installs development and test dependencies.
- `bugfix-agent prepare-batch --source raw.csv --product-line hc --out batch.json` prepares a batch from a defect export.
- `bugfix-platform run --work-dir ./repos --product-line hc --defect-batch batch.json --cartography-profile micro_frontend --cartography-mode heuristic --analyze-mode heuristic --out-dir ./out` runs Agents 2 and 3 locally without a model. Set the profile to match your target repository.
- `python packaging/build.py platform` builds and verifies the platform ZIP. Install `.[dev,sdk]` before building so the packager can bundle the SDK. Use the `agent1` target with the `.[build]` extra to build the Agent 1 executable and skill package.

## Coding Style and Naming

Use four-space indentation, UTF-8, and LF line endings. Follow Python conventions with `snake_case` for functions and modules and `PascalCase` for classes. Preserve existing JSON names such as `defectId` when changing contract models.

## Testing Guidelines

Run `python -m pytest -q` for the full suite or `python -m pytest -q tests/platform/test_workflow.py` for a focused run. Name files and functions `test_*.py` and `test_*`. Add regression coverage in the matching `tests/` area. Use `tests/fixtures/` and stub SDK calls for routine tests. The suite disables real CodeGraph by default.

## Commits and Pull Requests

Use a short subject that describes the change, following recent prefixes such as `feat(sdk):`, `fix:`, or `docs:`. In pull requests, describe affected agents or contracts, link the issue if available, and list the tests and builds you ran. Keep local `.env` files, credentials, and generated artifacts out of commits.
