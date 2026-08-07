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

    const runStatus = document.getElementById("run-status");

    runStatus.className =
        `run-value run-status ${manifest.status || ""}`;

    setText(
        "run-fingerprint",
        `SHA-256: ${input.sha256 || "Unavailable"}`
    );

    renderStages(stages);

    runMessage.hidden = true;
    runContent.hidden = false;
}

function renderRunHistory(runs) {
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
