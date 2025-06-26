import math
import os
from flask import Flask, render_template_string, request, jsonify
import folium
from branca.element import MacroElement, Template

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'interactive_app_secret_key_swal_fix')

# In-memory storage
app_data = {
    "loc1": None, "loc2": None, "azimuth": None,
    "status_message": "IAApp(SwalFix): Click map for Location 1."
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

@app.route('/')
def index():
    map_center = [20, 0]
    folium_map = folium.Map(location=map_center, zoom_start=2)

    if app_data["loc1"]:
        folium.Marker(location=app_data["loc1"], popup="Location 1", icon=folium.Icon(color='blue', icon='1', prefix='fa')).add_to(folium_map)
    if app_data["loc2"]:
        folium.Marker(location=app_data["loc2"], popup="Location 2", icon=folium.Icon(color='red', icon='2', prefix='fa')).add_to(folium_map)

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

    html_content_page = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Interactive Azimuth App (SwalFix)</title>
        <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
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
        <div class="container">
            <h1>Interactive Azimuth App (SwalFix)</h1>
            <div class="info-panel">
                <p id="status_display">{app_data['status_message']}</p>
                <p>Location 1: <span id="loc1_coords_display">{'Not set' if not app_data['loc1'] else '[{:.4f}, {:.4f}]'.format(app_data['loc1'][0], app_data['loc1'][1])}</span></p>
                <p>Location 2: <span id="loc2_coords_display">{'Not set' if not app_data['loc2'] else '[{:.4f}, {:.4f}]'.format(app_data['loc2'][0], app_data['loc2'][1])}</span></p>
                <p>Azimuth: <span id="azimuth_result_display">{('%.2f°' % app_data['azimuth']) if app_data['azimuth'] is not None else 'Not calculated'}</span></p>
            </div>
            <div class="button-panel">
                <form id="manual_center_pivot_form" style="display:inline-block; margin-left:10px;" onsubmit="return setCenterPivotManual(event)">
                    <input type="number" step="any" id="manual_center_lat" placeholder="Lat" required style="width:90px;">
                    <input type="number" step="any" id="manual_center_lng" placeholder="Lng" required style="width:90px;">
                    <button type="submit">Set Center Pivot (manual)</button>
                </form>
                <form id="pivot_length_form" style="display:inline-block; margin-left:10px;" onsubmit="return setPivotLength(event)">
                    <input type="number" step="any" id="pivot_length_input" placeholder="Pivot Length (m)" min="1" required style="width:120px;">
                    <button type="submit">Set Pivot Length</button>
                </form>
                <button class="reset-button" onclick="resetGlobalSelections()">Reset All Selections</button>
            </div>
            <div id="map_display_area">{map_html_representation}</div>
        </div>

        <script>
            async function handleGlobalMapInteraction(latitude, longitude) {{
                let targetLoc, confirmQuestion;
                const loc1IsSet_el = document.getElementById('loc1_coords_display');
                const loc2IsSet_el = document.getElementById('loc2_coords_display');
                const loc1IsSet = loc1IsSet_el && !loc1IsSet_el.innerText.includes('Not set');
                const loc2IsSet = loc2IsSet_el && !loc2IsSet_el.innerText.includes('Not set');

                if (!loc1IsSet) {{ targetLoc = 1; confirmQuestion = `Set Center Pivot: (${{latitude}}, ${{longitude}})?`; }}
                else if (!loc2IsSet) {{ targetLoc = 2; confirmQuestion = `Set End Pivot: (${{latitude}}, ${{longitude}})?`; }}
                else {{ Swal.fire('Selection Full', 'Both pivots set. Reset to change.', 'info'); return; }}

                const confirmation = await Swal.fire({{ title: 'Confirm Point', text: confirmQuestion, icon: 'question', showCancelButton: true, confirmButtonText: 'Yes', cancelButtonText: 'Cancel' }});
                if (confirmation.isConfirmed) {{ 
                    await processGlobalCoordinateSelection(latitude, longitude, targetLoc); 
                }}
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
        </script>
    </body>
    </html>
    """
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
    return jsonify({"success": True, "message": "IAApp(SwalFix): Selections cleared."})

# Health check endpoint for monitoring
@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "message": "IAApp is running"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    print("Starting Interactive Azimuth App (Render.com Version)...")
    print(f"Port: {port}")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)