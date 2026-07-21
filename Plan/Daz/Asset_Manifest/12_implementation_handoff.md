# Developer and AI Implementation Handoff

## Required services

1. `archive_scanner`: safe archive listing, hashing, DSX/supplement extraction, member records.
2. `placement_classifier`: matches only materialized 401-path taxonomy; produces explanation/confidence.
3. `install_differ`: pre/post native-library snapshots and archive-member joins.
4. `dson_scanner`: JSON/zlib decoding, assets/references/formulas/geometry/material/property extraction.
5. `cms_adapter`: read-only DAZ Asset Manager/Content Manager metadata capture.
6. `daz_runtime_inspector`: clean-scene fixtures, before/after snapshots, component/property diff, smokes.
7. `semantic_mapper`: controlled asset/body classification with evidence and confidence.
8. `manifest_validator`: schema, vocabulary, taxonomy, graph, path, hash, ontology, and idempotence checks.
9. `registry_writer`: atomic revision publication, immutable evidence, product/package/file/search indexes.

## Recommended runtime layout

```text
F:\DAZ\05_registry\
  manifests\assets\ products\ packages\
  snapshots\
  indexes\assets.jsonl products.jsonl files.jsonl properties.jsonl body_taxa.jsonl
  inspection\<asset_id>\<inspection_id>\
  rejected\
```

YAML is the canonical portable record. SQLite/Parquet/search indexes are rebuildable projections. Store one
JSONL row per entity for fast lookup; include entity ID, parent manifest/revision, canonical name/class,
generation, body taxa, file path/hash, qualification state, and a pointer to canonical YAML.

## API/CLI contract

Minimum commands: `scan-archive`, `classify`, `install-diff`, `inspect-static`, `inspect-runtime`,
`validate`, `publish`, `rescan`, `diff-revision`, `rebuild-index`, `find`, and `report-unknowns`. All commands
support `--dry-run`, structured JSON output, job ID, deterministic logging, and nonzero failure codes.

## Transaction rules

Use a staging directory on the same volume; fsync; validate; atomically rename; then update indexes. A
crash before publication leaves canonical manifests unchanged. Lock by manifest ID, not global registry.
Evidence is immutable and content-addressed. Never partially update a manifest in place.

## Implementation order and acceptance

1. Schema/vocabulary/taxonomy loader and validator.
2. Archive scanner and stable-ID/hash library.
3. Native install snapshot/diff and file graph.
4. DSON parser/reference resolver.
5. Runtime inspector and clean fixtures.
6. Semantic/body mapper and ontology adapter.
7. Atomic registry/index/search layer.
8. Batch orchestrator, reports, targeted reinspection.

Each stage needs unit fixtures, malformed inputs, Windows path/case tests, compressed DSON, missing
references, duplicate archives, multi-package products, multiple user-facing assets, runtime dialogs,
controller cycles, left/right assets, and an idempotent end-to-end rescan.

## AI handoff prompt

“Read this package in index order. Treat the schema, vocabularies, and taxonomy as closed contracts. Process
one immutable archive hash per job. Preserve native DAZ install paths. Record observations and uncertainties;
do not invent values. Perform static and clean-scene runtime differential inspection, validate every graph
and hash, publish atomically, and retain every earlier revision and evidence record.”
