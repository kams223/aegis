"use strict";

const statusElement = document.getElementById("system-status");
const statusText = document.getElementById("status-text");

const tableBody = document.getElementById("track-table-body");
const tableMessage = document.getElementById("table-message");

const runContent = document.getElementById("run-content");
const runMessage = document.getElementById("run-message");
const runPanelTitle = document.getElementById(
    "run-panel-title"
);
const stageTableBody = document.getElementById(
    "stage-table-body"
);

const historyTableBody = document.getElementById(
    "history-table-body"
);
const historyMessage = document.getElementById(
    "history-message"
);

function setText(id, value) {
    const element = document.getElementById(id);

    if (element) {
        element.textContent = String(value);
    }
}

function createCell(value) {
    const cell = document.createElement("td");
    cell.textContent = String(value);
    return cell;
}

function formatDuration(value) {
    const duration = Number(value);

    if (!Number.isFinite(duration)) {
        return "Unavailable";
    }

    if (duration < 1) {
        return `${duration.toFixed(3)} s`;
    }

    return `${duration.toFixed(2)} s`;
}

function formatNumber(value, decimalPlaces = 0) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "Unavailable";
    }

    return number.toFixed(decimalPlaces);
}

function formatTimestamp(value) {
    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "Unavailable";
    }

    return date.toLocaleString();
}

function createStatusCell(status) {
    const cell = document.createElement("td");
    const badge = document.createElement("span");

    badge.className = `badge ${status || ""}`;
    badge.textContent = status || "unknown";

    cell.appendChild(badge);

    return cell;
}

function createPerformanceItem(label, value, id) {
    const item = document.createElement("article");
    item.className = "run-item";

    const labelElement = document.createElement("div");
    labelElement.className = "run-label";
    labelElement.textContent = label;

    const valueElement = document.createElement("div");
    valueElement.id = id;
    valueElement.className = "run-value";
    valueElement.textContent = value;

    item.appendChild(labelElement);
    item.appendChild(valueElement);

    return item;
}

function ensurePerformancePanel() {
    let panel = document.getElementById(
        "performance-panel"
    );

    if (panel) {
        return panel;
    }

    panel = document.createElement("section");
    panel.id = "performance-panel";

    const heading = document.createElement("h3");
    heading.className = "stage-heading";
    heading.textContent = "Processing performance";

    const grid = document.createElement("div");
    grid.className = "run-grid";

    grid.appendChild(
        createPerformanceItem(
            "Processing FPS",
            "Unavailable",
            "performance-fps"
        )
    );

    grid.appendChild(
        createPerformanceItem(
            "Frames processed",
            "Unavailable",
            "performance-frames"
        )
    );

    grid.appendChild(
        createPerformanceItem(
            "Frame detections",
            "Unavailable",
            "performance-detections"
        )
    );

    grid.appendChild(
        createPerformanceItem(
            "Tracked observations",
            "Unavailable",
            "performance-observations"
        )
    );

    grid.appendChild(
        createPerformanceItem(
            "Unique tracks",
            "Unavailable",
            "performance-unique-tracks"
        )
    );

    grid.appendChild(
        createPerformanceItem(
            "Source resolution",
            "Unavailable",
            "performance-resolution"
        )
    );

    grid.appendChild(
        createPerformanceItem(
            "Source FPS",
            "Unavailable",
            "performance-source-fps"
        )
    );

    grid.appendChild(
        createPerformanceItem(
            "Processing duration",
            "Unavailable",
            "performance-duration"
        )
    );

    grid.appendChild(
        createPerformanceItem(
            "Initialization overhead",
            "Unavailable",
            "performance-overhead"
        )
    );

    grid.appendChild(
        createPerformanceItem(
            "Pipeline duration",
            "Unavailable",
            "performance-pipeline-duration"
        )
    );

    panel.appendChild(heading);
    panel.appendChild(grid);

    const fingerprint = document.getElementById(
        "run-fingerprint"
    );

    fingerprint.insertAdjacentElement(
        "afterend",
        panel
    );

    return panel;
}

function ensureHistoryPerformanceHeaders() {
    const historyTable = historyTableBody.closest("table");

    if (!historyTable) {
        return;
    }

    const headerRow = historyTable.querySelector(
        "thead tr"
    );

    if (
        !headerRow ||
        headerRow.querySelector(
            "[data-performance-column]"
        )
    ) {
        return;
    }

    const headers = [
        "Processing FPS",
        "Frames",
        "Detections",
        "Processing time",
    ];

    for (const label of headers) {
        const header = document.createElement("th");

        header.dataset.performanceColumn = "true";
        header.textContent = label;

        headerRow.appendChild(header);
    }
}

function renderPerformance(manifest) {
    ensurePerformancePanel();

    const performance = manifest.performance || {};
    const metrics = performance.processing_metrics || {};
    const results = metrics.results || {};
    const video = metrics.video || {};

    const metricsAvailable =
        performance.processing_metrics_available === true;

    if (!metricsAvailable) {
        setText("performance-fps", "Unavailable");
        setText("performance-frames", "Unavailable");
        setText(
            "performance-detections",
            "Unavailable"
        );
        setText(
            "performance-observations",
            "Unavailable"
        );
        setText(
            "performance-unique-tracks",
            "Unavailable"
        );
        setText(
            "performance-resolution",
            "Unavailable"
        );
        setText(
            "performance-source-fps",
            "Unavailable"
        );
        setText(
            "performance-duration",
            "Unavailable"
        );
    } else {
        setText(
            "performance-fps",
            `${formatNumber(
                results.average_processing_fps,
                2
            )} FPS`
        );

        setText(
            "performance-frames",
            formatNumber(results.frames_processed)
        );

        setText(
            "performance-detections",
            formatNumber(results.frame_detections)
        );

        setText(
            "performance-observations",
            formatNumber(results.tracked_observations)
        );

        setText(
            "performance-unique-tracks",
            formatNumber(results.unique_tracks)
        );

        const width = Number(video.width);
        const height = Number(video.height);

        const resolution = (
            Number.isFinite(width) &&
            Number.isFinite(height)
        )
            ? `${width} × ${height}`
            : "Unavailable";

        setText(
            "performance-resolution",
            resolution
        );

        const sourceFps = Number(video.source_fps);

        setText(
            "performance-source-fps",
            Number.isFinite(sourceFps)
                ? `${sourceFps.toFixed(2)} FPS`
                : "Unavailable"
        );

        setText(
            "performance-duration",
            formatDuration(metrics.duration_seconds)
        );
    }

    setText(
        "performance-overhead",
        formatDuration(
            performance.initialization_overhead_seconds
        )
    );

    setText(
        "performance-pipeline-duration",
        formatDuration(
            performance.pipeline_duration_seconds
        )
    );
}

function renderTracks(tracks) {
    tableBody.replaceChildren();

    if (tracks.length === 0) {
        tableMessage.textContent =
            "No tracks match the selected filters.";
        tableMessage.hidden = false;
        return;
    }

    tableMessage.hidden = true;

    for (const track of tracks) {
        const row = document.createElement("tr");

        row.appendChild(createCell(track.track_id));
        row.appendChild(createCell(track.dominant_label));
        row.appendChild(
            createStatusCell(track.quality_level)
        );

        row.appendChild(
            createCell(
                `${(
                    Number(track.average_confidence) * 100
                ).toFixed(1)}%`
            )
        );

        row.appendChild(
            createCell(track.observation_count)
        );

        row.appendChild(
            createCell(
                formatDuration(track.duration_seconds)
            )
        );

        row.appendChild(
            createCell(
                `${Number(
                    track.displacement_pixels
                ).toFixed(1)} px`
            )
        );

        row.appendChild(
            createCell(
                `${track.first_frame}–${track.last_frame}`
            )
        );

        tableBody.appendChild(row);
    }
}

function renderStages(stages) {
    stageTableBody.replaceChildren();

    for (const stage of stages) {
        const row = document.createElement("tr");

        row.appendChild(createCell(stage.name));
        row.appendChild(createStatusCell(stage.status));

        row.appendChild(
            createCell(
                formatDuration(stage.duration_seconds)
            )
        );

        row.appendChild(createCell(stage.exit_code));

        stageTableBody.appendChild(row);
    }
}

function renderRun(manifest, isLatest) {
    const model = manifest.model || {};
    const input = manifest.input || {};
    const stages = Array.isArray(manifest.stages)
        ? manifest.stages
        : [];

    const runId = manifest.run_id || "legacy-run";

    runPanelTitle.textContent = isLatest
        ? "Latest pipeline run"
        : `Archived pipeline run: ${runId}`;

    setText("run-id", runId);
    setText("run-status", manifest.status || "unknown");

    setText(
        "run-finished",
        formatTimestamp(manifest.finished_at_utc)
    );

    setText(
        "run-duration",
        formatDuration(manifest.duration_seconds)
    );

    setText(
        "run-model",
        model.model_path || "Unavailable"
    );

    setText(
        "run-device",
        model.device || "Unavailable"
    );

    setText(
        "run-input",
        input.path || "Unavailable"
    );

    const runStatus = document.getElementById(
        "run-status"
    );

    runStatus.className =
        `run-value run-status ${manifest.status || ""}`;

    setText(
        "run-fingerprint",
        `SHA-256: ${input.sha256 || "Unavailable"}`
    );

    renderPerformance(manifest);
    renderStages(stages);

    runMessage.hidden = true;
    runContent.hidden = false;
}

function renderRunHistory(runs) {
    ensureHistoryPerformanceHeaders();
    historyTableBody.replaceChildren();

    if (runs.length === 0) {
        historyMessage.textContent =
            "No archived pipeline runs are available.";
        historyMessage.hidden = false;
        return;
    }

    historyMessage.hidden = true;

    for (const run of runs) {
        const row = document.createElement("tr");

        const runIdCell = document.createElement("td");
        const runButton = document.createElement("button");

        runButton.type = "button";
        runButton.className = "run-link";
        runButton.textContent = run.run_id || "unknown";

        runButton.addEventListener(
            "click",
            () => loadArchivedRun(run.run_id)
        );

        runIdCell.appendChild(runButton);
        row.appendChild(runIdCell);

        row.appendChild(createStatusCell(run.status));

        row.appendChild(
            createCell(
                formatTimestamp(run.finished_at_utc)
            )
        );

        row.appendChild(
            createCell(
                formatDuration(run.duration_seconds)
            )
        );

        row.appendChild(
            createCell(run.model_path || "Unavailable")
        );

        row.appendChild(
            createCell(run.device || "Unavailable")
        );

        row.appendChild(
            createCell(run.stage_count)
        );

        const metricsAvailable =
            run.processing_metrics_available === true;

        row.appendChild(
            createCell(
                metricsAvailable
                    ? `${formatNumber(
                        run.average_processing_fps,
                        2
                    )} FPS`
                    : "Unavailable"
            )
        );

        row.appendChild(
            createCell(
                metricsAvailable
                    ? formatNumber(
                        run.frames_processed
                    )
                    : "Unavailable"
            )
        );

        row.appendChild(
            createCell(
                metricsAvailable
                    ? formatNumber(
                        run.frame_detections
                    )
                    : "Unavailable"
            )
        );

        row.appendChild(
            createCell(
                metricsAvailable
                    ? formatDuration(
                        run.processing_duration_seconds
                    )
                    : "Unavailable"
            )
        );

        historyTableBody.appendChild(row);
    }
}

async function requestJson(path) {
    const response = await fetch(path, {
        headers: {
            Accept: "application/json",
        },
        cache: "no-store",
    });

    if (!response.ok) {
        throw new Error(
            `${path} returned HTTP ${response.status}`
        );
    }

    return response.json();
}

async function loadHealth() {
    const health = await requestJson("/health");

    statusText.textContent = health.status;

    statusElement.classList.toggle(
        "healthy",
        health.status === "healthy"
    );
}

async function loadStatistics() {
    const statistics = await requestJson("/statistics");

    setText("total-count", statistics.total_tracks);

    setText(
        "stable-count",
        statistics.quality_counts.stable
    );

    setText(
        "tentative-count",
        statistics.quality_counts.tentative
    );

    setText(
        "weak-count",
        statistics.quality_counts.weak
    );
}

async function loadTracks() {
    tableMessage.hidden = false;
    tableMessage.textContent = "Loading tracks…";

    const quality = document
        .getElementById("quality-filter")
        .value;

    const confidence = document
        .getElementById("confidence-filter")
        .value;

    const parameters = new URLSearchParams({
        minimum_confidence: confidence || "0",
        limit: "1000",
    });

    if (quality) {
        parameters.set("quality", quality);
    }

    const data = await requestJson(
        `/tracks?${parameters.toString()}`
    );

    renderTracks(data.tracks);
}

async function loadLatestRun() {
    const button = document.getElementById(
        "run-refresh-button"
    );

    button.disabled = true;
    button.textContent = "Loading…";

    runMessage.hidden = false;
    runMessage.textContent =
        "Loading latest pipeline run…";
    runContent.hidden = true;

    try {
        const manifest = await requestJson(
            "/runs/latest"
        );

        renderRun(manifest, true);
    } catch (error) {
        console.error(
            "Latest pipeline run could not be loaded:",
            error
        );

        runContent.hidden = true;
        runMessage.hidden = false;
        runMessage.textContent =
            `Latest pipeline run unavailable: ${error.message}`;
    } finally {
        button.disabled = false;
        button.textContent = "Show latest";
    }
}

async function loadArchivedRun(runId) {
    runMessage.hidden = false;
    runMessage.textContent =
        `Loading archived run ${runId}…`;
    runContent.hidden = true;

    try {
        const manifest = await requestJson(
            `/runs/${encodeURIComponent(runId)}`
        );

        renderRun(manifest, false);

        window.scrollTo({
            top: 0,
            behavior: "smooth",
        });
    } catch (error) {
        console.error(
            "Archived pipeline run could not be loaded:",
            error
        );

        runContent.hidden = true;
        runMessage.hidden = false;
        runMessage.textContent =
            `Archived run unavailable: ${error.message}`;
    }
}

async function loadRunHistory() {
    const button = document.getElementById(
        "history-refresh-button"
    );

    button.disabled = true;
    button.textContent = "Loading…";

    historyMessage.hidden = false;
    historyMessage.textContent =
        "Loading run history…";

    try {
        const data = await requestJson(
            "/runs?limit=100"
        );

        renderRunHistory(data.runs);
    } catch (error) {
        console.error(
            "Run history could not be loaded:",
            error
        );

        historyMessage.hidden = false;
        historyMessage.textContent =
            `Run history unavailable: ${error.message}`;
    } finally {
        button.disabled = false;
        button.textContent = "Reload history";
    }
}

async function refreshDashboard() {
    statusText.textContent = "Loading…";

    try {
        await loadHealth();
        await loadStatistics();
        await loadTracks();
    } catch (error) {
        console.error("Dashboard refresh failed:", error);

        statusText.textContent = "API unavailable";
        statusElement.classList.remove("healthy");

        tableMessage.hidden = false;
        tableMessage.textContent = error.message;
    }

    await loadLatestRun();
    await loadRunHistory();
}

function initializeDashboard() {
    const refreshButton =
        document.getElementById("refresh-button");

    const runRefreshButton =
        document.getElementById("run-refresh-button");

    const historyRefreshButton =
        document.getElementById(
            "history-refresh-button"
        );

    const qualityFilter =
        document.getElementById("quality-filter");

    const confidenceFilter =
        document.getElementById("confidence-filter");

    if (
        !statusElement ||
        !statusText ||
        !tableBody ||
        !tableMessage ||
        !runContent ||
        !runMessage ||
        !runPanelTitle ||
        !stageTableBody ||
        !historyTableBody ||
        !historyMessage ||
        !refreshButton ||
        !runRefreshButton ||
        !historyRefreshButton ||
        !qualityFilter ||
        !confidenceFilter
    ) {
        console.error(
            "Dashboard initialization failed: " +
            "one or more HTML elements are missing."
        );
        return;
    }

    refreshButton.addEventListener(
        "click",
        refreshDashboard
    );

    runRefreshButton.addEventListener(
        "click",
        loadLatestRun
    );

    historyRefreshButton.addEventListener(
        "click",
        loadRunHistory
    );

    qualityFilter.addEventListener(
        "change",
        loadTracks
    );

    confidenceFilter.addEventListener(
        "change",
        loadTracks
    );

    refreshDashboard();
}

window.addEventListener(
    "DOMContentLoaded",
    initializeDashboard
);
