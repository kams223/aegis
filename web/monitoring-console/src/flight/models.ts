// Frontend presentation only. No transport, command or monitoring schema changes.
export type Platform = 'PX4' | 'ArduPilot' | 'Simulation';
export type Environment = 'REAL' | 'SITL' | 'SYNTHETIC';
export type Availability<T> = Readonly<{ state: 'supplied'; value: T }> | Readonly<{ state: 'unavailable'; reason: string }>;
export interface Telemetry {
  readonly altitude: Availability<number>;
  readonly altitudeUnit: 'm';
  readonly groundSpeed: Availability<number>;
  readonly groundSpeedUnit: 'm/s';
  readonly battery: Availability<number>;
  readonly batteryUnit: '%';
  readonly flightMode: Availability<string>;
  readonly linkHealth: Availability<string>;
}
export interface VehiclePresentation {
  readonly vehicleId: string;
  readonly label: string;
  readonly platform: Platform;
  readonly environment: Environment;
  readonly connection: 'not_connected' | 'offline_demo' | 'unknown';
  readonly lastUpdate: Availability<string>;
  readonly telemetry: Telemetry;
  readonly camera: Readonly<{ cameraId: string | null; availability: 'unavailable' | 'unknown'; note: string }>;
  readonly provenance: Readonly<{ kind: 'synthetic_demo'; reference: string; note: string }>;
}
