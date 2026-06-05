# Contributing to Mark-SaaS

## Welcome

Mark-SaaS is an open-source document-to-Markdown pipeline for LLM and RAG applications. It takes raw documents, extracts text using MarkItDown or Docling, runs a multi-pass token optimization pipeline, and scores how much meaning was preserved using embedding-based semantic evaluation.

Contributions are welcome. The project is small enough that any meaningful improvement — a bug fix, a new optimizer pass, a scoring improvement, a UI fix — has a real impact.

---

## Before You Start

Read the [README](./README.md) first. It documents:

- The two extraction paths: `general_document` (MarkItDown) and `research_paper` (Docling)
- The four optimization modes: `safe`, `balanced`, `aggressive`, `rag`
- The three evaluation scores: Semantic Preservation, Context Preservation, and Overall Preservation
- The full API surface with all endpoints

Understanding the extraction → optimization → evaluation flow is essential before making changes to any of these layers.

---

## Repository Architecture

Here is where contributors should focus their work, based on the actual folder structure:

### Extraction layer — `backend/app/services/extractors.py`
Defines the `Extractor` abstract base class, `MarkItDownExtractor`, and `DoclingExtractor`. The `get_extractor()` factory function routes documents by `document_type`. If you want to add a new extraction strategy or modify existing extraction behavior, this is the starting point.

### OCR layer — `backend/app/services/ocr_service.py`, `backend/app/utils/ocr_handler.py`
`OCRService` manages the EasyOCR singleton. `ocr_handler.py` contains `needs_ocr_fallback()` and `run_ocr()` for whole-document OCR fallback. Embedded image OCR heuristics live in the conversion pipeline.

### Optimization layer — `backend/app/optimizer/`
The optimizer is a modular pipeline. Each pass lives in `backend/app/optimizer/passes/` as its own module and is auto-discovered by `PassRegistry` using `@register_pass`. The `OptimizationService` in `backend/app/services/optimization_service.py` maps the four modes to ordered pass lists.

Currently registered passes:
- `abbreviation_mining.py`
- `boilerplate_section.py`
- `citation.py`
- `content_boilerplate.py`
- `equation_preservation.py`
- `header_footer.py`
- `importance_aware.py`
- `ocr_cleanup.py`
- `paragraph_dedup.py`
- `reference_section.py`
- `semantic_dedup.py`
- `semantic_table_transform.py`
- `table_compression.py`

To add a new pass: create a new `.py` file in `passes/`, implement `OptimizerPass`, apply `@register_pass`, and add it to the relevant mode lists in `optimization_service.py`.

### Evaluation layer — `backend/app/services/semantic_scoring.py`
`SemanticScoringService.score()` computes three scores. The semantic score uses `sentence-transformers/all-MiniLM-L6-v2` with a BoW cosine fallback. The context score is a weighted composite of six sub-metrics: section score (25%), table score (20%), numeric score (20%), code score (10%), image score (10%), entity score (15%).

### API layer — `backend/app/api/routes/`
Seven route files: `health.py`, `upload.py`, `convert.py`, `chunk.py`, `download.py`, `stats.py`, `zip_upload.py`. All routes are registered under `/api` in `main.py`.

### Frontend — `frontend/`
Built with Next.js 16 and React 19. JavaScript (not TypeScript) with JSX. Styled with Tailwind CSS 4. The main application logic lives in `frontend/app/page.js`. State management is handled by `frontend/hooks/useConversion.js`. API calls go through `frontend/services/api.js` using the native `fetch` API. Components are in `frontend/components/`.

---

## Development Setup

### Backend

```bash
git clone https://github.com/VoidCrewTech67/Mark-SaaS.git
cd Mark-SaaS/backend

python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

The interactive API docs are at `http://localhost:8000/docs`.

**System dependencies** required by `pdf2image` and `easyocr`:
- Linux/macOS: `poppler-utils`, `libgl1-mesa-glx`, `libglib2.0-0`
- Windows: Poppler binaries on `PATH`

### Frontend

```bash
cd Mark-SaaS/frontend

cp .env.local.example .env.local
# NEXT_PUBLIC_API_URL defaults to http://localhost:8000

npm install
npm run dev
```

The UI runs at `http://localhost:3000`.

### Running both simultaneously

The root `package.json` includes a `concurrently` script:

```bash
cd Mark-SaaS
npm install          # installs concurrently
npm run dev          # starts both backend and frontend
```

---

## Types of Contributions

### Extraction improvements
Changes to `extractors.py`, `docling_service.py`, or the MarkItDown converter in `app/utils/converter.py`. Examples: better handling of a specific file format, improving extraction accuracy for a document type.

### OCR improvements
Changes to `ocr_service.py` or `ocr_handler.py`. Examples: tuning the `needs_ocr_fallback()` heuristic, improving embedded image OCR filtering.

### Optimization improvements
Adding or modifying passes in `backend/app/optimizer/passes/`. Each pass is self-contained. To add a pass, implement `OptimizerPass`, apply `@register_pass`, then add it to the appropriate mode list in `optimization_service.py`.

### Semantic preservation scoring improvements
Changes to `semantic_scoring.py`. The embedding path, BoW fallback, chunk sampling logic, and score computation are all in this one file.

### Context preservation evaluation improvements
Changes to the six sub-metric functions in `semantic_scoring.py` (`_score_sections`, `_score_tables`, `_score_numerics`, `_score_code`, `_score_images`, `_score_entities`) or their weights.

### UI improvements
Changes to components in `frontend/components/`. The primary display component is `ResultCard.jsx`. Upload behavior is in `UploadZone.jsx`. Application state lives in `hooks/useConversion.js`. API calls go through `services/api.js`.

### Documentation improvements
Changes to `README.md`, `CONTRIBUTING.md`, or inline code comments. Documentation should only describe what actually exists in the code.

### Bug fixes
Any fix to a broken behavior. Bug fix PRs should clearly describe the failure mode and include a short reproduction case in the description.

### Performance improvements
Examples: reducing EasyOCR initialization time, improving chunking throughput, reducing optimizer memory usage.

---

## Branch Naming

Create a branch from the current default branch before starting any work.

```
feat/description        — new functionality
fix/description         — bug fix
docs/description        — documentation only
refactor/description    — restructuring without behavior change
test/description        — adding or modifying tests
```

Examples:
```
feat/add-importance-aware-pass
fix/ocr-fallback-empty-output
docs/update-optimizer-modes
refactor/semantic-scoring-chunking
test/context-score-tables
```

---

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/). This keeps the history readable.

```
feat: add importance-aware optimizer pass
fix: correct table row count in context scoring
docs: document optimization modes in README
refactor: split ocr_handler into separate functions
test: add edge cases for semantic scoring with empty input
```

The format is `type: short description`. No period at the end. Present tense.

---

## Pull Requests

Before submitting:

- Describe what the PR changes and why. A one-line summary is not enough.
- For bug fixes, describe the failure mode and what was causing it.
- For new optimizer passes, explain what content is removed, why it is safe to remove, and how it interacts with the scoring layer.
- For UI changes, include a screenshot or screen recording.
- If your change affects documented behavior (API parameters, scoring output, config), update the relevant section of `README.md`.
- Run the existing test suite locally: `cd backend && pytest tests/`

Keep PRs focused. A PR that fixes an OCR bug and also adds a new optimizer pass is harder to review than two separate PRs.

---

## Engineering Principles

Mark-SaaS is built around five principles. Changes that violate these will not be merged.

**1. Semantic preservation over aggressive compression.**
Removing content to reduce tokens is only acceptable if the semantic score remains high. The scoring layer exists to catch regressions. A new optimizer pass that saves 5% tokens but drops the semantic score below 90% is not a good trade-off by default.

**2. Context retention over maximum token reduction.**
Structural elements — headings, tables, code blocks, numeric values, named entities — are preserved at higher weight than raw token savings. The six sub-metrics in `_context_score()` encode this priority directly.

**3. Reproducible evaluation metrics.**
Scores must be deterministic given the same input. Avoid random sampling in scoring unless the document is large enough to require it (the existing `_maybe_sample()` threshold is `>200,000` characters). When sampling is used, it must be logged.

**4. Transparent scoring.**
Every score is broken down into sub-metrics and issues that are returned to the caller. If the optimizer removes something meaningful, the scoring layer should surface it. Do not suppress warnings from the evaluation layer.

**5. Simple, maintainable code.**
The codebase uses standard Python patterns: dataclasses, ABCs, async/await over threads where appropriate. Frontend components are plain JSX with inline styles and CSS classes — no complex abstraction layers. Keep new code consistent with what is already there.

---

## Testing

The test suite is at `backend/tests/`. Currently there is one test file: `test_semantic_scoring.py`.

To run it:

```bash
cd backend
pytest tests/
```

If you modify `semantic_scoring.py`, add a test case. If you add a new optimizer pass, add a test that confirms what it removes and that it does not break on empty or minimal input.

There is no CI pipeline configured in the repository. Tests are run manually.

---

## Reporting Bugs

Open a GitHub issue with:

```
**Environment**
- OS:
- Python version:
- Node.js version:
- Docling installed: yes / no

**Document type**
- File format (PDF, DOCX, etc.):
- Document type used (general_document / research_paper):
- Optimization mode:

**Steps to reproduce**
1. Upload ...
2. Select ...
3. Click ...

**Expected behavior**


**Actual behavior**


**Relevant logs or error output**

```

---

## Suggesting Features

Open a GitHub issue with:

```
**What problem does this solve?**
Describe the specific failure or limitation you are encountering.

**Proposed solution**
What would you add or change?

**Where in the codebase would this live?**
e.g. a new optimizer pass, a change to the scoring weights, a new API parameter

**Alternatives you considered**


**Additional context**

```

---

## Documentation Contributions

Documentation should reflect what the code actually does. If you find something in `README.md` or `CONTRIBUTING.md` that is wrong, outdated, or missing, a PR fixing it is welcome.

The bar for documentation PRs:
- Verify any technical claim against the source code before writing it.
- Do not add sections for features that do not exist yet.
- Keep language plain and direct.

---

## Recognition

Every contribution that improves the project is appreciated — whether it is a one-line fix, a new optimizer pass, or a test that catches a regression. There is no minimum size for a meaningful contribution.
