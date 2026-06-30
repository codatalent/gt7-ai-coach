import csv

CORNERS = {
    'T2':               {'pos': (-384.5, 68.2),   'radius': 40},
    'T4':               {'pos': (-323.3, 27.7),   'radius': 40},
    'T5':               {'pos': (-58.2, 338.0),   'radius': 40},
    'T6':               {'pos': (243.9, 450.8),   'radius': 40},
    'T8_Corkscrew':     {'pos': (385.9, 67.5),    'radius': 40},
    'T9_Corkscrew_exit':{'pos': (404.6, -43.6),   'radius': 40},
    'T10':              {'pos': (353.4, -231.5),  'radius': 40},
    'T11_Rainey':       {'pos': (155.2, -263.6),  'radius': 40},
    'T3_Andretti':      {'pos': (-38.9, -420.0),  'radius': 40},
}

def load_lap(filename):
    with open(filename) as f:
        return list(csv.DictReader(f))

def dist(x1, z1, x2, z2):
    return ((x1 - x2)**2 + (z1 - z2)**2) ** 0.5

def get_corner_data(rows, corner):
    cx, cz = corner['pos']
    r = corner['radius']
    packets = []
    for row in rows:
        x = float(row['pos_x'])
        z = float(row['pos_z'])
        if dist(x, z, cx, cz) < r:
            packets.append(row)
    return packets

def analyse_corner(name, lap1_rows, lap2_rows):
    c = CORNERS[name]
    d1 = get_corner_data(lap1_rows, c)
    d2 = get_corner_data(lap2_rows, c)

    if not d1 or not d2:
        print(f"\n{name}: insufficient data")
        return

    min_speed_1 = min(float(r['speed']) for r in d1)
    min_speed_2 = min(float(r['speed']) for r in d2)

    max_brake_1 = max(float(r['brake']) for r in d1)
    max_brake_2 = max(float(r['brake']) for r in d2)

    brake_start_1 = next((float(r['speed']) for r in d1 if float(r['brake']) > 20), None)
    brake_start_2 = next((float(r['speed']) for r in d2 if float(r['brake']) > 20), None)

    print(f"\n{'='*50}")
    print(f"Corner: {name}")
    print(f"  Min speed  - Lap 1: {min_speed_1:.1f} km/h | Lap 2: {min_speed_2:.1f} km/h | Delta: {min_speed_2 - min_speed_1:+.1f}")
    print(f"  Max brake  - Lap 1: {max_brake_1:.0f}%      | Lap 2: {max_brake_2:.0f}%      ")
    if brake_start_1 and brake_start_2:
        print(f"  Brake entry speed - Lap 1: {brake_start_1:.1f} | Lap 2: {brake_start_2:.1f} | Delta: {brake_start_2 - brake_start_1:+.1f}")

    # Coaching suggestion
    speed_delta = min_speed_2 - min_speed_1
    if speed_delta < -5:
        print(f"  ⚠️  Lap 2 minimum speed is {abs(speed_delta):.1f} km/h LOWER — braking too early or too hard")
    elif speed_delta > 5:
        print(f"  ✅ Lap 2 minimum speed is {speed_delta:.1f} km/h HIGHER — better corner entry")
    else:
        print(f"  ➡️  Similar minimum speed across both laps")

lap1 = load_lap('lap_1.csv')
lap2 = load_lap('lap_2.csv')

print("GT7 LAP COMPARATOR — Lap 1 vs Lap 2")
print("Laguna Seca | 911 GT3 R (992)")

for corner in CORNERS:
    analyse_corner(corner, lap1, lap2)

print(f"\n{'='*50}")
