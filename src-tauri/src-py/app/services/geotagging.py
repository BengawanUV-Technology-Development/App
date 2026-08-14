import math

def build_intrinsic_matrix(width: int, height: int, focal_length_mm: float, sensor_width_mm: float):
    fx = focal_length_mm * (width / sensor_width_mm)
    fy = fx
    cx = width / 2.0
    cy = height / 2.0
    
    return [
        [fx, 0.0, cx],
        [0.0, fy, cy],
        [0.0, 0.0, 1.0]
    ]

def invert_matrix_3x3(m):
    det = m[0][0]*(m[1][1]*m[2][2] - m[2][1]*m[1][2]) - \
          m[0][1]*(m[1][0]*m[2][2] - m[1][2]*m[2][0]) + \
          m[0][2]*(m[1][0]*m[2][1] - m[1][1]*m[2][0])
    
    if det == 0:
        return None
        
    invdet = 1.0 / det
    minv = [
        [(m[1][1]*m[2][2] - m[2][1]*m[1][2]) * invdet,
         (m[0][2]*m[2][1] - m[0][1]*m[2][2]) * invdet,
         (m[0][1]*m[1][2] - m[0][2]*m[1][1]) * invdet],
        [(m[1][2]*m[2][0] - m[1][0]*m[2][2]) * invdet,
         (m[0][0]*m[2][2] - m[0][2]*m[2][0]) * invdet,
         (m[1][0]*m[0][2] - m[0][0]*m[1][2]) * invdet],
        [(m[1][0]*m[2][1] - m[2][0]*m[1][1]) * invdet,
         (m[2][0]*m[0][1] - m[0][0]*m[2][1]) * invdet,
         (m[0][0]*m[1][1] - m[1][0]*m[0][1]) * invdet]
    ]
    return minv

def mat_mul_3x3(A, B):
    result = [[0,0,0], [0,0,0], [0,0,0]]
    for i in range(3):
        for j in range(3):
            for k in range(3):
                result[i][j] += A[i][k] * B[k][j]
    return result

def mat_vec_mul_3x3(A, v):
    return [
        A[0][0]*v[0] + A[0][1]*v[1] + A[0][2]*v[2],
        A[1][0]*v[0] + A[1][1]*v[1] + A[1][2]*v[2],
        A[2][0]*v[0] + A[2][1]*v[1] + A[2][2]*v[2]
    ]

def get_rotation_matrix(roll_deg: float, pitch_deg: float, yaw_deg: float):
    r = math.radians(roll_deg)
    p = math.radians(pitch_deg)
    y = math.radians(yaw_deg)
    
    Rx = [
        [1.0, 0.0, 0.0],
        [0.0, math.cos(r), -math.sin(r)],
        [0.0, math.sin(r), math.cos(r)]
    ]
    
    Ry = [
        [math.cos(p), 0.0, math.sin(p)],
        [0.0, 1.0, 0.0],
        [-math.sin(p), 0.0, math.cos(p)]
    ]
    
    Rz = [
        [math.cos(y), -math.sin(y), 0.0],
        [math.sin(y), math.cos(y), 0.0],
        [0.0, 0.0, 1.0]
    ]
    
    # R = Rx @ Ry @ Rz
    R_xy = mat_mul_3x3(Rx, Ry)
    return mat_mul_3x3(R_xy, Rz)

def unproject_pixel_to_ray(u: float, v: float, R_world, K_inv):
    vec = [u, v, 1.0]
    d_cam_cv = mat_vec_mul_3x3(K_inv, vec)
    d_cam_blender = [d_cam_cv[0], -d_cam_cv[1], -d_cam_cv[2]]
    d_world = mat_vec_mul_3x3(R_world, d_cam_blender)
    
    norm = math.sqrt(d_world[0]**2 + d_world[1]**2 + d_world[2]**2)
    if norm == 0:
        return [0, 0, 0]
    return [d_world[0]/norm, d_world[1]/norm, d_world[2]/norm]

def ray_ground_intersection(P_cam, v_ray, z_ground=0.0):
    if abs(v_ray[2]) < 1e-6:
        return None
    t = (z_ground - P_cam[2]) / v_ray[2]
    if t <= 0:
        return None
    return [
        P_cam[0] + t * v_ray[0],
        P_cam[1] + t * v_ray[1]
    ]

def estimate_target_gps(
    u_c: float, v_c: float, 
    image_width: int, image_height: int,
    drone_lat: float, drone_lng: float, drone_alt_m: float,
    roll_deg: float, pitch_deg: float, yaw_deg: float,
    focal_length_mm: float = 6.0, sensor_width_mm: float = 6.287
):
    """
    Estimates the GPS coordinates of a target in an image based on telemetry.
    Returns (target_lat, target_lng) or None if target is above the horizon.
    """
    K = build_intrinsic_matrix(image_width, image_height, focal_length_mm, sensor_width_mm)
    K_inv = invert_matrix_3x3(K)
    if not K_inv:
        return None
        
    R_world = get_rotation_matrix(roll_deg, pitch_deg, yaw_deg)
    v_ray = unproject_pixel_to_ray(u_c, v_c, R_world, K_inv)
    
    P_cam = [0.0, 0.0, drone_alt_m]
    xy_meters = ray_ground_intersection(P_cam, v_ray, 0.0)
    
    if xy_meters is None:
        return None
        
    x_meters, y_meters = xy_meters
    
    # 1 degree lat = ~111.32 km
    # x is East, y is North
    lat_offset = (y_meters / 111320.0)
    lng_offset = (x_meters / (111320.0 * math.cos(math.radians(drone_lat))))
    
    target_lat = drone_lat + lat_offset
    target_lng = drone_lng + lng_offset
    
    return target_lat, target_lng
