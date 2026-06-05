# Contributing to Mark-SaaS

## Welcome

First, thank you for your interest in contributing to Mark-SaaS! We appreciate contributions of all sizes—whether you're fixing a typo, opening a bug report, or implementing a new feature in the token optimization pipeline.

This document outlines the process for contributing to the repository.

## Project Philosophy

Before diving in, it is helpful to understand what Mark-SaaS prioritizes as an engineering project:

1. **Semantic Preservation:** Code changes must not degrade the meaning of the optimized documents.
2. **Context Retention:** Structural elements (tables, lists, figures, references) must survive the pipeline.
3. **Token Efficiency:** The core goal is reducing LLM token consumption.
4. **Transparency:** If the system makes a trade-off, it should be measurable and visible to the user.
5. **Practical Engineering Over Hype:** We prioritize working, stable implementations over bleeding-edge, unverified claims.

## Ways to Contribute

There are many ways to get involved:

- **Bug Reports:** If something is broken, please let us know.
- **Documentation Improvements:** Keeping our README and code comments clear and accurate.
- **UI/UX Improvements:** Enhancing the frontend dashboard and conversion tools.
- **OCR Improvements:** Fine-tuning EasyOCR heuristics for embedded image extraction.
- **Optimization Pipeline Enhancements:** Adding or improving token reduction passes.
- **Evaluation Metric Improvements:** Refining semantic and context scoring logic.
- **Testing:** Expanding unit tests to cover edge cases.
- **Performance Improvements:** Optimizing extraction latency or chunking speed.

## Development Setup

To start contributing, you will need to set up the repository locally.

### 1. Fork and Clone
Fork the repository on GitHub, then clone your fork:
```bash
git clone https://github.com/YOUR-USERNAME/Mark-SaaS.git
cd Mark-SaaS
```

### 2. Backend Setup
We recommend using a virtual environment for the Python backend.
```bash
cd backend
python -m venv venv

# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
```

To run the backend server:
```bash
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup
Open a new terminal session and navigate to the frontend directory:
```bash
cd frontend
npm install
```

To run the frontend development server:
```bash
npm run dev
```
The application will be accessible at `http://localhost:3000`.

## Branch Strategy

All work should be done on a dedicated feature branch created from `main`. We use the following branch naming conventions:

- `feat/feature-name` (e.g., `feat/add-docling-extractor`)
- `fix/bug-name` (e.g., `fix/easyocr-memory-leak`)
- `docs/topic-name` (e.g., `docs/update-architecture-flow`)
- `refactor/component-name` (e.g., `refactor/chunking-logic`)
- `test/component-name` (e.g., `test/semantic-scoring`)

## Commit Convention

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification for our commit messages. This helps us maintain a readable history.

- `feat:` A new feature
- `fix:` A bug fix
- `docs:` Documentation only changes
- `refactor:` A code change that neither fixes a bug nor adds a feature
- `test:` Adding missing tests or correcting existing tests
- `chore:` Changes to the build process or auxiliary tools

**Example:**
```text
feat: add table compression pass to optimization pipeline
fix: resolve null pointer exception in chunking service
```

## Code Standards

To keep the codebase maintainable, please follow these guidelines:

### Backend (Python)
- **Python Best Practices:** Follow standard Python practices and PEP 8 guidelines.
- **Type Hints:** Use type hints where practical to improve clarity.
- **Clear Function Names:** Names should describe exactly what the function does.
- **Small Reusable Modules:** Keep functions and classes small, focused, and single-responsibility.

### Frontend (TypeScript/React)
- **TypeScript-First:** Use TypeScript for all new code to ensure type safety.
- **Reusable React Components:** Build components that can be shared across the UI.
- **Consistent Formatting:** Rely on established code formatters to maintain style.

### General
- **Readability Over Cleverness:** Write code that is easy for the next developer to understand.
- **Prefer Maintainability:** Simple, well-documented code is better than complex optimizations.
- **Avoid Unnecessary Dependencies:** Evaluate if a new package is truly needed before adding it.

## Testing

Reliable tests are critical for a pipeline dealing with unstructured data.
- **New Features:** Must include tests verifying the new behavior.
- **Bug Fixes:** Should include a test that reproduces the bug to prevent regressions.
- **Regression Prevention:** Ensure the existing test suite passes before opening a Pull Request.

## Pull Request Guidelines

When you are ready to submit your code, please ensure your Pull Request meets these criteria:

- **Clear Description:** Explain *what* the PR does and *why* it is needed.
- **Small, Focused PRs:** Keep PRs scoped to a single problem or feature.
- **Screenshots:** Include screenshots or screen recordings for any UI changes.
- **Related Issue References:** Link to relevant open issues (e.g., "Fixes #42").
- **Passing Tests:** Verify all tests pass locally.
- **Updated Documentation:** Update `README.md` or code comments if you alter system behavior.

## Reporting Bugs

When submitting a bug report via GitHub Issues, please include:
- **Environment:** OS, Python version, Node.js version.
- **Steps to Reproduce:** Exact sequence of actions to trigger the bug.
- **Expected Behavior:** What you thought would happen.
- **Actual Behavior:** What actually happened.
- **Screenshots/Logs:** Any relevant error traces or visuals.

## Suggesting Features

If you have an idea for Mark-SaaS, please open an issue with the following information:
- **Problem:** The specific issue or limitation you are facing.
- **Proposed Solution:** How you think the problem should be addressed.
- **Alternatives Considered:** Other approaches you thought about.
- **Additional Context:** Any metrics, examples, or links that support your request.

## Recognition

Every meaningful contribution helps improve this project. Whether you're reporting a bug, writing documentation, or submitting core infrastructure code, your effort is highly appreciated. Thank you for making Mark-SaaS better!
