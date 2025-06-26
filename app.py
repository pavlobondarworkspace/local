import math
import os
from flask import Flask, render_template_string, request, jsonify, Response
import folium
from branca.element import MacroElement, Template  # type: ignore

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'interactive_app_secret_key_swal_fix')

# In-memory storage
app_data = {
    "loc1": None, "loc2": None, "azimuth": None,
    "status_message": "IAApp(SwalFix): Click map for Location 1.",
    "pivot_length": None,
    # Симуляция
    "pivot_angle": 0.0,  # угол в градусах (0 = север)
    "pivot_direction": 1,  # 1 = по часовой, -1 = против
    "pivot_speed": 4.886,  # м/мин (по умолчанию 20:1)
    "pivot_mode": 100,  # % работы (0-100)
    "pivot_timer": 0,  # секунд
    "pivot_running": False,
    "pivot_time_factor": 1,  # ускорение времени (1,2,10,100,1000)
    "pivot_sector": 0.0  # сколько градусов пройдено
}

PIVOT_SPEEDS = {
    "20:1": 4.886,
    "25:1": 3.909,
    "30:1": 3.257,
    "40:1": 2.443,
    "50:1": 1.954,
    "60:1": 1.628
}

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

def calculate_end_pivot(lat1, lon1, length_m):
    # 1 градус широты ~ 111320 м
    delta_lat = length_m / 111320.0
    lat2 = lat1 + delta_lat
    lon2 = lon1
    return [lat2, lon2]

def calculate_end_pivot_by_angle(lat1, lon1, length_m, angle_deg):
    # angle_deg: 0 = север, 90 = восток, 180 = юг, 270 = запад
    R = 6378137  # радиус Земли в метрах
    d_rad = length_m / R
    angle_rad = math.radians(angle_deg)
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.asin(math.sin(lat1_rad) * math.cos(d_rad) + math.cos(lat1_rad) * math.sin(d_rad) * math.cos(angle_rad))
    lon2_rad = lon1_rad + math.atan2(math.sin(angle_rad) * math.sin(d_rad) * math.cos(lat1_rad), math.cos(d_rad) - math.sin(lat1_rad) * math.sin(lat2_rad))
    return [math.degrees(lat2_rad), math.degrees(lon2_rad)]

def get_sector_points(center, radius, angle_from, angle_to, n_points=60):
    # angle_from, angle_to в градусах, 0 = север
    points = []
    if angle_to < angle_from:
        angle_to += 360
    for i in range(n_points+1):
        angle = angle_from + (angle_to - angle_from) * i / n_points
        pt = calculate_end_pivot_by_angle(center[0], center[1], radius, angle)
        points.append(pt)
    return points

@app.route('/')
def index():
    map_center = [20, 0]
    folium_map = folium.Map(location=map_center, zoom_start=2)

    if app_data["loc1"]:
        folium.Marker(location=app_data["loc1"], popup="Center Pivot", icon=folium.Icon(color='blue', icon='1', prefix='fa')).add_to(folium_map)
    # Если есть длина и Center Pivot, вычисляем End Pivot и сектор
    end_pivot = None
    if app_data["loc1"] and app_data["pivot_length"]:
        # Текущий угол
        angle = app_data.get("pivot_angle", 0.0)
        end_pivot = calculate_end_pivot_by_angle(app_data["loc1"][0], app_data["loc1"][1], app_data["pivot_length"], angle)
        app_data["loc2"] = end_pivot
        folium.Marker(location=end_pivot, popup="End Pivot", icon=folium.Icon(color='red', icon='2', prefix='fa')).add_to(folium_map)
        # Линия
        folium.PolyLine([app_data["loc1"], end_pivot], color='blue', weight=4).add_to(folium_map)
        # Круг
        folium.Circle(
            location=app_data["loc1"],
            radius=app_data["pivot_length"],
            color='#2980b9',
            fill=True,
            fill_color='#f7b6d2',
            fill_opacity=0.3,
            weight=2
        ).add_to(folium_map)
        # Сектор (пройденный путь)
        sector_deg = min(app_data.get("pivot_sector", 0.0), 360)
        if sector_deg > 0.1:
            points = [app_data["loc1"]] + get_sector_points(app_data["loc1"], app_data["pivot_length"], 0, angle, n_points=60) + [app_data["loc1"]]
            folium.PolyLine(points, color='#c0397b', weight=8, opacity=0.5).add_to(folium_map)
    elif app_data["loc2"]:
        folium.Marker(location=app_data["loc2"], popup="End Pivot", icon=folium.Icon(color='red', icon='2', prefix='fa')).add_to(folium_map)

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

    map_html_representation = folium_map.get_root().render()

    html_content_page = """
    <!DOCTYPE html>
    <html lang=\"en\">
    <head>
        <meta charset=\"UTF-8\">
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
        <title>Center Pivot Simulator</title>
        <script src=\"https://cdn.jsdelivr.net/npm/sweetalert2@11\"></script>
        <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css\">
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 15px; background-color: #eef2f7; color: #333; }}
            .container {{ max-width: 900px; margin: auto; background-color: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            h1 {{ text-align: center; color: #2c3e50; margin-bottom: 20px; font-size: 1.8em;}}
            #map_display_area {{ height: 450px; width: 100%; margin-bottom: 20px; border-radius: 6px; border: 1px solid #bdc3c7; }}
            .info-panel {{ margin-bottom: 20px; padding: 15px; background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px; }}
            .info-panel p {{ margin: 8px 0; font-size: 1em; }}
            .info-panel span {{ font-weight: 600; color: #2980b9; }}
            .button-panel {{ text-align: center; margin-bottom: 20px; }}
            .pivot-control-panel {{ background: #f0f6fa; border: 1px solid #bcdff1; border-radius: 8px; padding: 18px 20px; margin-bottom: 20px; }}
            .pivot-control-panel h2 {{ font-size: 1.2em; color: #2471a3; margin-bottom: 12px; }}
            .pivot-row {{ display: flex; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }}
            .pivot-row label {{ min-width: 120px; font-weight: 500; margin-right: 10px; }}
            .pivot-row select, .pivot-row input[type=range] {{ margin-right: 15px; }}
            .pivot-row .pivot-timer {{ font-size: 1.1em; font-weight: 600; color: #2c3e50; margin-left: 10px; }}
            .pivot-row .pivot-btn {{ margin-right: 8px; padding: 7px 14px; border-radius: 5px; border: none; background: #3498db; color: #fff; font-size: 1em; cursor: pointer; transition: background 0.2s; }}
            .pivot-row .pivot-btn:hover {{ background: #2471a3; }}
            .pivot-row .pivot-btn.active {{ background: #e67e22; }}
            .pivot-row .pivot-btn.reset {{ background: #e74c3c; }}
            .pivot-row .pivot-btn.reset:hover {{ background: #c0392b; }}
            .pivot-row .pivot-btn.speed {{ background: #8e44ad; }}
            .pivot-row .pivot-btn.speed.active {{ background: #5e3370; }}
            .pivot-row .pivot-btn.timefactor {{ background: #16a085; }}
            .pivot-row .pivot-btn.timefactor.active {{ background: #117864; }}
            .pivot-row .pivot-btn:disabled {{ background: #b2bec3; cursor: not-allowed; }}
            .pivot-row .pivot-speed-table {{ border-collapse: collapse; margin-right: 15px; }}
            .pivot-row .pivot-speed-table th, .pivot-row .pivot-speed-table td {{ border: 1px solid #bcdff1; padding: 3px 8px; font-size: 0.95em; }}
            .pivot-row .pivot-speed-table th {{ background: #d6eaf8; }}
            .pivot-row .pivot-speed-table td.selected {{ background: #aed6f1; font-weight: 600; }}
            .pivot-row .pivot-slider-value {{ min-width: 38px; display: inline-block; text-align: right; font-weight: 600; color: #2980b9; }}
            .pivot-calc-panel {{ background: #fdf6f7; border: 1px solid #f7b6d2; border-radius: 8px; padding: 14px 20px; margin-bottom: 20px; }}
            .pivot-calc-panel h3 {{ font-size: 1.1em; color: #b03a2e; margin-bottom: 10px; }}
            .pivot-calc-panel .calc-row {{ margin-bottom: 6px; }}
        </style>
    </head>
    <body>
        <div class=\"container\">
            <h1>Center Pivot Simulator</h1>
            <div class=\"info-panel\">
                <p id=\"status_display\">{status_message}</p>
                <p>Center Pivot: <span id=\"loc1_coords_display\">{loc1_disp}</span></p>
                <p>End Pivot: <span id=\"loc2_coords_display\">{loc2_disp}</span></p>
                <p>Azimuth: <span id=\"azimuth_result_display\">{azimuth_disp}</span></p>
            </div>
            <div class=\"button-panel\">
                <button onclick=\"enableCenterPivotSelection()\">Set Center Pivot (by map)</button>
                <form id=\"manual_center_pivot_form\" style=\"display:inline-block; margin-left:10px;\" onsubmit=\"return setCenterPivotManual(event)\">
                    <input type=\"number\" step=\"any\" id=\"manual_center_lat\" placeholder=\"Lat\" required style=\"width:90px;\">
                    <input type=\"number\" step=\"any\" id=\"manual_center_lng\" placeholder=\"Lng\" required style=\"width:90px;\">
                    <button type=\"submit\">Set Center Pivot (manual)</button>
                </form>
                <form id=\"pivot_length_form\" style=\"display:inline-block; margin-left:10px;\" onsubmit=\"return setPivotLength(event)\">
                    <input type=\"number\" step=\"any\" id=\"pivot_length_input\" placeholder=\"Pivot Length (m)\" min=\"1\" required style=\"width:120px;\">
                    <button type=\"submit\">Set Pivot Length</button>
                </form>
                <button class=\"reset-button\" onclick=\"resetGlobalSelections()\">Reset All Selections</button>
            </div>
            <div class=\"pivot-control-panel\" id=\"pivot_control_panel\" style=\"display:none;\">
                <h2>Pivot Movement Control</h2>
                <div class=\"pivot-row\">
                    <label>Direction:</label>
                    <button class=\"pivot-btn\" id=\"dir_cw_btn\">Clockwise</button>
                    <button class=\"pivot-btn\" id=\"dir_ccw_btn\">Counterclockwise</button>
                </div>
                <div class=\"pivot-row\">
                    <label>Speed:</label>
                    <table class=\"pivot-speed-table\"><tr id=\"speed_names\"></tr><tr id=\"speed_values\"></tr></table>
                </div>
                <div class=\"pivot-row\">
                    <label>Work Mode (%):</label>
                    <input type=\"range\" min=\"0\" max=\"100\" step=\"1\" id=\"mode_slider\">
                    <span class=\"pivot-slider-value\" id=\"mode_slider_val\"></span>
                </div>
                <div class=\"pivot-row\">
                    <label>Time Factor:</label>
                    <button class=\"pivot-btn timefactor\" data-factor=\"1\">x1</button>
                    <button class=\"pivot-btn timefactor\" data-factor=\"2\">x2</button>
                    <button class=\"pivot-btn timefactor\" data-factor=\"10\">x10</button>
                    <button class=\"pivot-btn timefactor\" data-factor=\"100\">x100</button>
                    <button class=\"pivot-btn timefactor\" data-factor=\"1000\">x1000</button>
                </div>
                <div class=\"pivot-row\">
                    <label>Control:</label>
                    <button class=\"pivot-btn\" id=\"start_btn\">Start</button>
                    <button class=\"pivot-btn\" id=\"stop_btn\">Stop</button>
                    <button class=\"pivot-btn reset\" id=\"reset_btn\">Reset</button>
                    <span class=\"pivot-timer\" id=\"pivot_timer_display\">00:00:00</span>
                </div>
            </div>
            <div class=\"pivot-calc-panel\" id=\"pivot_calc_panel\" style=\"display:none;\">
                <h3>Calculated Data</h3>
                <div class=\"calc-row\">Circumference: <span id=\"circumference_val\">-</span> m</div>
                <div class=\"calc-row\">Full Rotation Time: <span id=\"rotation_time_val\">-</span> min</div>
            </div>
            <div id=\"map_display_area\">{map_html_representation}</div>
        </div>
        <script>
        var centerPivotSelectionEnabled = false;
        function enableCenterPivotSelection() {{
            centerPivotSelectionEnabled = true;
            Swal.fire('Mode Enabled', 'Click on the map to set Center Pivot.', 'info');
        }}
        async function handleGlobalMapInteraction(latitude, longitude) {{
            if (!centerPivotSelectionEnabled) return;
            let targetLoc = 1;
            let confirmQuestion = `Set Center Pivot: (${{latitude}}, ${{longitude}})?`;
            const confirmation = await Swal.fire({{ title: 'Confirm Point', text: confirmQuestion, icon: 'question', showCancelButton: true, confirmButtonText: 'Yes', cancelButtonText: 'Cancel' }});
            if (confirmation.isConfirmed) {{
                await processGlobalCoordinateSelection(latitude, longitude, targetLoc);
                centerPivotSelectionEnabled = false;
            }}
        }}
        async function setCenterPivotManual(event) {{
            event.preventDefault();
            const lat = document.getElementById('manual_center_lat').value;
            const lng = document.getElementById('manual_center_lng').value;
            await processGlobalCoordinateSelection(lat, lng, 1);
            return false;
        }}
        async function processGlobalCoordinateSelection(lat, lon, locId) {{
            try {{
                const response = await fetch('/set_coordinate', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ lat: parseFloat(lat), lon: parseFloat(lon), location_id: locId }})
                }});
                const result = await response.json();
                if (result.success) {{
                    Swal.fire({{ title: 'Point Set!', text: result.message, icon: 'success', timer: 1500, showConfirmButton: false }});
                    window.location.reload(); 
                }} else {{ Swal.fire('Error Setting Point', result.message || 'Unknown error.', 'error'); }}
            }} catch (err) {{
                console.error('Error in processGlobalCoordinateSelection:', err);
                Swal.fire('Network Error', 'Failed to communicate: ' + err.toString(), 'error');
            }}
        }}
        async function resetGlobalSelections() {{
            const confirmation = await Swal.fire({{ title: 'Confirm Reset', text: "Are you sure you want to clear all selected locations and azimuth?", icon: 'warning', showCancelButton: true, confirmButtonText: 'Yes, Reset', cancelButtonText: 'Cancel'}});
            if (confirmation.isConfirmed) {{
                try {{
                    const response = await fetch('/reset', {{ method: 'POST' }});
                    const result = await response.json();
                    if (result.success) {{
                        Swal.fire('Selections Reset', result.message, 'success');
                        window.location.reload();
                    }} else {{ Swal.fire('Error Resetting', result.message || 'Unknown error.', 'error'); }}
                }} catch (err) {{
                    console.error('Error in resetGlobalSelections:', err);
                    Swal.fire('Network Error', 'Failed to communicate for reset: ' + err.toString(), 'error');
                }}
            }}
        }}
        async function setPivotLength(event) {{
            event.preventDefault();
            const length = document.getElementById('pivot_length_input').value;
            try {{
                const response = await fetch('/set_pivot_length', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ length: parseFloat(length) }})
                }});
                const result = await response.json();
                if (result.success) {{
                    Swal.fire({{ title: 'Pivot Length Set!', text: result.message, icon: 'success', timer: 1200, showConfirmButton: false }});
                    window.location.reload();
                }} else {{ Swal.fire('Error', result.message || 'Unknown error.', 'error'); }}
            }} catch (err) {{
                Swal.fire('Network Error', 'Failed to set length: ' + err.toString(), 'error');
            }}
            return false;
        }}
        // --- Pivot Control JS ---
        const PIVOT_SPEEDS = {{{{"20:1":4.886,"25:1":3.909,"30:1":3.257,"40:1":2.443,"50:1":1.954,"60:1":1.628}}}};
        let pivotState = null;
        function updatePivotUI(state) {{{{
            // Показывать/скрывать блоки
            const show = state && state.pivot_length && state.loc1;
            document.getElementById('pivot_control_panel').style.display = show ? '' : 'none';
            document.getElementById('pivot_calc_panel').style.display = show ? '' : 'none';
            // Таймер
            let t = Math.floor(state.pivot_timer || 0);
            let h = Math.floor(t/3600), m = Math.floor((t%3600)/60), s = t%60;
            document.getElementById('pivot_timer_display').innerText = `${{h.toString().padStart(2,'0')}}:${{m.toString().padStart(2,'0')}}:${{s.toString().padStart(2,'0')}}`;
            // Расчетные данные
            document.getElementById('circumference_val').innerText = state.circumference ? state.circumference.toFixed(2) : '-';
            document.getElementById('rotation_time_val').innerText = state.rotation_time ? state.rotation_time.toFixed(1) : '-';
            // Скорости
            let names = '', vals = '';
            Object.entries(PIVOT_SPEEDS).forEach(([k,v])=>{{
                names += `<th>${{k}}</th>`;
                vals += `<td class='${{Math.abs((state.pivot_speed||0)-v)<0.001?'selected':''}}' data-speed='${{v}}'>${{v}}</td>`;
            }});
            document.getElementById('speed_names').innerHTML = names;
            document.getElementById('speed_values').innerHTML = vals;
            // Mode slider
            let slider = document.getElementById('mode_slider');
            slider.value = state.pivot_mode||100;
            document.getElementById('mode_slider_val').innerText = slider.value+'%';
            // Time factor
            document.querySelectorAll('.pivot-btn.timefactor').forEach(btn=>{{{{
                btn.classList.toggle('active', parseInt(btn.dataset.factor)==state.pivot_time_factor);
            }}}});
            // Direction
            document.getElementById('dir_cw_btn').classList.toggle('active', state.pivot_direction==1);
            document.getElementById('dir_ccw_btn').classList.toggle('active', state.pivot_direction==-1);
            // Start/Stop
            document.getElementById('start_btn').disabled = !!state.pivot_running;
            document.getElementById('stop_btn').disabled = !state.pivot_running;
        }}}}
        function sendPivotControl(action, data={{{{}}}}) {{{{
            fetch('/pivot_control', {{{{
                method: 'POST',
                headers: {{{{'Content-Type':'application/json'}}}},
                body: JSON.stringify(Object.assign({{{{action}}}}, data))
            }}}}).then(()=>setTimeout(fetchPivotState, 200));
        }}}}
        function fetchPivotState() {{{{
            fetch('/pivot_state').then(r=>r.json()).then(state=>{{{{
                pivotState = state;
                updatePivotUI(state);
            }}}});
        }}}}
        // --- Event listeners ---
        document.addEventListener('DOMContentLoaded', function() {{{{
            fetchPivotState();
            setInterval(fetchPivotState, 1000);
            // Speed table
            document.getElementById('speed_values').onclick = function(e) {{{{
                if(e.target.tagName==='TD') sendPivotControl('set_speed', {{{{speed: e.target.dataset.speed}}}});
            }}}};
            // Mode slider
            document.getElementById('mode_slider').oninput = function(e) {{{{
                document.getElementById('mode_slider_val').innerText = e.target.value+'%';
            }}}};
            document.getElementById('mode_slider').onchange = function(e) {{{{
                sendPivotControl('set_mode', {{{{mode: e.target.value}}}});
            }}}};
            // Time factor
            document.querySelectorAll('.pivot-btn.timefactor').forEach(btn=>{{{{
                btn.onclick = ()=>sendPivotControl('set_time_factor', {{{{factor: btn.dataset.factor}}}});
            }}}});
            // Direction
            document.getElementById('dir_cw_btn').onclick = ()=>sendPivotControl('set_direction', {{{{direction:1}}}});
            document.getElementById('dir_ccw_btn').onclick = ()=>sendPivotControl('set_direction', {{{{direction:-1}}}});
            // Start/Stop/Reset
            document.getElementById('start_btn').onclick = ()=>sendPivotControl('start');
            document.getElementById('stop_btn').onclick = ()=>sendPivotControl('stop');
            document.getElementById('reset_btn').onclick = ()=>sendPivotControl('reset');
        }}}});
        </script>
    </body>
    </html>
    """.format(
        status_message=app_data['status_message'],
        loc1_disp='Not set' if not app_data['loc1'] else '[{:.4f}, {:.4f}]'.format(app_data['loc1'][0], app_data['loc1'][1]),
        loc2_disp='Not set' if not app_data['loc2'] else '[{:.4f}, {:.4f}]'.format(app_data['loc2'][0], app_data['loc2'][1]),
        azimuth_disp=('%.2f°' % app_data['azimuth']) if app_data['azimuth'] is not None else 'Not calculated',
        map_html_representation=map_html_representation
    )
    return Response(html_content_page, content_type='text/html')

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

# Health check endpoint for monitoring
@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "message": "IAApp is running"})

# Расчет длины окружности
def get_circumference(length_m):
    return 2 * math.pi * length_m if length_m else 0

def get_full_rotation_time(length_m, speed_m_min, mode_percent):
    if not length_m or not speed_m_min or not mode_percent:
        return 0
    circ = get_circumference(length_m)
    # Скорость с учетом режима
    effective_speed = speed_m_min * (mode_percent / 100)
    if effective_speed == 0:
        return 0
    return circ / effective_speed  # минуты

# --- API для управления симуляцией ---
from flask import session
import time

@app.route('/pivot_state')
def get_pivot_state():
    # Для периодического опроса состояния
    state = {k: app_data[k] for k in [
        "pivot_angle", "pivot_direction", "pivot_speed", "pivot_mode", "pivot_timer", "pivot_running", "pivot_time_factor", "pivot_sector",
        "pivot_length", "loc1", "loc2"
    ]}
    # расчетные данные
    circ = get_circumference(app_data["pivot_length"])
    rot_time = get_full_rotation_time(app_data["pivot_length"], app_data["pivot_speed"], app_data["pivot_mode"])
    state["circumference"] = circ
    state["rotation_time"] = rot_time
    return jsonify(state)

@app.route('/pivot_control', methods=['POST'])
def pivot_control():
    payload = request.get_json()
    action = payload.get('action')
    if action == 'start':
        app_data["pivot_running"] = True
    elif action == 'stop':
        app_data["pivot_running"] = False
    elif action == 'reset':
        app_data["pivot_angle"] = 0.0
        app_data["pivot_timer"] = 0
        app_data["pivot_sector"] = 0.0
        app_data["pivot_running"] = False
    elif action == 'set_direction':
        app_data["pivot_direction"] = int(payload.get('direction', 1))
    elif action == 'set_speed':
        app_data["pivot_speed"] = float(payload.get('speed', 4.886))
    elif action == 'set_mode':
        app_data["pivot_mode"] = int(payload.get('mode', 100))
    elif action == 'set_time_factor':
        app_data["pivot_time_factor"] = int(payload.get('factor', 1))
    return jsonify({"success": True, "state": app_data})

# Фоновый "tick" для симуляции (упрощённо, без потоков)
last_tick = time.time()
@app.before_request
def pivot_simulation_tick():
    global last_tick
    now = time.time()
    dt = now - last_tick
    last_tick = now
    if app_data["pivot_running"] and app_data["pivot_length"] and app_data["loc1"]:
        # Учет ускорения времени
        dt *= app_data["pivot_time_factor"]
        # Учет режима работы (процент)
        work_time = dt * (app_data["pivot_mode"] / 100)
        # Угол, который проходит End Pivot за это время
        circ = get_circumference(app_data["pivot_length"])
        if circ > 0:
            angle_delta = 360 * (app_data["pivot_speed"] * work_time) / circ
            app_data["pivot_angle"] += angle_delta * app_data["pivot_direction"]
            app_data["pivot_angle"] %= 360
            app_data["pivot_sector"] += abs(angle_delta)
            if app_data["pivot_sector"] > 360:
                app_data["pivot_sector"] = 360
        app_data["pivot_timer"] += dt

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    print("Starting Interactive Azimuth App (Render.com Version)...")
    print(f"Port: {port}")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)