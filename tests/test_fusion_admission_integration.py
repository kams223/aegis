"""Existing adapters remain unchanged while SF-1 supplies a stricter consumer."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import pytest

from aegis.core.frames import FrameMetadata
from aegis.perception.contracts import ObjectDetection
from aegis.tracking.contracts import TrackedObject, TrackedObjectBatch
from aegis.fusion.camera_adapter import tracked_objects_to_observations
from aegis.fusion.derived_evidence import derive_camera_evidence, derive_radar_evidence
from aegis.fusion.contracts import SensorObservation, MeasurementTime
from aegis.radar.adapter import radar_detections_to_observations
from aegis.radar.contracts import RadarDetection, RadarPolarDetectionMeasurement
from aegis.fusion.uncertainty import CovarianceDeclaration, MeasurementBasis
from aegis.fusion.admission import admit_batch, AdmissionLedger
from test_fusion_admission import make_request, run


def with_basis(obs, quantity, axes, units):
    r = make_request()
    b = MeasurementBasis('image_bbox' if quantity == 'image_extent' else 'radar_polar', axes, units, obs.reference_frame)
    matrix = tuple(tuple(float(i == j) for j in range(len(axes))) for i in range(len(axes)))
    return replace(r, observation=obs, quantity=quantity, basis=b, uncertainty=CovarianceDeclaration(matrix, b, r.uncertainty.uncertainty_provenance))


def test_camera_adapter_box_is_not_implicitly_a_point_or_confidence_covariance():
    tracked = TrackedObjectBatch(FrameMetadata('opening-a', 1, 10., 640, 480),
        (TrackedObject(7, ObjectDetection(0, 'object', 1.5, 10.25, 20.5, 30.75, 40.5)),))
    obs = tracked_objects_to_observations(tracked, sensor_id='camera', clock_domain='video:a', reference_frame_id='camera:image').observations[0]
    r = with_basis(obs, 'image_extent', ('x1', 'y1', 'x2', 'y2'), ('px',)*4)
    r = replace(r, derivation=derive_camera_evidence(obs))
    result = run(r).results[0]
    assert result.status == 'admitted'
    a = result.admitted_measurement
    assert a.source_observation is obs and a.derivation is r.derivation
    assert a.values == (10.25, 20.5, 30.75, 40.5)
    assert a.uncertainty.matrix == r.uncertainty.matrix
    assert a.source_observation.measurement.confidence == 1.5
    assert run(replace(r, uncertainty=None)).results[0].status == 'rejected'
    invalid = replace(obs, measurement=replace(obs.measurement, x2=0.))
    assert run(replace(r, observation=invalid, derivation=None)).results[0].diagnostics[0].code == 'IMAGE_BOX'


@pytest.mark.parametrize('elevation,rate,axes,units,values', [
    (None, None, ('range_m','azimuth_rad'), ('m','rad'), (10.,0.)),
    (0., None, ('range_m','azimuth_rad','elevation_rad'), ('m','rad','rad'), (10.,0.,0.)),
    (None, -2., ('range_m','azimuth_rad','radial_velocity_mps'), ('m','rad','m/s'), (10.,0.,-2.)),
    (0., 0., ('range_m','azimuth_rad','elevation_rad','radial_velocity_mps'), ('m','rad','rad','m/s'), (10.,0.,0.,0.)),
])
def test_radar_adapter_exact_optional_component_dimensions(elevation, rate, axes, units, values):
    measurement = RadarPolarDetectionMeasurement(10., 0., elevation, rate)
    detection = RadarDetection('radar-run', 'event-r', MeasurementTime(10., 'video:a'), measurement)
    obs = radar_detections_to_observations((detection,), sensor_id='radar', reference_frame_id='radar:local').observations[0]
    r = with_basis(obs, 'radar_polar', axes, units)
    r = replace(r, source_session_id='radar-run', derivation=derive_radar_evidence(obs))
    a = run(r).results[0].admitted_measurement
    assert a is not None and a.values == values
    assert a.source_observation.measurement is measurement
    if elevation is None:
        assert a.derivation.spatial_projection is None
    duplicate = admit_batch((r, replace(r)), AdmissionLedger.empty())
    assert [x.status for x in duplicate.results] == ['admitted', 'duplicate']


def test_native_aircraft_telemetry_is_not_external_object_evidence():
    from aegis.simulation.sensor_telemetry import SensorTelemetry
    from aegis.simulation.contracts import load_contract
    from aegis.simulation.sensor_realism import encode
    doc = json.loads((Path(__file__).parents[1] / 'examples/sensor_telemetry_example.json').read_text())
    record = load_contract(SensorTelemetry, encode(doc['observations'][0]['record']))
    r = make_request(observation=record)
    assert run(r).results[0].diagnostics[0].code == 'OBSERVATION_TYPE'
    obs = make_request().observation
    assert run(replace(r, observation=replace(obs, measurement=record))).results[0].diagnostics[0].code == 'UNSUPPORTED_MEASUREMENT_TYPE'


def test_mixed_existing_adapters_replay_deterministically_without_mutation():
    camera = make_request()
    m = RadarPolarDetectionMeasurement(0., 0.)
    obs = radar_detections_to_observations((RadarDetection('r', 'event', MeasurementTime(10., 'video:a'), m),), sensor_id='r', reference_frame_id='r:local').observations[0]
    radar = with_basis(obs, 'radar_polar', ('range_m','azimuth_rad'), ('m','rad'))
    requests = (radar, camera, camera)
    before = repr(requests)
    results = [admit_batch(requests, AdmissionLedger.empty()) for _ in range(3)]
    assert results[0] == results[1] == results[2]
    assert [r.status for r in results[0].results] == ['admitted','admitted','duplicate']
    assert repr(requests) == before
    assert results[0].results[0].admitted_measurement.values == (0.,0.)


def test_isolated_standard_library_operation_reads_no_clock_or_io():
    script = '''
import sys, time, importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in {'numpy','scipy','torch','cv2','ultralytics'}: raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
from aegis.fusion.admission import *
from aegis.fusion.uncertainty import *
from aegis.fusion.contracts import *
from aegis.spatial.camera import ImagePoint
frame=ReferenceFrame('image')
obs=SensorObservation('o','s',MeasurementTime(0.,'clock'),frame,ImagePoint(1.,2.,10,10,frame))
basis=MeasurementBasis('image_point',('u_px','v_px'),('px','px'),frame)
request=AdmissionRequest(obs,'source','external_object','image_location',basis,CovarianceDeclaration(((1.,0.),(0.,1.)),basis,UncertaintyProvenance('model','1','synthetic_model')),CorrelationClaim.unknown(),MeasurementTime(1.,'clock'),MeasurementTime(0.,'clock'),2.)
def forbidden(*a,**k): raise AssertionError('implicit clock')
time.time=time.monotonic=time.perf_counter=forbidden
def audit(event,args):
 if event=='open' or event.startswith(('socket.','subprocess.')) or event=='os.system': raise AssertionError(event)
sys.addaudithook(audit)
result=admit_batch((request,request),AdmissionLedger.empty())
assert [x.status for x in result.results]==['admitted','duplicate']
assert validate_covariance(request.uncertainty,basis).covariance.rank==2
'''
    result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
