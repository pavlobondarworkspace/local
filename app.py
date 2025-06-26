from flask import Flask, render_template, request, jsonify
import math, time, threading

app = Flask(__name__)

# Глобальные данные (thread-safe)
state = {
    "center": None,  # [lat, lon]
    "length": None,  # meters
    "angle": 0.0,    # degrees
    "direction": 1,  # 1 or -1
    "speed": 4.886,  # m/min
    "mode": 100,     # %
    "timer": 0,      # seconds
    "running": False,
    "time_factor": 1,
    "last_tick": time.time()
}
lock = threading.Lock()

def calc_end_pivot(center, length, angle):
    R = 6371000
    angle_rad = math.radians(angle)
    lat1, lon1 = map(math.radians, center)
    d_div_r = length / R
    lat2 = math.asin(math.sin(lat1) * math.cos(d_div_r) + math.cos(lat1) * math.sin(d_div_r) * math.cos(angle_rad))
    lon2 = lon1 + math.atan2(math.sin(angle_rad) * math.sin(d_div_r) * math.cos(lat1),
                             math.cos(d_div_r) - math.sin(lat1) * math.sin(lat2))
    return [math.degrees(lat2), math.degrees(lon2)]

def calc_azimuth(center, end):
    lat1, lon1, lat2, lon2 = map(math.radians, [*center, *end])
    d_lon = lon2 - lon1
    y = math.sin(d_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    az = (math.degrees(math.atan2(y, x)) + 360) % 360
    return az

def tick():
    with lock:
        now = time.time()
        dt = (now - state["last_tick"]) * state["time_factor"]
        state["last_tick"] = now
        if state["running"]:
            state["timer"] += dt
            if state["center"] and state["length"]:
                mode = state["mode"] / 100.0
                cycle = 60.0
                t_in_cycle = (state["timer"] % cycle)
                move_time = cycle * mode
                if t_in_cycle < move_time:
                    dt_move = min(dt, move_time - t_in_cycle)
                else:
                    dt_move = 0
                R = state["length"]
                v = state["speed"]
                if R > 0 and v > 0 and dt_move > 0:
                    omega = v / (60 * R)
                    d_angle = math.degrees(omega * dt_move) * state["direction"]
                    state["angle"] = (state["angle"] + d_angle) % 360.0

def get_circle_length():
    return 2 * math.pi * state["length"] if state["length"] else 0

def get_circle_time():
    if not state["length"] or not state["speed"] or not state["mode"]:
        return "00:00"
    length = get_circle_length()
    speed = state["speed"]
    duty = state["mode"] / 100.0
    if speed == 0 or duty == 0:
        return "00:00"
    mins = length / speed / duty
    h = int(mins // 60)
    m = int(mins % 60)
    return f"{h:02d}:{m:02d}"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/status")
def status():
    tick()
    with lock:
        center = state["center"]
        length = state["length"]
        angle = state["angle"]
        end = calc_end_pivot(center, length, angle) if center and length else None
        zero = calc_end_pivot(center, length, 0) if center and length else None
        azimuth = calc_azimuth(center, end) if center and end else None
        circle_length = get_circle_length()
        circle_time = get_circle_time()
        return jsonify({
            "center": center,
            "length": length,
            "angle": angle,
            "end": end,
            "zero": zero,
            "azimuth": azimuth,
            "timer": state["timer"],
            "running": state["running"],
            "direction": state["direction"],
            "speed": state["speed"],
            "mode": state["mode"],
            "time_factor": state["time_factor"],
            "circle_length": circle_length,
            "circle_time": circle_time
        })

@app.route("/set_center", methods=["POST"])
def set_center():
    data = request.json
    lat, lon = float(data["lat"]), float(data["lon"])
    with lock:
        state["center"] = [lat, lon]
        state["angle"] = 0.0
        state["timer"] = 0
    return jsonify(success=True)

@app.route("/set_length", methods=["POST"])
def set_length():
    data = request.json
    length = float(data["length"])
    with lock:
        state["length"] = length
        state["angle"] = 0.0
        state["timer"] = 0
    return jsonify(success=True)

@app.route("/control", methods=["POST"])
def control():
    data = request.json
    with lock:
        for k in ["direction", "speed", "mode", "time_factor"]:
            if k in data: state[k] = type(state[k])(data[k])
        if "running" in data: state["running"] = bool(data["running"])
        if "reset" in data and data["reset"]:
            state["angle"] = 0.0
            state["timer"] = 0
            state["running"] = False
    return jsonify(success=True)

@app.route("/start", methods=["POST"])
def start():
    with lock:
        state["running"] = True
    return jsonify(success=True)

@app.route("/stop", methods=["POST"])
def stop():
    with lock:
        state["running"] = False
    return jsonify(success=True)

@app.route("/reset", methods=["POST"])
def reset():
    with lock:
        for k in state: state[k] = state[k] if k in ["last_tick"] else None if isinstance(state[k], list) else 0 if isinstance(state[k], (int, float)) else False
        state["speed"] = 4.886
        state["mode"] = 100
        state["direction"] = 1
        state["time_factor"] = 1
        state["last_tick"] = time.time()
        state["timer"] = 0
    return jsonify(success=True)

if __name__ == "__main__":
    app.run(debug=True) 