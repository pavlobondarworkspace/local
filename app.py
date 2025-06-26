import math
import os
from flask import Flask, render_template_string, request, jsonify
import folium
from branca.element import MacroElement, Template
from threading import Lock
import time

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'interactive_app_secret_key_swal_fix')

# In-memory storage
app_data = {
    "loc1": None, "loc2": None, "azimuth": None,
    "status_message": "IAApp(SwalFix): Click map for Location 1.",
    "pivot_length": None,
    "pivot_angle": 0.0,  # текущий угол (градусы)
    "pivot_direction": 1,  # 1 = по часовой, -1 = против
    "pivot_running": False,  # идёт ли движение
    "pivot_speed": 4.886,  # м/мин (по умолчанию)
    "pivot_mode": 100,  # % работы
    "pivot_timer": 0,  # секунд с момента старта
    "pivot_time_factor": 1,  # ускорение времени (1, 2, 10, 100, 1000)
}

app_data_lock = Lock()
last_tick_time = [time.time()]

def calculate_azimuth(lat1, lon1, lat2, lon2):
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    delta_lon = lon2_rad - lon1_rad
    y = math.sin(delta_lon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - \
        math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon)
    azimuth_rad = math.atan2(y, x)
    azimuth_deg = (math.degrees(azimuth_rad) + 360) % 360
    return azimuth_deg

# --- Utility: Calculate End Pivot by angle, length, and center ---
def calculate_end_pivot_by_angle(lat, lon, length_m, angle_deg):
    """
    Вычисляет координаты End Pivot по центру (lat, lon), длине (метры) и углу (градусы, от севера по часовой).
    Возвращает (lat2, lon2).
    """
    R = 6371000  # радиус Земли в метрах
    angle_rad = math.radians(angle_deg)
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    d_div_r = length_m / R
    lat2_rad = math.asin(math.sin(lat_rad) * math.cos(d_div_r) + math.cos(lat_rad) * math.sin(d_div_r) * math.cos(angle_rad))
    lon2_rad = lon_rad + math.atan2(
        math.sin(angle_rad) * math.sin(d_div_r) * math.cos(lat_rad),
        math.cos(d_div_r) - math.sin(lat_rad) * math.sin(lat2_rad)
    )
    return [math.degrees(lat2_rad), math.degrees(lon2_rad)]

def pivot_tick():
    """Обновляет угол и таймер в зависимости от состояния симуляции с учётом режима (duty cycle)."""
    with app_data_lock:
        now = time.time()
        dt = now - last_tick_time[0]
        last_tick_time[0] = now
        if app_data['pivot_running'] and app_data['loc1'] and app_data['pivot_length']:
            dt *= app_data['pivot_time_factor']
            mode = app_data['pivot_mode'] / 100.0 if app_data['pivot_mode'] else 1.0
            # Duty cycle: если режим < 100%, то часть времени стоим
            if mode < 1.0:
                # 1 цикл = 60 сек (30 сек едет, 30 сек стоит при 50%)
                cycle = 60.0
                t_in_cycle = (app_data['pivot_timer'] % cycle)
                move_time = cycle * mode
                if t_in_cycle + dt > cycle:
                    # Пересекаем границу duty cycle
                    dt_move = max(0, move_time - t_in_cycle) if t_in_cycle < move_time else 0
                else:
                    dt_move = min(dt, max(0, move_time - t_in_cycle)) if t_in_cycle < move_time else 0
            else:
                dt_move = dt
            circle_length = 2 * math.pi * app_data['pivot_length']
            if circle_length > 0 and dt_move > 0:
                speed = app_data['pivot_speed']
                d_angle = 360.0 * (speed * dt_move) / circle_length * app_data['pivot_direction']
                app_data['pivot_angle'] = (app_data['pivot_angle'] + d_angle) % 360.0
            app_data['pivot_timer'] += int(dt)

@app.route('/')
def index():
    map_center = [20, 0]
    folium_map = folium.Map(location=map_center, zoom_start=2)

    if app_data["loc1"]:
        folium.Marker(location=app_data["loc1"], popup="Center Pivot", icon=folium.Icon(color='blue', icon='1', prefix='fa')).add_to(folium_map)
    pivot_length = app_data.get("pivot_length")
    if app_data["loc1"] and pivot_length is not None and float(pivot_length) > 0:
        # Синяя линия (нулевой угол)
        zero_angle = 0.0
        end_pivot_zero = calculate_end_pivot_by_angle(app_data["loc1"][0], app_data["loc1"][1], float(pivot_length), zero_angle)
        folium.Marker(location=end_pivot_zero, popup="End Pivot (0°)", icon=folium.Icon(color='blue', icon='2', prefix='fa')).add_to(folium_map)
        folium.PolyLine([app_data["loc1"], end_pivot_zero], color='blue', weight=4).add_to(folium_map)
        # Красная линия (текущий угол)
        angle = app_data.get("pivot_angle", 0.0)
        end_pivot = calculate_end_pivot_by_angle(app_data["loc1"][0], app_data["loc1"][1], float(pivot_length), angle)
        app_data["loc2"] = end_pivot
        folium.Marker(location=end_pivot, popup="End Pivot (dynamic)", icon=folium.Icon(color='red', icon='3', prefix='fa')).add_to(folium_map)
        folium.PolyLine([app_data["loc1"], end_pivot], color='red', weight=4).add_to(folium_map)
        folium.Circle(
            location=app_data["loc1"],
            radius=float(pivot_length),
            color='#2980b9',
            fill=True,
            fill_color='#f7b6d2',
            fill_opacity=0.3,
            weight=2
        ).add_to(folium_map)

    # Relay function: defines handleGlobalMapInteraction in iframe, relays to parent handler
    relay_js = """
    {% macro script(this, kwargs) %}
        window.handleGlobalMapInteraction = function(lat, lng) {
            if (window.parent && window.parent.handleGlobalMapInteraction) {
                window.parent.handleGlobalMapInteraction(lat, lng);
            } else {
                console.error('handleGlobalMapInteraction not found in parent.');
            }
        }
    {% endmacro %}
    """
    relay_macro = MacroElement()
    relay_macro._template = Template(relay_js)
    folium_map.add_child(relay_macro)

    # Click listener: calls handleGlobalMapInteraction (now defined by relay)
    js_click_listener_template = """
        {% macro script(this, kwargs) %}
            var map_instance = {{ this._parent.get_name() }};
            if (typeof map_instance !== 'undefined' && map_instance && typeof map_instance.on === 'function'){
                 map_instance.on('click', function(e) {
                    handleGlobalMapInteraction(e.latlng.lat.toFixed(6), e.latlng.lng.toFixed(6));
                });
                console.log("IAApp(SwalFix): Click listener attached to map (id: " + map_instance.getContainer().id + ") via MacroElement.");
            } else {
                console.error("IAApp(SwalFix): Map instance '{{ this._parent.get_name() }}' not found or not a Leaflet map.");
            }
        {% endmacro %}
    """
    macro = MacroElement()
    macro._template = Template(js_click_listener_template)
    folium_map.add_child(macro)

    map_html_representation = folium_map._repr_html_()

    html_content_page = f'''
    <!DOCTYPE html>
    <html lang='en'>
    <head>
        <meta charset='UTF-8'>
        <meta name='viewport' content='width=device-width, initial-scale=1.0'>
        <title>Interactive Azimuth App (SwalFix)</title>
        <script src='https://cdn.jsdelivr.net/npm/sweetalert2@11'></script>
        <link rel='stylesheet' href='https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css'>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 15px; background-color: #eef2f7; color: #333; }}
            .container {{ max-width: 900px; margin: auto; background-color: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            h1 {{ text-align: center; color: #2c3e50; margin-bottom: 20px; font-size: 1.8em;}}
            #map_display_area {{ height: 450px; width: 100%; margin-bottom: 20px; border-radius: 6px; border: 1px solid #bdc3c7; }}
            .info-panel {{ margin-bottom: 20px; padding: 15px; background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px; }}
            .info-panel p {{ margin: 8px 0; font-size: 1em; }}
            .info-panel span {{ font-weight: 600; color: #2980b9; }}
            .button-panel {{ text-align: center; }}
            button {{ padding: 10px 18px; font-size: 0.95em; cursor: pointer; background-color: #3498db; color: white; border: none; border-radius: 5px; margin: 5px; transition: background-color 0.3s ease; }}
            button:hover {{ background-color: #2980b9; }}
            button.reset-button {{ background-color: #e74c3c; }}
            button.reset-button:hover {{ background-color: #c0392b; }}
        </style>
    </head>
    <body>
        <div class='container'>
            <h1>Interactive Azimuth App (SwalFix)</h1>
            <div class='info-panel'>
                <p id='status_display'>{app_data['status_message']}</p>
                <p>Center Pivot: <span id='loc1_coords_display'>{'Not set' if not app_data['loc1'] else '[{:.4f}, {:.4f}]'.format(app_data['loc1'][0], app_data['loc1'][1])}</span></p>
                <p>End Pivot (dynamic): <span id='loc2_coords_display'>{'Not set' if not app_data['loc2'] else '[{:.4f}, {:.4f}]'.format(app_data['loc2'][0], app_data['loc2'][1])}</span></p>
                <p>Azimuth: <span id='azimuth_result_display'>{('%.2f°' % app_data['azimuth']) if app_data['azimuth'] is not None else 'Not calculated'}</span></p>
            </div>
            <div class='button-panel'>
                <form id='manual_center_pivot_form' style='display:inline-block; margin-left:10px;' onsubmit='return setCenterPivotManual(event)'>
                    <input type='number' step='any' id='manual_center_lat' placeholder='Lat' required style='width:90px;'>
                    <input type='number' step='any' id='manual_center_lng' placeholder='Lng' required style='width:90px;'>
                    <button type='submit'>Set Center Pivot (manual)</button>
                </form>
                <form id='pivot_length_form' style='display:inline-block; margin-left:10px;' onsubmit='return setPivotLength(event)'>
                    <input type='number' step='any' id='pivot_length_input' placeholder='Pivot Length (m)' min='1' required style='width:120px;' value='{app_data.get('pivot_length') if app_data.get('pivot_length') else ''}'>
                    <button type='submit'>Set Pivot Length</button>
                </form>
                <button class='reset-button' onclick='resetGlobalSelections()'>Reset All Selections</button>
            </div>
            <div class='info-panel' id='pivot_warning' style='display:none; color:#b71c1c; background:#ffeaea;'>Для симуляции задайте Center Pivot и длину машины.</div>
            <div class='info-panel' id='pivot_control_block' style='display:none;'>
                <h3 style='margin-top:0;'>Управление движением</h3>
                <div style='display:flex; flex-wrap:wrap; align-items:center; gap:10px;'>
                    <button id='dir_ccw_btn' onclick='setDirection(-1)'>⟲ Против часовой</button>
                    <button id='dir_cw_btn' onclick='setDirection(1)'>⟳ По часовой</button>
                    <button id='start_stop_btn' onclick='toggleStartStop()'>{'Стоп' if app_data['pivot_running'] else 'Старт'}</button>
                    <span>Скорость:</span>
                    <select id='speed_select' onchange='setSpeed()'>
                        <option value='4.886' {'selected' if app_data['pivot_speed']==4.886 else ''}>20:1 (4.886 м/мин)</option>
                        <option value='3.909' {'selected' if app_data['pivot_speed']==3.909 else ''}>25:1 (3.909 м/мин)</option>
                        <option value='3.257' {'selected' if app_data['pivot_speed']==3.257 else ''}>30:1 (3.257 м/мин)</option>
                        <option value='2.443' {'selected' if app_data['pivot_speed']==2.443 else ''}>40:1 (2.443 м/мин)</option>
                        <option value='1.954' {'selected' if app_data['pivot_speed']==1.954 else ''}>50:1 (1.954 м/мин)</option>
                        <option value='1.628' {'selected' if app_data['pivot_speed']==1.628 else ''}>60:1 (1.628 м/мин)</option>
                    </select>
                    <span>Режим работы:</span>
                    <input type='range' id='mode_slider' min='0' max='100' value='{app_data['pivot_mode']}' step='1' oninput='setMode()'>
                    <span id='mode_value'>{app_data['pivot_mode']}%</span>
                    <span>Таймер: <span id='pivot_timer_display'>{app_data['pivot_timer']//3600:02d}:{(app_data['pivot_timer']//60)%60:02d}</span></span>
                    <button onclick='resetPivot()'>Reset</button>
                    <span>Ускорение:</span>
                    <button onclick='setTimeFactor(1)'>x1</button>
                    <button onclick='setTimeFactor(2)'>x2</button>
                    <button onclick='setTimeFactor(10)'>x10</button>
                    <button onclick='setTimeFactor(100)'>x100</button>
                    <button onclick='setTimeFactor(1000)'>x1000</button>
                </div>
            </div>
            <div class='info-panel' id='pivot_calc_block' style='margin-top:10px; background:#f8e9f0; display:none;'>
                <h3 style='margin-top:0;'>Расчётные данные</h3>
                <p>Длина окружности: <span id='circle_length_display'>{(2*math.pi*app_data['pivot_length']) if app_data['pivot_length'] else 0:.2f} м</span> </p>
                <p>Время полного оборота: <span id='circle_time_display'>{((2*math.pi*app_data['pivot_length'])/(app_data['pivot_speed'] if app_data['pivot_speed'] else 1)/ (app_data['pivot_mode']/100 if app_data['pivot_mode'] else 1)) / (app_data['pivot_time_factor'] if app_data['pivot_time_factor'] else 1) if app_data['pivot_length'] else 0:.2f} мин</span></p>
            </div>
            <div id='map_display_area'>{map_html_representation}</div>
        </div>
        <script>
            // ... существующие функции ...
            async function handleGlobalMapInteraction(latitude, longitude) {
                const loc1IsSet_el = document.getElementById('loc1_coords_display');
                const loc1IsSet = loc1IsSet_el && !loc1IsSet_el.innerText.includes('Not set');
                if (loc1IsSet) {
                    Swal.fire('Center Pivot already set', 'Use reset to change.', 'info');
                    return;
                }
                let confirmQuestion = `Set Center Pivot: (${latitude}, ${longitude})?`;
                const confirmation = await Swal.fire({ title: 'Confirm Point', text: confirmQuestion, icon: 'question', showCancelButton: true, confirmButtonText: 'Yes', cancelButtonText: 'Cancel' });
                if (confirmation.isConfirmed) {
                    await processGlobalCoordinateSelection(latitude, longitude, 1);
                }
            }

            async function processGlobalCoordinateSelection(lat, lon, locId) {
                try {
                    const response = await fetch('/set_coordinate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ lat: parseFloat(lat), lon: parseFloat(lon), location_id: locId })
                    });
                    const result = await response.json();
                    if (result.success) {
                        Swal.fire({ title: 'Point Set!', text: result.message, icon: 'success', timer: 1500, showConfirmButton: false });
                        window.location.reload(); 
                    } else { Swal.fire('Error Setting Point', result.message || 'Unknown error.', 'error'); }
                } catch (err) {
                    console.error('Error in processGlobalCoordinateSelection:', err);
                    Swal.fire('Network Error', 'Failed to communicate: ' + err.toString(), 'error');
                }
            }

            async function resetGlobalSelections() {
                const confirmation = await Swal.fire({ title: 'Confirm Reset', text: "Are you sure you want to clear all selected locations and azimuth?", icon: 'warning', showCancelButton: true, confirmButtonText: 'Yes, Reset', cancelButtonText: 'Cancel' });
                if (confirmation.isConfirmed) {
                    try {
                        const response = await fetch('/reset', { method: 'POST' });
                        const result = await response.json();
                        if (result.success) {
                            Swal.fire('Selections Reset', result.message, 'success');
                            window.location.reload();
                        } else { Swal.fire('Error Resetting', result.message || 'Unknown error.', 'error'); }
                    } catch (err) {
                        console.error('Error in resetGlobalSelections:', err);
                        Swal.fire('Network Error', 'Failed to communicate for reset: ' + err.toString(), 'error');
                    }
                }
            }

            async function setCenterPivotManual(event) {
                event.preventDefault();
                const lat = document.getElementById('manual_center_lat').value;
                const lng = document.getElementById('manual_center_lng').value;
                await processGlobalCoordinateSelection(lat, lng, 1);
                window.location.reload();
                return false;
            }

            async function setPivotLength(event) {
                event.preventDefault();
                const length = document.getElementById('pivot_length_input').value;
                try {
                    const response = await fetch('/set_pivot_length', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ length: parseFloat(length) })
                    });
                    const result = await response.json();
                    if (result.success) {
                        Swal.fire({ title: 'Pivot Length Set!', text: result.message, icon: 'success', timer: 1200, showConfirmButton: false });
                        window.location.reload();
                    } else { Swal.fire('Error', result.message || 'Unknown error.', 'error'); }
                } catch (err) {
                    Swal.fire('Network Error', 'Failed to set length: ' + err.toString(), 'error');
                }
                return false;
            }

            // --- Управление движением ---
            async function setDirection(dir) {
                await fetch('/pivot_control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'direction', direction: dir })
                });
            }
            async function toggleStartStop() {
                const running = document.getElementById('start_stop_btn').innerText === 'Стоп';
                await fetch('/pivot_control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: running ? 'stop' : 'start' })
                });
            }
            async function setSpeed() {
                const speed = document.getElementById('speed_select').value;
                await fetch('/pivot_control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'speed', speed: speed })
                });
            }
            async function setMode() {
                const mode = document.getElementById('mode_slider').value;
                document.getElementById('mode_value').innerText = mode + '%';
                await fetch('/pivot_control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'mode', mode: mode })
                });
            }
            async function setTimeFactor(factor) {
                await fetch('/pivot_control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'time_factor', time_factor: factor })
                });
            }
            async function resetPivot() {
                await fetch('/pivot_control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'reset' })
                });
            }

            // --- Периодический опрос статуса и обновление UI ---
            let prevAngle = null;
            async function pollPivotStatus() {
                try {
                    const resp = await fetch('/pivot_status');
                    const data = await resp.json();
                    // Таймер
                    const t = data.timer;
                    document.getElementById('pivot_timer_display').innerText =
                        `${String(Math.floor(t/3600)).padStart(2,'0')}:${String(Math.floor((t/60)%60)).padStart(2,'0')}`;
                    // Кнопка старт/стоп
                    document.getElementById('start_stop_btn').innerText = data.running ? 'Стоп' : 'Старт';
                    // Обновление End Pivot (dynamic)
                    if (data.end_pivot) {
                        document.getElementById('loc2_coords_display').innerText = `[${data.end_pivot[0].toFixed(4)}, ${data.end_pivot[1].toFixed(4)}]`;
                    }
                    // Обновление азимута
                    if (data.azimuth !== undefined && data.azimuth !== null) {
                        document.getElementById('azimuth_result_display').innerText = `${data.azimuth.toFixed(2)}°`;
                    }
                } catch (e) { /* ignore */ }
                setTimeout(pollPivotStatus, 1000);
            }
            pollPivotStatus();

            // --- Визуализация сектора на карте (через Leaflet) ---
            function addSectorArcToMap() {
                const iframe = document.querySelector('#map_display_area iframe');
                if (!iframe) { setTimeout(addSectorArcToMap, 1000); return; }
                const win = iframe.contentWindow;
                if (!win.L) { setTimeout(addSectorArcToMap, 1000); return; }
                let map = null;
                for (let k in win) {
                    if (win[k] && win[k].setView && win[k].on) { map = win[k]; break; }
                }
                if (!map) { setTimeout(addSectorArcToMap, 1000); return; }
                const loc1 = {lat: parseFloat(document.getElementById('loc1_coords_display').innerText.replace(/[^\d.,-]/g,'').split(',')[0]), lng: parseFloat(document.getElementById('loc1_coords_display').innerText.replace(/[^\d.,-]/g,'').split(',')[1])};
                const radius = parseFloat(document.getElementById('pivot_length_input').value);
                if (!loc1.lat || !loc1.lng || !radius) return;
                let baseCircle = null;
                window.updateSectorArc = function(angle) {
                    if (baseCircle) { map.removeLayer(baseCircle); }
                    // Только основной круг, без сектора
                    baseCircle = win.L.circle([loc1.lat, loc1.lng], {radius: radius, color:'#2980b9', fillColor:'#f7b6d2', fillOpacity:0.3, weight:2});
                    baseCircle.addTo(map);
                };
            }
            setTimeout(addSectorArcToMap, 2000);

            function checkPivotBlocks() {
                const loc1 = document.getElementById('loc1_coords_display').innerText;
                const len = document.getElementById('pivot_length_input').value;
                const show = loc1 && !loc1.includes('Not set') && len && parseFloat(len) > 0;
                document.getElementById('pivot_control_block').style.display = show ? '' : 'none';
                document.getElementById('pivot_calc_block').style.display = show ? '' : 'none';
                document.getElementById('pivot_warning').style.display = show ? 'none' : '';
            }
            setTimeout(checkPivotBlocks, 1000);
        </script>
    </body>
    </html>
    '''
    return render_template_string(html_content_page)

@app.route('/set_coordinate', methods=['POST'])
def set_coordinate_endpoint():
    try:
        payload = request.get_json()
        lat, lon, loc_id = payload.get('lat'), payload.get('lon'), payload.get('location_id')
        if any(val is None for val in [lat, lon, loc_id]): return jsonify({"success": False, "message": "IAApp(SwalFix): Incomplete data."}), 400
        lat, lon, loc_id = float(lat), float(lon), int(loc_id)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): return jsonify({"success": False, "message": "IAApp(SwalFix): Coords out of range."}), 400
        current_message = ""
        if loc_id == 1:
            app_data["loc1"] = [lat, lon]; app_data["status_message"] = "IAApp(SwalFix): Loc 1 set. Select Loc 2."
            current_message = f"IAApp(SwalFix): Loc 1 recorded: [{lat:.4f}, {lon:.4f}]."
        elif loc_id == 2:
            app_data["loc2"] = [lat, lon]; app_data["status_message"] = "IAApp(SwalFix): Loc 2 set. Azimuth pending."
            current_message = f"IAApp(SwalFix): Loc 2 recorded: [{lat:.4f}, {lon:.4f}]."
        else: return jsonify({"success": False, "message": "IAApp(SwalFix): Invalid location ID."}), 400
        app_data["azimuth"] = None 
        if app_data["loc1"] and app_data["loc2"]:
            try:
                az = calculate_azimuth(app_data["loc1"][0], app_data["loc1"][1], app_data["loc2"][0], app_data["loc2"][1])
                app_data["azimuth"] = az; app_data["status_message"] = f"IAApp(SwalFix): Azimuth: {az:.2f}°"
                current_message += f" Azimuth: {az:.2f}°."
            except Exception as e:
                app_data["status_message"] = "IAApp(SwalFix): Error in azimuth calc."; current_message += f" Calc Error: {str(e)}"
        return jsonify({
            "success": True, "message": current_message, "status_message": app_data["status_message"],
            "loc1_coords": app_data["loc1"], "loc2_coords": app_data["loc2"], "azimuth": app_data["azimuth"]
        })
    except Exception as e: return jsonify({"success": False, "message": f"IAApp(SwalFix): Server error: {str(e)}"}), 500

@app.route('/reset', methods=['POST'])
def reset_endpoint():
    app_data["loc1"], app_data["loc2"], app_data["azimuth"] = None, None, None
    app_data["status_message"] = "IAApp(SwalFix): Reset. Select Loc 1."
    app_data["pivot_angle"] = 0.0
    app_data["pivot_timer"] = 0
    app_data["pivot_running"] = False
    return jsonify({"success": True, "message": "IAApp(SwalFix): Selections cleared."})

@app.route('/set_pivot_length', methods=['POST'])
def set_pivot_length():
    try:
        payload = request.get_json()
        length = payload.get('length')
        if length is None or float(length) <= 0:
            return jsonify({"success": False, "message": "Invalid length."}), 400
        app_data["pivot_length"] = float(length)
        return jsonify({"success": True, "message": f"Pivot Length set: {length} m."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500

@app.route('/pivot_control', methods=['POST'])
def pivot_control():
    with app_data_lock:
        data = request.get_json()
        action = data.get('action')
        if action == 'start':
            app_data['pivot_running'] = True
        elif action == 'stop':
            app_data['pivot_running'] = False
        elif action == 'direction':
            app_data['pivot_direction'] = int(data.get('direction', 1))
        elif action == 'speed':
            app_data['pivot_speed'] = float(data.get('speed', 4.886))
        elif action == 'mode':
            app_data['pivot_mode'] = int(data.get('mode', 100))
        elif action == 'time_factor':
            app_data['pivot_time_factor'] = int(data.get('time_factor', 1))
        elif action == 'reset':
            app_data['pivot_angle'] = 0.0
            app_data['pivot_timer'] = 0
            app_data['pivot_running'] = False
        return jsonify({"success": True, "app_data": app_data})

@app.route('/pivot_status', methods=['GET'])
def pivot_status():
    pivot_tick()
    with app_data_lock:
        loc1 = app_data['loc1']
        pivot_length = app_data['pivot_length']
        angle = app_data['pivot_angle']
        end_pivot = None
        azimuth = None
        if loc1 and pivot_length:
            end_pivot = calculate_end_pivot_by_angle(loc1[0], loc1[1], float(pivot_length), angle)
            # Азимут между loc1 и текущим End Pivot
            azimuth = calculate_azimuth(loc1[0], loc1[1], end_pivot[0], end_pivot[1])
            app_data['azimuth'] = azimuth
        return jsonify({
            "angle": angle,
            "timer": app_data['pivot_timer'],
            "running": app_data['pivot_running'],
            "direction": app_data['pivot_direction'],
            "speed": app_data['pivot_speed'],
            "mode": app_data['pivot_mode'],
            "time_factor": app_data['pivot_time_factor'],
            "end_pivot": end_pivot,
            "azimuth": azimuth,
        })

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "message": "IAApp is running"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    print("Starting Interactive Azimuth App (Render.com Version)...")
    print(f"Port: {port}")
    app.run(host='0.0.0.0', port=port, debug=debug_mode) 