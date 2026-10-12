"""Focused presentation checks; existing contracts supply the mathematics."""

from dataclasses import asdict, replace
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

from aegis.fusion.contracts import MeasurementTime, ReferenceFrame, SensorObservation
from aegis.fusion.derived_evidence import DerivedSensorEvidence
from aegis.fusion.observation_history import ObservationHistory
from aegis.radar.contracts import RadarPolarDetectionMeasurement
from aegis.spatial.camera import ImagePoint
from aegis.spatial.transforms import RigidTransform
from aegis.fusion.derived_evidence import derive_camera_evidence


ROOT = Path(__file__).resolve().parents[1]
render = runpy.run_path(str(ROOT / "examples/synthetic_observation_inspector.py"))[
    "render_observation_history_html"]
scenario = runpy.run_path(str(ROOT / "examples/synthetic_observation_demo.py"))["_scenario"]
ABSENT = "Unavailable (not supplied)"


class Report(HTMLParser):
    """Read table cells and definition pairs without depending on whitespace."""

    def __init__(self, document):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.pairs = []
        self.tags = []
        self.attributes = []
        self.cell = None
        self.field = None
        self.row = None
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)
        if tag == "tr":
            self.row = []
        elif tag == "td":
            self.cell = []
        elif tag in ("dt", "dd"):
            self.field = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        if self.field is not None:
            self.field.append(data)

    def handle_endtag(self, tag):
        if tag == "td":
            self.row.append("".join(self.cell))
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
        elif tag == "dt":
            self.label = "".join(self.field)
            self.field = None
        elif tag == "dd":
            self.pairs.append((self.label, "".join(self.field)))
            self.field = None


def view(history, **kwargs):
    return render(history, scenario_label="Fixed fixture",
                  camera_observation_count=kwargs.pop("camera_observation_count", 1),
                  radar_observation_count=kwargs.pop("radar_observation_count", 1), **kwargs)


def test_fixture_metadata_geometry_and_provenance():
    history, _ = scenario()
    report = Report(view(history))
    radar_id = ('["radar-detection",1,"fixture:radar-sensor","fixture:session",'
                r'"[\"scripted-radar-detection\",1,\"0\",0]"]')
    assert [row[:9] for row in report.rows] == [
        ["0", "radar", "RadarPolarDetectionMeasurement", "fixture:radar-sensor",
         radar_id, ABSENT, "5.0", "fixture:radar", "fixture:radar:local"],
        ["1", "camera", "ImageTrackMeasurement", "fixture:camera-sensor",
         '["camera-track","fixture:camera-sensor","fixture:opening",51,7,0]',
         '["fixture:opening",7]', "2.0", "fixture:camera", "fixture:camera:image"],
    ]
    expected = {
        ("Camera source observations", "1"), ("Radar source observations", "1"),
        ("Total source observations", "2"), ("Evidence occurrences", "2"),
        ("History occurrences", "2"), ("Range (m)", "10.0"),
        ("Azimuth (rad)", "0.0"), ("Elevation (rad)", "0.0"),
        ("Radial range rate (m/s)", ABSENT),
        ("Bounding box xyxy (px)", "(10.0, 20.0, 30.0, 40.0)"),
        ("Class ID", "0"), ("Label", "fixture"),
        ("Detection confidence (backend)", "0.75"),
        ("Image dimensions (px)", "(640, 480)"),
        ("Point xyz (m)", "(10.0, 0.0, 0.0)"),
        ("Point xyz (m)", "(11.0, 2.0, 3.0)"),
        ("Direction xyz (dimensionless)", "(0.0, 0.0, 1.0)"),
        ("Geometry frame", "fixture:radar:local"),
        ("Geometry frame", "fixture:target"),
        ("Geometry frame", "fixture:camera:optical"),
        ("Interval (target s)", "(204.75, 205.25)"),
        ("Interval (target s)", "(101.75, 102.25)"),
        ("Target clock domain", "fixture:time"),
        ("Selected image point uv (px)", "(320.0, 240.0)"),
        ("Selected image point frame", "fixture:camera:image"),
        ("Calibration ID", "fixture:calibration"),
        ("Intrinsics fx/fy/cx/cy (px)", "(100.0, 100.0, 320.0, 240.0)"),
        ("Transform source frame", "fixture:radar:local"),
        ("Transform target frame", "fixture:target"),
        ("Translation target from source (m)", "(1.0, 2.0, 3.0)"),
        ("Mapping source clock", "fixture:radar"),
        ("Mapping source clock", "fixture:camera"),
        ("Mapping target clock", "fixture:time"),
        ("Mapping offset (target s)", "200.0"),
        ("Mapping offset (target s)", "100.0"),
        ("Mapping validity (source s)", "(0.0, 10.0)"),
        ("Mapping error bound (target s)", "0.25"),
        ("Camera calibration", "Not applicable"),
    }
    assert expected <= set(report.pairs)
    assert report.tags.count("details") == 2
    assert ("Source observation ID", radar_id) in report.pairs
    assert ("Source sensor ID", "fixture:camera-sensor") in report.pairs


def test_repeated_occurrences_retain_exact_caller_order():
    history, _ = scenario()
    radar, camera = history.records
    repeated = ObservationHistory((camera, radar, radar, camera))
    report = Report(view(repeated))
    assert [row[0:2] for row in report.rows] == [
        ["0", "camera"], ["1", "radar"], ["2", "radar"], ["3", "camera"]]
    assert [row[6] for row in report.rows] == ["2.0", "5.0", "5.0", "2.0"]
    assert report.rows[1][2:] == report.rows[2][2:]
    assert ("Evidence occurrences", "4") in report.pairs
    assert ("History occurrences", "4") in report.pairs
    assert ("Total source observations", "2") in report.pairs


def test_missing_optionals_and_measured_zero():
    source = SensorObservation("observation", "sensor", MeasurementTime(0.0, "clock"),
                               ReferenceFrame("radar:local"),
                               RadarPolarDetectionMeasurement(0.0, 0.0))
    report = Report(view(ObservationHistory((DerivedSensorEvidence(source),)),
                         camera_observation_count=0))
    row = report.rows[0]
    assert row[5] == ABSENT and row[6] == "0.0"
    for label in ("Elevation (rad)", "Radial range rate (m/s)", "Geometry", "Geometry frame",
                  "Interval (target s)", "Target clock domain", "Transform source frame",
                  "Mapping source clock", "Projection source"):
        assert (label, ABSENT) in report.pairs
    assert ("Range (m)", "0.0") in report.pairs
    assert ("Azimuth (rad)", "0.0") in report.pairs
    history, _ = scenario()
    camera = DerivedSensorEvidence(history.records[1].source_observation)
    camera_report = Report(view(ObservationHistory((camera,)), radar_observation_count=0))
    assert ("Calibration ID", ABSENT) in camera_report.pairs
    assert ("Selected image point uv (px)", ABSENT) in camera_report.pairs


def test_image_point_and_stored_rotated_direction():
    frame = ReferenceFrame("image")
    point = ImagePoint(0.0, 0.0, 640, 480, frame)
    history, _ = scenario()
    intrinsics = replace(history.records[1].camera_intrinsics, image_frame=frame)
    source = SensorObservation("point", "camera", MeasurementTime(0.0, "clock"), frame, point)
    transform = RigidTransform(intrinsics.optical_frame, ReferenceFrame("rotated"),
                              ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                              (0.0, 0.0, 0.0))
    evidence = derive_camera_evidence(source, image_point=point, intrinsics=intrinsics,
                                      spatial_transform=transform)
    report = Report(view(ObservationHistory((evidence,)), radar_observation_count=0))
    assert report.rows[0][2] == "ImagePoint"
    assert ("Image point uv (px)", "(0.0, 0.0)") in report.pairs
    assert "rotated" in report.rows[0][11]


def test_untrusted_text_is_escaped_everywhere():
    text = '<script src="https://invalid.example/">& \'quoted\' Ω</script>'
    frame = ReferenceFrame(text)
    source = SensorObservation(text, text, MeasurementTime(0.0, text), frame,
                               ImagePoint(0.0, 0.0, 1, 1, frame), text)
    document = render(ObservationHistory((DerivedSensorEvidence(source),)),
                      scenario_label=text, camera_observation_count=1, radar_observation_count=0)
    assert escape(text, quote=True) in document
    report = Report(document)
    assert report.rows[0][3:6] == [text, text, text]
    assert report.rows[0][7:9] == [text, text]
    assert ("Scenario", text) in report.pairs
    assert "script" not in report.tags
    assert not any(name in ("src", "href", "id") for name, _ in report.attributes)
    history, _ = scenario()
    camera = history.records[1].source_observation
    changed = replace(camera, measurement=replace(camera.measurement, label=text))
    assert ("Label", text) in Report(view(ObservationHistory((DerivedSensorEvidence(changed),)))).pairs


def test_rendering_preserves_values_and_all_provenance_references():
    history, _ = scenario()
    before = asdict(history)
    records = history.records
    references = [(e.source_observation, e.source_observation.measurement,
                   e.source_observation.measurement_time, e.spatial_projection,
                   e.camera_intrinsics, e.spatial_transform, e.transformed_geometry,
                   e.mapped_time) for e in records]
    assert view(history) == view(history)
    assert asdict(history) == before and history.records is records
    for evidence, original in zip(history.records, references, strict=True):
        current = (evidence.source_observation, evidence.source_observation.measurement,
                   evidence.source_observation.measurement_time, evidence.spatial_projection,
                   evidence.camera_intrinsics, evidence.spatial_transform,
                   evidence.transformed_geometry, evidence.mapped_time)
        assert all(left is right for left, right in zip(current, original, strict=True))
    radar, camera = records
    assert radar.spatial_projection.source_measurement is radar.source_observation.measurement
    assert radar.transformed_geometry.source_point is radar.spatial_projection
    assert camera.spatial_projection.source_image_point is references[1][3].source_image_point
    for evidence in records:
        assert evidence.mapped_time.source_time is evidence.source_observation.measurement_time


def command(*args, optimized=False):
    bootstrap = ("import runpy, sys; src, examples, script = sys.argv[1:4]; "
                 "sys.path[:0] = [src, examples]; sys.argv = [script] + sys.argv[4:]; "
                 "runpy.run_path(script, run_name='__main__')")
    return [sys.executable, "-I", "-S", "-B", *(["-O"] if optimized else []),
            "-c", bootstrap, str(ROOT / "src"), str(ROOT / "examples"),
            str(ROOT / "examples/synthetic_observation_demo.py"), *args]


def test_independent_offline_html_execution(tmp_path):
    runs = [subprocess.run(command("--html"), cwd=tmp_path, env={}, capture_output=True,
                           check=True, timeout=30) for _ in range(2)]
    assert runs[0].stdout == runs[1].stdout
    assert runs[0].stderr == runs[1].stderr == b""
    document = runs[0].stdout.decode("utf-8")
    assert document.startswith("<!DOCTYPE html>\n")
    assert document.endswith("</body></html>\n")
    assert "DETERMINISTIC SYNTHETIC DEMO: PASS" not in document
    report = Report(document)
    assert ("charset", "utf-8") in report.attributes
    assert not set(report.tags) & {"script", "link", "img", "iframe", "object", "embed"}
    assert not any(name in ("src", "href") or name.startswith("on")
                   for name, _ in report.attributes)
    assert len(report.rows) == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("args,optimized,fragment", [
    (("--unknown",), False, b"unrecognized arguments"),
    (("--ht",), False, b"unrecognized arguments"),
    (("--html",), True, b"Run without -O"),
])
def test_cli_rejection_before_output(tmp_path, args, optimized, fragment):
    result = subprocess.run(command(*args, optimized=optimized), cwd=tmp_path, env={},
                            capture_output=True, timeout=30)
    assert result.returncode != 0 and result.stdout == b""
    assert fragment in result.stderr


def test_validation_failure_emits_no_partial_html(tmp_path):
    bootstrap = ("import runpy, sys; sys.path[:0] = sys.argv[1:3]; "
                 "namespace = runpy.run_path(sys.argv[3]); sys.argv = ['demo', '--html']; "
                 "namespace['main'].__globals__['_scenario'] = lambda: (_ for _ in ()).throw(AssertionError()); "
                 "namespace['main']()")
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", bootstrap,
                             str(ROOT / "src"), str(ROOT / "examples"),
                             str(ROOT / "examples/synthetic_observation_demo.py")],
                            cwd=tmp_path, env={}, capture_output=True, timeout=30)
    assert result.returncode != 0 and result.stdout == b""
    assert b"AssertionError" in result.stderr


@pytest.mark.parametrize("override,error", [
    ({"history": ()}, TypeError), ({"scenario_label": 1}, TypeError),
    ({"scenario_label": " "}, ValueError), ({"camera_observation_count": True}, TypeError),
    ({"radar_observation_count": 1.0}, TypeError), ({"radar_observation_count": -1}, ValueError),
    ({"radar_observation_count": 0}, ValueError),
])
def test_invalid_renderer_arguments(override, error):
    history, _ = scenario()
    arguments = dict(history=history, scenario_label="fixture",
                     camera_observation_count=1, radar_observation_count=1)
    arguments.update(override)
    with pytest.raises(error):
        render(**arguments)


def test_unsupported_measurement_is_rejected():
    # Deliberately malformed evidence bypasses contract construction so the
    # renderer's own unsupported-type boundary can be exercised independently.
    source = SensorObservation("id", "sensor", MeasurementTime(0.0, "clock"),
                               ReferenceFrame("frame"), object())
    evidence = object.__new__(DerivedSensorEvidence)
    object.__setattr__(evidence, "source_observation", source)
    with pytest.raises(TypeError, match="unsupported observation measurement type"):
        view(ObservationHistory((evidence,)))


def test_empty_history_accepts_zero_counts():
    report = Report(view(ObservationHistory(()), camera_observation_count=0,
                         radar_observation_count=0))
    assert report.rows == []
    assert ("History occurrences", "0") in report.pairs
