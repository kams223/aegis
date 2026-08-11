const runSelect = document.getElementById("run-select");
const loadRunButton = document.getElementById(
    "load-run-button"
);
const applyFiltersButton = document.getElementById(
    "apply-filters-button"
);

const previousPageButton = document.getElementById(
    "previous-page-button"
);
const nextPageButton = document.getElementById(
    "next-page-button"
);

let currentOffset = 0;

function setText(id, value) {
    document.getElementById(id).textContent = value;
}

function formatNumber(value, digits = 2) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return number.toFixed(digits);
}

async function requestJson(path) {
    const response = await fetch(path, {
        headers: {
            "Accept": "application/json",
        },
    });

    if (!response.ok) {
        let detail = (
            `Request failed with HTTP ${response.status}`
        );

        try {
            const body = await response.json();
            detail = body.detail || detail;
        } catch {
            // Retain the HTTP status message.
        }

        throw new Error(detail);
    }

    return response.json();
}

function formatRunOption(run) {
    const timestamp = new Date(run.finished_at_utc);

    const finished = Number.isNaN(timestamp.getTime())
        ? "unknown time"
        : timestamp.toLocaleString();

    return (
        `${finished} — ${run.status} — ${run.run_id}`
    );
}

function renderStatistics(statistics) {
    setText(
        "total-tracks",
        statistics.total_tracks
    );

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

    document.getElementById(
        "statistics-panel"
    ).hidden = false;
}

function createCell(value) {
    const cell = document.createElement("td");
    cell.textContent = value;
    return cell;
}

function createQualityCell(level) {
    const cell = document.createElement("td");
    const badge = document.createElement("span");

    badge.className = `quality ${level}`;
    badge.textContent = level;

    cell.append(badge);
    return cell;
}

function renderTracks(data) {
    const tableBody = document.getElementById(
        "track-table-body"
    );

    tableBody.replaceChildren();

    for (const track of data.tracks) {
        const row = document.createElement("tr");

        row.append(
            createCell(track.track_id),
            createCell(track.dominant_label),
            createQualityCell(track.quality_level),
            createCell(
                formatNumber(
                    track.average_confidence,
                    4
                )
            ),
            createCell(track.observation_count),
            createCell(
                `${formatNumber(
                    track.duration_seconds,
                    2
                )} s`
            ),
            createCell(
                `${formatNumber(
                    track.displacement_pixels,
                    1
                )} px`
            )
        );

        row.addEventListener(
            "click",
            () => loadTrackDetails(track.track_id)
        );

        tableBody.append(row);
    }

        currentOffset = data.offset;

    const firstResult = (
        data.total_matching === 0
            ? 0
            : data.offset + 1
    );

    const lastResult = (
        data.offset + data.returned
    );

    const pageNumber = (
        Math.floor(data.offset / data.limit) + 1
    );

    const pageCount = Math.max(
        1,
        Math.ceil(data.total_matching / data.limit)
    );

    setText(
        "tracks-message",
        (
            `${data.total_matching} matching tracks; ` +
            `showing ${firstResult}–${lastResult}. ` +
            "Select a row for details."
        )
    );

    setText(
        "page-message",
        `Page ${pageNumber} of ${pageCount}`
    );

    previousPageButton.disabled = (
        !data.has_previous
    );

    nextPageButton.disabled = (
        !data.has_next
    );

    document.getElementById(
        "tracks-panel"
    ).hidden = false;
}

function createDetailCard(label, value) {
    const card = document.createElement("article");
    card.className = "detail-card";

    const labelElement = document.createElement("div");
    labelElement.className = "detail-label";
    labelElement.textContent = label;

    const valueElement = document.createElement("div");
    valueElement.className = "detail-value";
    valueElement.textContent = value;

    card.append(
        labelElement,
        valueElement
    );

    return card;
}

function positionText(position) {
    if (
        position === null
        || typeof position !== "object"
    ) {
        return "—";
    }

    return (
        `${formatNumber(position.x, 1)}, ` +
        `${formatNumber(position.y, 1)}`
    );
}

async function loadTrackDetails(trackId) {
    const runId = runSelect.value;

    try {
        const track = await requestJson(
            (
                `/runs/${encodeURIComponent(runId)}` +
                `/tracks/${trackId}`
            )
        );

        const details = document.getElementById(
            "track-details"
        );

        details.replaceChildren(
            createDetailCard(
                "Track ID",
                track.track_id
            ),
            createDetailCard(
                "Predicted label",
                track.dominant_label
            ),
            createDetailCard(
                "Quality",
                track.quality_level
            ),
            createDetailCard(
                "Reason",
                track.quality_reason
            ),
            createDetailCard(
                "Observations",
                track.observation_count
            ),
            createDetailCard(
                "Average confidence",
                formatNumber(
                    track.average_confidence,
                    4
                )
            ),
            createDetailCard(
                "Duration",
                (
                    `${formatNumber(
                        track.duration_seconds,
                        2
                    )} seconds`
                )
            ),
            createDetailCard(
                "Displacement",
                (
                    `${formatNumber(
                        track.displacement_pixels,
                        1
                    )} pixels`
                )
            ),
            createDetailCard(
                "Frame range",
                (
                    `${track.first_frame}–` +
                    `${track.last_frame}`
                )
            ),
            createDetailCard(
                "Start position",
                positionText(track.start_position)
            ),
            createDetailCard(
                "End position",
                positionText(track.end_position)
            )
        );

        document.getElementById(
            "details-panel"
        ).hidden = false;
    } catch (error) {
        setText(
            "tracks-message",
            error.message
        );
    }
}

function buildTrackQuery() {
    const parameters = new URLSearchParams({
        minimum_confidence: document.getElementById(
            "confidence-filter"
        ).value,
        limit: document.getElementById(
            "track-limit"
        ).value,
        offset: currentOffset,
    });

    const quality = document.getElementById(
        "quality-filter"
    ).value;

    const dominantLabel = document.getElementById(
        "label-filter"
    ).value.trim();

    if (quality) {
        parameters.set("quality", quality);
    }

    if (dominantLabel) {
        parameters.set(
            "dominant_label",
            dominantLabel
        );
    }

    return parameters.toString();
}

async function loadTracks() {
    const runId = runSelect.value;

    const data = await requestJson(
        (
            `/runs/${encodeURIComponent(runId)}` +
            `/tracks?${buildTrackQuery()}`
        )
    );

    renderTracks(data);
}

async function loadSelectedRun() {
    const runId = runSelect.value;

    if (!runId) {
        return;
    }
    currentOffset = 0;
    loadRunButton.disabled = true;
    applyFiltersButton.disabled = true;

    setText(
        "run-message",
        `Loading run ${runId}…`
    );

    document.getElementById(
        "details-panel"
    ).hidden = true;

    try {
        const statistics = await requestJson(
            (
                `/runs/${encodeURIComponent(runId)}` +
                "/statistics"
            )
        );

        renderStatistics(statistics);
        await loadTracks();

        setText(
            "run-message",
            `Loaded archived run ${runId}.`
        );
    } catch (error) {
        setText(
            "run-message",
            error.message
        );
    } finally {
        loadRunButton.disabled = false;
        applyFiltersButton.disabled = false;
    }
}

async function loadRuns() {
    try {
        const data = await requestJson(
            "/runs?limit=500"
        );

        runSelect.replaceChildren();

        for (const run of data.runs) {
            const option = document.createElement(
                "option"
            );

            option.value = run.run_id;
            option.textContent = formatRunOption(run);

            runSelect.append(option);
        }

        if (data.runs.length === 0) {
            const option = document.createElement(
                "option"
            );

            option.value = "";
            option.textContent = (
                "No archived runs available"
            );

            runSelect.append(option);

            setText(
                "run-message",
                "No archived runs are available."
            );

            return;
        }

        loadRunButton.disabled = false;
        await loadSelectedRun();
    } catch (error) {
        runSelect.replaceChildren();

        setText(
            "run-message",
            error.message
        );
    }
}

loadRunButton.addEventListener(
    "click",
    loadSelectedRun
);

applyFiltersButton.addEventListener(
    "click",
    async () => {
        currentOffset = 0;
        applyFiltersButton.disabled = true;

        try {
            await loadTracks();
        } catch (error) {
            setText(
                "tracks-message",
                error.message
            );
        } finally {
            applyFiltersButton.disabled = false;
        }
    }
);

previousPageButton.addEventListener(
    "click",
    async () => {
        const limit = Number(
            document.getElementById(
                "track-limit"
            ).value
        );

        currentOffset = Math.max(
            0,
            currentOffset - limit
        );

        await loadTracks();
    }
);

nextPageButton.addEventListener(
    "click",
    async () => {
        const limit = Number(
            document.getElementById(
                "track-limit"
            ).value
        );

        currentOffset += limit;
        await loadTracks();
    }
);

loadRuns();
