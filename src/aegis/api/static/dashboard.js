"use strict";

const statusElement = document.getElementById("system-status");
const statusText = document.getElementById("status-text");

const tableBody = document.getElementById("track-table-body");
const tableMessage = document.getElementById("table-message");

const runContent = document.getElementById("run-content");
const runMessage = document.getElementById("run-message");
const stageTableBody = document.getElementById(
    "stage-table-body"
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

        const qualityCell = document.createElement("td");
        const qualityBadge = document.createElement("span");

        qualityBadge.className =
            `badge ${track.quality_level}`;
        qualityBadge.textContent = track.quality_level;

        qualityCell.appendChild(qualityBadge);
        row.appendChild(qualityCell);

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

        const statusCell = document.createElement("td");
        const statusBadge = document.createElement("span");

        statusBadge.className =
            `badge ${stage.status}`;
        statusBadge.textContent = stage.status;

        statusCell.appendChild(statusBadge);
        row.appendChild(statusCell);

        row.appendChild(
            createCell(
                formatDuration(stage.duration_seconds)
            )
        );

        row.appendChild(createCell(stage.exit_code));

        stageTableBody.appendChild(row);
    }
}

function renderRun(manifest) {
    const model = manifest.model || {};
    const input = manifest.input || {};
    const stages = Array.isArray(manifest.stages)
        ? manifest.stages
        : [];

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
    runMessage.hidden = false;
    runMessage.textContent =
        "Loading latest pipeline run…";
    runContent.hidden = true;

    try {
        const manifest = await requestJson(
            "/runs/latest"
        );

        renderRun(manifest);
    } catch (error) {
        console.error(
            "Latest pipeline run could not be loaded:",
            error
        );

        runContent.hidden = true;
        runMessage.hidden = false;
        runMessage.textContent =
            `Latest pipeline run unavailable: ${error.message}`;
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
}

function initializeDashboard() {
    const refreshButton =
        document.getElementById("refresh-button");

    const runRefreshButton =
        document.getElementById("run-refresh-button");

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
        !stageTableBody ||
        !refreshButton ||
        !runRefreshButton ||
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
