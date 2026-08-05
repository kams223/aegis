"use strict";

const statusElement = document.getElementById("system-status");
const statusText = document.getElementById("status-text");
const tableBody = document.getElementById("track-table-body");
const tableMessage = document.getElementById("table-message");

function setText(id, value) {
    document.getElementById(id).textContent = String(value);
}

function createCell(value) {
    const cell = document.createElement("td");
    cell.textContent = String(value);
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
                `${Number(
                    track.duration_seconds
                ).toFixed(3)} s`
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
}

function initializeDashboard() {
    const refreshButton =
        document.getElementById("refresh-button");

    const qualityFilter =
        document.getElementById("quality-filter");

    const confidenceFilter =
        document.getElementById("confidence-filter");

    if (
        !statusElement ||
        !statusText ||
        !tableBody ||
        !tableMessage ||
        !refreshButton ||
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
