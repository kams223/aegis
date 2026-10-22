"""Pure decoding and validation; fabricated unit fixtures never attest sensor operation."""
import math

SENSOR_CONFIG = {
    'imu': dict(topic='/aegis/sensors/imu', message='gz.msgs.IMU', rate_hz=100,
                frame='body FLU; sensor coincident and aligned at link origin',
                units={'acceleration':'m/s^2', 'angular_velocity':'rad/s', 'orientation':'unit quaternion xyzw'},
                interpretation='specific force R_world_to_sensor * (a_world - gravity); orientation relative to initial world alignment'),
    'gnss': dict(topic='/aegis/sensors/gnss', message='gz.msgs.NavSat', rate_hz=20,
                 frame='WGS84 latitude/longitude; elevation relative to spherical origin',
                 units={'latitude':'deg','longitude':'deg','altitude':'m'},
                 origin=dict(latitude_deg=0,longitude_deg=0,elevation_m=0,heading_deg=0,world='ENU')),
    'barometer': dict(topic='/aegis/sensors/barometer', message='gz.msgs.FluidPressure', rate_hz=50,
                     frame='scalar atmospheric pressure at sensor origin', units={'pressure':'Pa','derived_altitude':'m'},
                     model='Gazebo Sensors 8 standard lapse atmosphere with geopotential correction; P0=101325 Pa, T0=288.15 K, L=0.0065 K/m, g=9.80665, M=28.9644, R=8314.32, earth radius=6356766 m; zero altitude at world z=0, not geographic elevation'),
}


def decode_sensor(name, message):
    if not message.HasField('header') or not message.header.HasField('stamp'):
        raise ValueError('Missing sensor update timestamp')
    stamp=message.header.stamp
    if stamp.sec < 0 or not 0 <= stamp.nsec < 10**9:
        raise ValueError('Malformed timestamp')
    row=dict(time_ns=stamp.sec*10**9+stamp.nsec,
             header_frames=[v for d in message.header.data if d.key=='frame_id' for v in d.value])
    if name=='imu':
        for field in ('linear_acceleration','angular_velocity','orientation'):
            if not message.HasField(field): raise ValueError('Missing '+field)
        row.update(acceleration=[getattr(message.linear_acceleration,k) for k in 'xyz'],
                   angular_velocity=[getattr(message.angular_velocity,k) for k in 'xyz'],
                   orientation=[getattr(message.orientation,k) for k in 'xyzw'])
    elif name=='gnss':
        row.update(latitude=message.latitude_deg,longitude=message.longitude_deg,altitude=message.altitude,
                   message_frame=message.frame_id)
    elif name=='barometer': row.update(pressure=message.pressure,variance=message.variance)
    else: raise ValueError('Unknown sensor')
    return row


def pressure_altitude(pressure):
    if not math.isfinite(pressure) or pressure <= 0: raise ValueError('Invalid pressure')
    exponent=9.80665*28.9644/(8314.32*.0065)
    geopotential=288.15/.0065*(1-(pressure/101325)**(1/exponent))
    return 6356766*geopotential/(6356766-geopotential)


def world_to_sensor(vector, body_to_world):
    """Inverse quaternion rotation; sensor and body axes coincide in this model."""
    x, y, z, w = (-body_to_world[0], -body_to_world[1], -body_to_world[2], body_to_world[3])
    vx, vy, vz = vector
    tx, ty, tz = 2*(y*vz-z*vy), 2*(z*vx-x*vz), 2*(x*vy-y*vx)
    return [vx+w*tx+y*tz-z*ty, vy+w*ty+z*tx-x*tz, vz+w*tz+x*ty-y*tx]


def analyze_sensors(streams, poses):
    result=dict(passed=False,diagnostics=[],streams={},comparisons={})
    errors=result['diagnostics']
    if not isinstance(streams, dict):
        result['diagnostics'].append('Malformed sensor stream collection')
        return result
    try:
        if not isinstance(poses, list) or not poses:
            raise ValueError('Missing ground truth')
        previous = -1
        for pose in poses:
            if (type(pose['time_ns']) is not int or not previous < pose['time_ns'] <= 2*10**9
                    or pose['frame'] != 'aegis_sensor_aircraft'):
                raise ValueError('Invalid ground-truth timestamp/frame')
            previous = pose['time_ns']
            if any(type(pose[k]) not in (int, float) or not math.isfinite(pose[k])
                   for k in ('x','y','z','qx','qy','qz','qw')):
                raise ValueError('Invalid ground-truth pose')
            if abs(sum(pose[k]**2 for k in ('qx','qy','qz','qw'))-1) > 1e-5:
                raise ValueError('Invalid ground-truth quaternion')
    except (ValueError, KeyError, TypeError) as error:
        result['diagnostics'].append('ground_truth: ' + str(error))
        return result
    for name,cfg in SENSOR_CONFIG.items():
        rows=streams.get(name,[]); rate=cfg['rate_hz']; period=10**9/rate
        stats=dict(samples=len(rows) if isinstance(rows, list) else 0,expected_rate_hz=rate,first_time_ns=None,last_time_ns=None)
        result['streams'][name]=stats
        try:
            if not isinstance(rows, list) or not 2 <= len(rows) <= 512: raise ValueError('Missing or excessive samples')
            times=[r['time_ns'] for r in rows]
            if any(type(t) is not int or not 0<=t<=2*10**9 for t in times): raise ValueError('Invalid timestamp')
            gaps=[b-a for a,b in zip(times,times[1:])]
            if min(gaps)<=0: raise ValueError('Timestamp not strictly increasing')
            stats.update(first_time_ns=times[0],last_time_ns=times[-1],mean_rate_hz=(len(rows)-1)*1e9/(times[-1]-times[0]),
                         minimum_interval_ns=min(gaps),maximum_interval_ns=max(gaps))
            if times[0]>2*period or times[-1]<2e9-2*period: raise ValueError('Delayed startup or missing tail')
            if max(gaps)>1.5*period or min(gaps)<.5*period or not .9*rate<=stats['mean_rate_hz']<=1.1*rate:
                raise ValueError('Update rate/dropout outside tolerance')
            residuals=[]; orientations=[]; force_free=[]; force_late=[]; force_vector=[]; gyro=[]
            for row in rows:
                if name == 'imu' and [len(row[k]) for k in ('acceleration','angular_velocity','orientation')] != [3,3,4]:
                    raise ValueError('Invalid vector/quaternion shape')
                fields=(row['acceleration']+row['angular_velocity']+row['orientation'] if name=='imu' else
                        [row['latitude'],row['longitude'],row['altitude']] if name=='gnss' else [row['pressure'],row['variance']])
                if any(type(v) not in (int,float) or not math.isfinite(v) for v in fields): raise ValueError('Nonfinite/missing measurement')
                frames = [row.get('message_frame')] if name == 'gnss' else row['header_frames']
                if frames != ['passive_aircraft::body::'+name]:
                    raise ValueError('Unexpected sensor frame')
                if not poses: raise ValueError('Missing ground truth')
                pose=min(poses,key=lambda p:abs(p['time_ns']-row['time_ns']))
                if abs(pose['time_ns']-row['time_ns'])>11000000: raise ValueError('No nearby ground truth within 11 ms')
                if name=='gnss':
                    if not -90<=row['latitude']<=90 or not -180<=row['longitude']<=180: raise ValueError('Invalid geographic coordinate')
                    # WGS84 local tangent approximation, valid for this <1 m level drop.
                    residuals.append(max(abs(row['altitude']-pose['z']),abs(row['latitude']*math.pi/180*6335439-pose['y']),abs(row['longitude']*math.pi/180*6378137-pose['x'])))
                elif name=='barometer':
                    if row['variance'] < 0: raise ValueError('Invalid pressure variance')
                    residuals.append(abs(pressure_altitude(row['pressure'])-pose['z']))
                else:
                    q=row['orientation']; pq=[pose[k] for k in ('qx','qy','qz','qw')]
                    if abs(sum(v*v for v in q)-1)>1e-5: raise ValueError('Invalid quaternion')
                    orientations.append(min(math.sqrt(sum((a-b)**2 for a,b in zip(q,pq))),math.sqrt(sum((a+b)**2 for a,b in zip(q,pq)))))
                    if 50000000<=row['time_ns']<=300000000: force_free.append(math.sqrt(sum(v*v for v in row['acceleration'])))
                    if row['time_ns']>=1500000000:
                        force_late.append(abs(math.sqrt(sum(v*v for v in row['acceleration']))-9.81))
                        expected = world_to_sensor([0,0,9.81], pq)
                        force_vector.append(math.sqrt(sum((a-b)**2 for a,b in zip(row['acceleration'], expected))))
                        gyro.append(math.sqrt(sum(v*v for v in row['angular_velocity'])))
            if name=='imu':
                if not force_free or not force_late: raise ValueError('Missing free fall or settled IMU window')
                comparison=dict(free_fall_max_specific_force_m_s2=max(force_free),settled_max_force_magnitude_error_m_s2=max(force_late),
                                settled_max_specific_force_vector_error_m_s2=max(force_vector),settled_max_angular_speed_rad_s=max(gyro),max_orientation_quaternion_distance=max(orientations))
                result['comparisons'][name]=comparison
                if max(force_free)>.2 or max(force_late)>.3 or max(force_vector)>.3 or max(gyro)>.1 or max(orientations)>.02: raise ValueError('IMU comparison mismatch')
            else:
                result['comparisons'][name]=dict(max_position_residual_m=max(residuals),matching='nearest actual pose <=11 ms; no interpolation',tolerance_m=.05)
                if max(residuals)>.05: raise ValueError('Ground truth altitude/position mismatch')
        except (ValueError,KeyError,TypeError,OverflowError,AttributeError,IndexError,ZeroDivisionError) as error: errors.append(name+': '+str(error))
    result['passed']=not errors
    return result
