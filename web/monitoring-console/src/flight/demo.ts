import type { Availability, Environment, Platform, VehiclePresentation } from './models';

const missing = <T,>(reason: string): Availability<T> => Object.freeze({ state: 'unavailable', reason });
function demoSlot(vehicleId: string, label: string, platform: Platform, environment: Environment, cameraId: string | null): VehiclePresentation {
  return Object.freeze({
    vehicleId, label, platform, environment,
    connection: environment === 'SYNTHETIC' ? 'offline_demo' : 'not_connected',
    lastUpdate: missing<string>('No vehicle updates supplied'),
    telemetry: Object.freeze({
      altitude: missing<number>('No altitude supplied'), altitudeUnit: 'm',
      groundSpeed: missing<number>('No ground speed supplied'), groundSpeedUnit: 'm/s',
      battery: missing<number>('No battery value supplied'), batteryUnit: '%',
      flightMode: missing<string>('No flight mode supplied'),
      linkHealth: missing<string>('No link-health record supplied'),
    }),
    camera: Object.freeze({ cameraId, availability: 'unavailable', note: 'No approved video supplied; no hardware camera access.' }),
    provenance: Object.freeze({ kind: 'synthetic_demo', reference: 'flight-operations-demo-v1', note: 'Fictional interface demonstration slot. Platform and environment labels describe future integration categories only; no actual vehicle, simulator or telemetry source is connected.' }),
  });
}
// Entirely separate from the validated monitoring snapshot and radar demo markers.
export const DEMO_VEHICLES: readonly VehiclePresentation[] = Object.freeze([
  demoSlot('demo-px4-real-slot', 'PX4 real-vehicle integration slot', 'PX4', 'REAL', null),
  demoSlot('demo-ardupilot-real-slot', 'ArduPilot real-vehicle integration slot', 'ArduPilot', 'REAL', null),
  demoSlot('demo-px4-sitl-slot', 'PX4 SITL integration slot', 'PX4', 'SITL', null),
  demoSlot('demo-ardupilot-sitl-slot', 'ArduPilot SITL integration slot', 'ArduPilot', 'SITL', null),
  demoSlot('demo-synthetic-slot', 'Synthetic interface demonstration', 'Simulation', 'SYNTHETIC', 'demo-camera-placeholder'),
]);
