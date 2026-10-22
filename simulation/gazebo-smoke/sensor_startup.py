"""Bounded startup diagnostics and a control-only process, isolated from observers."""
from datetime import datetime, timezone
import json
import os
import threading
import time

from sensor_checks import SENSOR_CONFIG

WORLD = 'aegis_sensor_aircraft'
CONTROL = '/world/' + WORLD + '/control'
EXPECTED_TOPICS = {
    '/world/' + WORLD + '/stats': 'gz.msgs.WorldStatistics',
    '/aegis/aircraft/pose': 'gz.msgs.Pose_V',
    **{config['topic']: config['message'] for config in SENSOR_CONFIG.values()},
}


class StartupTrace:
    """Receipt timestamps are wall observations, separate from sensor sim time."""
    def __init__(self):
        self.lock = threading.Lock()
        self.events = {}

    def mark(self, name, **details):
        with self.lock:
            if name not in self.events:
                self.events[name] = dict(monotonic_ns=time.monotonic_ns(),
                                        utc=datetime.now(timezone.utc).isoformat(), **details)

    def snapshot(self):
        with self.lock:
            return {name: dict(value) for name, value in self.events.items()}

    def verified(self):
        required = {'first_advancing_clock', 'first_pose',
                    *('first_' + name for name in SENSOR_CONFIG)}
        with self.lock:
            return required <= self.events.keys()


def discover(node):
    """Discovery is necessary but never sufficient proof of running physics."""
    missing = []
    for topic, kind in EXPECTED_TOPICS.items():
        publishers, subscribers = node.topic_info(topic)
        if not any(p.msg_type_name == kind for p in publishers):
            missing.append('publisher:' + topic)
        if not any(p.msg_type_name == kind for p in subscribers):
            missing.append('observer:' + topic)
    if not any(p.req_type_name == 'gz.msgs.WorldControl' and p.rep_type_name == 'gz.msgs.Boolean'
               for p in node.service_info(CONTROL)):
        missing.append('service:' + CONTROL)
    return missing


def wait_discovery(node, emit, timeout=10):
    deadline = time.monotonic() + timeout
    while True:
        missing = discover(node)
        if not missing:
            emit('transport_discovered', topics=EXPECTED_TOPICS, service=CONTROL)
            return
        if time.monotonic() >= deadline:
            emit('discovery_timeout', missing=missing)
            raise ValueError('Bounded transport discovery timeout')
        time.sleep(0.02)  # Poll a condition; no fixed settling delay or request retry.


def control_main():
    """Exactly one request; this process has no Python subscription callbacks."""
    def emit(event, **details):
        print(json.dumps(dict(event=event, monotonic_ns=time.monotonic_ns(),
                              utc=datetime.now(timezone.utc).isoformat(), **details)), flush=True)
    try:
        if os.geteuid() != 10001 or not os.environ.get('GZ_PARTITION', '').startswith('aegis-smoke-'):
            raise ValueError('Control helper requires the isolated owned container')
        from gz.transport13 import Node
        from gz.msgs10.world_control_pb2 import WorldControl
        from gz.msgs10.boolean_pb2 import Boolean
        emit('controller_initialized')
        node = Node()
        wait_discovery(node, emit)
        emit('control_request_sent', service=CONTROL, pause=False, timeout_ms=3000, attempt=1)
        ok, response = node.request(CONTROL, WorldControl(pause=False), WorldControl, Boolean, 3000)
        emit('control_result', transport_result=bool(ok), response_data=bool(response.data),
             acknowledged=bool(ok and response.data))
        return 0 if ok and response.data else 2
    except Exception as error:
        emit('control_failure', error=str(error))
        return 2


def classify_startup(events, control, clocks):
    required = {'first_advancing_clock', 'first_pose', *('first_' + name for name in SENSOR_CONFIG)}
    if required <= events.keys():
        return 'observed_running' if control.get('acknowledged') else 'observed_running_unacknowledged'
    if 'first_advancing_clock' in events:
        return 'simulation_advanced_required_observations_missing'
    if control.get('transport_result') is True and control.get('response_data') is False:
        return 'control_rejected'
    if 'control_request_sent' not in events:
        return 'control_not_attempted_readiness_failed'
    if clocks and clocks[-1]['paused'] and clocks[-1]['time_ns'] == 0:
        return 'only_paused_observed_delivery_or_observer_state_unresolved'
    return 'control_or_observation_state_unresolved'


if __name__ == '__main__':
    raise SystemExit(control_main())
