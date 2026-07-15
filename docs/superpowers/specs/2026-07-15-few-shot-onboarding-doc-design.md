# Spec: Unified few-shot sample onboarding guide (issue #109)

## Why

Adding a few-shot sample requires reverse-engineering three different loaders (math globs `data/few_shot/{style}/*.json`; social studies mixes root JSON + `few_shot_examples.csv`; natural sciences uses folder-per-題型). Validation rules and "how do I confirm my sample loaded" are documented nowhere; malformed JSON is silently dropped.

## Design

New `docs/ADDING_SAMPLES.md` (zh-TW to match `csv_填寫指南.md`, since data fillers are the audience) with:

1. **Per-subject sections** — target directories, file shape with a minimal working example each:
   - Math: `data/few_shot/{text_only|with_chart|with_image|creative_scenario}/`, single-example dict shape, image-manifest support.
   - Social studies: root JSON vs `few_shot_examples.csv` — JSON for one-off curated examples, CSV for bulk multi-小題 sets; link to `data/social_studies/csv_填寫指南.md`; note `範例_`-prefixed files are never loaded.
   - Natural sciences: `_TYPE_TO_FOLDER` mapping (Simple/Complex-multiple-choice, Constructed-response), 評分規準 JSON-array requirement, fallback scan when 題型 unknown.
2. **Validation rules** — 情境 enums per subject, 科學能力 codes, required fields per 題型, `chart_spec` must be valid JSON or it is silently dropped, CSV `utf-8-sig` + `;` separators.
3. **How to verify your sample loads** — one-liner per subject, e.g. `uv run python -c "from src.natural_sciences.data_loader import load_few_shot_example_groups; print(len(load_few_shot_example_groups('Constructed-response')))"`, plus `pytest -k few_shot`.
4. **Runtime reload** — loaders re-glob per request; no server restart or redeploy needed.

Cross-links: top-of-file docstring pointer to the doc in all three loaders (`src/data_loader.py`, `src/social_studies/data_loader.py`, `src/natural_sciences/data_loader.py`), and a README contributor-section link.

## Testing

Docs-only change; acceptance is the issue's checklist (doc exists and covers three subjects; loader docstrings and README link to it). Verify the "how to test" one-liners actually run before committing them.

## Out of scope

- Loader refactors or unification.
- A sample-validation CLI (separate issue if wanted).
