# Changelog

All notable changes to Aegis are documented in this file.

## [0.2.0] - 2026-08-08

### Added

- Configurable SQLite world-model database path.
- SQLite repositories for pipeline runs, stages, and evaluated tracks.
- Automatic run-manifest persistence throughout pipeline execution.
- Automatic evaluated-track persistence after successful runs.
- Idempotent archived-manifest importer.
- Idempotent evaluated-track importer.
- SQLite-backed run-history service with JSON fallback.
- SQLite-backed latest-track API with CSV fallback.
- Historical per-run statistics endpoint.
- Historical per-run track-list endpoint.
- Historical individual-track endpoint.
- SQLite-backed run-comparison queries.
- Database availability and active-storage details in API health responses.
- Automated repository, importer, persistence, API, and historical-query tests.

### Changed

- The pipeline now records run state in JSON and SQLite.
- The API prefers SQLite for run history and evaluated tracks.
- The API service version is now 0.6.0.
- The dashboard receives its latest world-model data from SQLite when available.
- Completed runs expose database-track persistence status in their manifests.
- Documentation now describes SQLite storage, import tools, and historical APIs.

### Compatibility

- JSON run manifests remain generated and readable.
- Archived JSON run history remains supported as a fallback.
- Evaluated-track CSV output remains generated and readable.
- Existing JSON history and evaluated-track CSV data can be imported repeatedly without creating duplicate records.
- Older manifests without processing metrics remain readable.

## [0.1.0] - 2026-08-06

### Added

- Recorded-video ingestion.
- YOLO object detection.
- ByteTrack persistent multi-object tracking.
- Annotated tracking video.
- Frame-level track observations.
- Per-track temporal summaries.
- Stable, tentative, and weak track-quality evaluation.
- Validated JSON pipeline configuration.
- Unified offline pipeline runner.
- Processing metrics.
- Latest and archived run manifests.
- Run-performance comparison.
- Read-only FastAPI service.
- Main situational-awareness dashboard.
- Run-comparison dashboard.
- Automated tests and GitHub Actions continuous integration.
