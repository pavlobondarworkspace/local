import math
import os
import time
from flask import Flask, render_template_string, request, jsonify
import folium
from branca.element import MacroElement, Template

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'interactive_app_secret_key_swal_fix')

# In-memory storage
app_data = {
    "center_pivot": None, "end_pivot": None, "azimuth": None, "pivot_length": None,
    "status_message": "IAApp(SwalFix): Set Center Pivot by map click or manually.",

    # Simulation state
    "simulation_running": False,
    "current_angle_deg": 0.0,  # 0 is North, positive CW
    "selected_speed_mps": 0.0, # m/s
    "direction": "cw", # "cw" or "ccw"
    "work_cycle_percentage": 100, # 0-100
    "time_acceleration": 1, # 1, 2, 10, 100, 1000
    "elapsed_simulation_time_sec": 0.0, # Effective run time
    "last_update_timestamp": 0.0, # Server time of last update
    "current_cycle_elapsed_sec": 0.0, # Time in current run/pause phase
    "is_in_run_phase": True, # True for run, False for pause in work cycle

    # Swept area visualization
    "swept_sector_points": [], # List of [lat, lon] points on the circumference for the swept sector
    "last_angle_added_to_sweep": -1.0 # Control point addition to sweep path, init to ensure first point adds
}

# Earth radius in meters
EARTH_RADIUS_METERS = 6371000.0
SWEEP_ANGLE_RESOLUTION_DEG = 1.0 # Add a point to swept path for every X degrees of change

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

def calculate_destination_point(lat, lon, distance_m, bearing_deg):
    """
    Calculates the destination point given a starting point, distance, and bearing.
    Lat, Lon in degrees. Distance in meters. Bearing in degrees (0 is North).
    Returns (dest_lat, dest_lon) in degrees.
    """
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    bearing_rad = math.radians(bearing_deg)

    angular_distance = distance_m / EARTH_RADIUS_METERS

    dest_lat_rad = math.asin(math.sin(lat_rad) * math.cos(angular_distance) +
                             math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing_rad))

    dest_lon_rad = lon_rad + math.atan2(math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat_rad),
                                     math.cos(angular_distance) - math.sin(lat_rad) * math.sin(dest_lat_rad))

    return math.degrees(dest_lat_rad), math.degrees(dest_lon_rad)

@app.route('/')
def index():
    map_center = [20, 0]
    folium_map = folium.Map(location=map_center, zoom_start=2)

    if app_data["center_pivot"]:
        folium.Marker(location=app_data["center_pivot"], popup="Center Pivot", icon=folium.Icon(color='blue', icon='1', prefix='fa')).add_to(folium_map)

    if app_data["end_pivot"] and app_data["center_pivot"] and app_data["pivot_length"]:
        # End Pivot marker
        folium.Marker(location=app_data["end_pivot"], popup="End Pivot", icon=folium.Icon(color='red', icon='2', prefix='fa')).add_to(folium_map)
        # Line for pivot arm
        folium.PolyLine(locations=[app_data["center_pivot"], app_data["end_pivot"]], color="blue", weight=5, opacity=0.8).add_to(folium_map)
        # Circle for pivot coverage
        folium.Circle(
            location=app_data["center_pivot"],
            radius=app_data["pivot_length"],
            color='blue', # Outline color
            fill=True,
            fill_color='lightpink', # Pastel Pink
            fill_opacity=0.3,
            popup=f"Coverage (Radius: {app_data['pivot_length']}m)"
        ).add_to(folium_map)

        # Draw swept area polygon
        if app_data.get("center_pivot") and app_data.get("swept_sector_points") and len(app_data["swept_sector_points"]) >= 1:
            # The polygon is formed by the center, then all points along the arc.
            # If only one point on arc, it's a line (degenerate polygon). Need at least 2 for a visible sector.
            # If swept_sector_points = [P0, P1, P2], vertices = [Center, P0, P1, P2]
            # P0 should be the point at angle 0.
            polygon_vertices = [app_data["center_pivot"]] + app_data["swept_sector_points"]

            if len(polygon_vertices) >= 3: # A polygon needs at least 3 vertices
                folium.Polygon(
                    locations=polygon_vertices,
                    color='darkred', # Outline for the swept sector
                    fill=True,
                    fill_color='mediumvioletred', # Darker pink for swept area
                    fill_opacity=0.3, # Same transparency
                    tooltip="Swept Area"
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
                <p>Center Pivot: <span id="center_pivot_coords_display">{'Not set' if not app_data['center_pivot'] else '[{:.4f}, {:.4f}]'.format(app_data['center_pivot'][0], app_data['center_pivot'][1])}</span></p>
                <p>End Pivot: <span id="end_pivot_coords_display">{'Not set' if not app_data['end_pivot'] else '[{:.4f}, {:.4f}]'.format(app_data['end_pivot'][0], app_data['end_pivot'][1])}</span></p>
                <p>Azimuth: <span id="azimuth_result_display">{('%.2f°' % app_data['azimuth']) if app_data['azimuth'] is not None else 'Not calculated'}</span></p>
            </div>
            <div class="input-section" style="margin-bottom: 15px; padding:10px; background-color: #f0f0f0; border-radius:5px;">
                <h4>Center Pivot Configuration</h4>
                <button id="setCenterByClickBtn" onclick="enableCenterPivotMapClick()">Set Center Pivot by Map Click</button>
                <div style="margin-top:10px; margin-bottom:10px;">
                    <label for="center_lat_manual">Lat:</label>
                    <input type="number" id="center_lat_manual" step="any" placeholder="e.g., 40.7128" style="width:120px;">
                    <label for="center_lon_manual">Lon:</label>
                    <input type="number" id="center_lon_manual" step="any" placeholder="e.g., -74.0060" style="width:120px;">
                    <button onclick="setCenterPivotManually()">Set Manually</button>
                </div>
            </div>
            <div class="input-section" style="margin-bottom: 15px; padding:10px; background-color: #f0f0f0; border-radius:5px;">
                <h4>Pivot Arm Configuration</h4>
                <label for="pivot_length_input">Pivot Length (meters):</label>
                <input type="number" id="pivot_length_input" step="1" placeholder="e.g., 400" style="width:100px;">
                <button onclick="calculateEndPivotAndDraw()">Calculate End Pivot & Draw</button>
                <p>Pivot Length: <span id="pivot_length_display">{'Not set' if not app_data['pivot_length'] else str(app_data['pivot_length']) + 'm'}</span></p>
            </div>

            <div class="input-section" id="movement_control_panel" style="margin-bottom: 15px; padding:10px; background-color: #e9ecef; border-radius:5px;">
                <h4>Movement Control</h4>

                <!-- Direction -->
                <div style="margin-bottom:10px;">
                    <label>Direction:</label>
                    <input type="radio" id="direction_cw" name="direction" value="cw" checked> <label for="direction_cw">Clockwise</label>
                    <input type="radio" id="direction_ccw" name="direction" value="ccw"> <label for="direction_ccw">Counter-Clockwise</label>
                </div>

                <!-- Start/Stop -->
                <button id="start_stop_button" style="background-color: #28a745;">Start Simulation</button>

                <!-- Speed Selection -->
                <div style="margin-top:10px; margin-bottom:10px;">
                    <label for="speed_select">Speed Setting:</label>
                    <select id="speed_select">
                        <option value="4.886">20:1 (4.886 m/min)</option>
                        <option value="3.909">25:1 (3.909 m/min)</option>
                        <option value="3.257" selected>30:1 (3.257 m/min)</option>
                        <option value="2.443">40:1 (2.443 m/min)</option>
                        <option value="1.954">50:1 (1.954 m/min)</option>
                        <option value="1.628">60:1 (1.628 m/min)</option>
                    </select>
                </div>

                <!-- Work Cycle Percentage -->
                <div style="margin-bottom:10px;">
                    <label for="work_cycle_slider">Work Cycle (%): </label>
                    <input type="range" id="work_cycle_slider" min="0" max="100" value="100" step="1" style="width: 200px;">
                    <span id="work_cycle_display">100%</span>
                </div>

                <!-- Timer -->
                <p>Timer: <span id="simulation_timer_display">00:00</span></p>

                <!-- Reset Simulation -->
                <button id="reset_simulation_button">Reset Simulation Position & Timer</button>

                <!-- Time Acceleration -->
                <div style="margin-top:10px;">
                    <label>Time Acceleration:</label>
                    <button class="accel-button" data-accel="1" style="background-color: #007bff;">x1</button>
                    <button class="accel-button" data-accel="2">x2</button>
                    <button class="accel-button" data-accel="10">x10</button>
                    <button class="accel-button" data-accel="100">x100</button>
                    <button class="accel-button" data-accel="1000">x1000</button>
                </div>
            </div>

            <div class="input-section" id="calculated_data_panel" style="margin-bottom: 15px; padding:10px; background-color: #f8f9fa; border-radius:5px;">
                <h4>Calculated Data</h4>
                <p>Circumference: <span id="display_circumference">N/A</span> meters</p>
                <p>Est. Full Rotation Time (at 100% cycle): <span id="display_rotation_time_ideal">N/A</span></p>
                <p>Est. Full Rotation Time (current cycle %): <span id="display_rotation_time_actual">N/A</span></p>
            </div>

            <div class="button-panel">
                <button class="reset-button" onclick="resetGlobalSelections()">Reset All Sections</button>
            </div>
            <div id="map_display_area">{map_html_representation}</div>
        </div>

        <script>
            // This variable will control whether map clicks are processed for Center Pivot
            let allowCenterPivotMapClick = false;

            function updateStatusDisplay(message) {
                document.getElementById('status_display').innerText = message;
            }

            function updateWorkCycleDisplay() {
                const slider = document.getElementById('work_cycle_slider');
                const display = document.getElementById('work_cycle_display');
                if (slider && display) {
                    display.innerText = slider.value + '%';
                }
            }
            let simulationIntervalId = null;
            let currentAcceleration = 1;

            function formatTime(totalSeconds) { // Used for simulation timer (HH:MM:SS)
                if (isNaN(totalSeconds) || totalSeconds < 0) totalSeconds = 0;
                const hours = Math.floor(totalSeconds / 3600);
                const minutes = Math.floor((totalSeconds % 3600) / 60);
                const seconds = Math.floor(totalSeconds % 60);
                return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
            }

            function formatTimeHHMM(totalSeconds) { // Used for estimated rotation time
                if (isNaN(totalSeconds) || totalSeconds < 0 || !isFinite(totalSeconds)) return "N/A";
                const hours = Math.floor(totalSeconds / 3600);
                const minutes = Math.floor((totalSeconds % 3600) / 60);
                return `${String(hours).padStart(2, '0')}h ${String(minutes).padStart(2, '0')}m`;
            }

            function updateCalculatedDataDisplays() {
                const pivotLengthEl = document.getElementById('pivot_length_input');
                const speedSelectEl = document.getElementById('speed_select');
                const workCycleSliderEl = document.getElementById('work_cycle_slider');

                const displayCircumferenceEl = document.getElementById('display_circumference');
                const displayRotationTimeIdealEl = document.getElementById('display_rotation_time_ideal');
                const displayRotationTimeActualEl = document.getElementById('display_rotation_time_actual');

                let pivotLength = parseFloat(pivotLengthEl.value);
                if (document.getElementById('pivot_length_display').innerText.includes('Not set') && isNaN(pivotLength)) {
                    // Try to get from display if input is empty (e.g. after page load)
                     const displayedLengthText = document.getElementById('pivot_length_display').innerText;
                     if (displayedLengthText && !displayedLengthText.includes('Not set')) {
                        pivotLength = parseFloat(displayedLengthText.replace('m', ''));
                     }
                }


                if (isNaN(pivotLength) || pivotLength <= 0) {
                    displayCircumferenceEl.innerText = "N/A";
                    displayRotationTimeIdealEl.innerText = "N/A";
                    displayRotationTimeActualEl.innerText = "N/A";
                    return;
                }

                const circumference = 2 * Math.PI * pivotLength;
                displayCircumferenceEl.innerText = circumference.toFixed(2);

                const speedMetersPerMin = parseFloat(speedSelectEl.value); // This is m/min from the select options
                if (isNaN(speedMetersPerMin) || speedMetersPerMin <= 0) {
                    displayRotationTimeIdealEl.innerText = "N/A";
                    displayRotationTimeActualEl.innerText = "N/A";
                    return;
                }
                const speedMetersPerSec = speedMetersPerMin / 60.0;

                // Ideal time (100% work cycle)
                const timeIdealSec = circumference / speedMetersPerSec;
                displayRotationTimeIdealEl.innerText = formatTimeHHMM(timeIdealSec);

                // Actual time (current work cycle %)
                const workCyclePercentage = parseInt(workCycleSliderEl.value);
                if (isNaN(workCyclePercentage) || workCyclePercentage < 0 || workCyclePercentage > 100) {
                     displayRotationTimeActualEl.innerText = "N/A";
                     return;
                }

                if (workCyclePercentage === 0) {
                    displayRotationTimeActualEl.innerText = "Infinite (0% cycle)";
                } else {
                    const effectiveSpeedMps = speedMetersPerSec * (workCyclePercentage / 100.0);
                    const timeActualSec = circumference / effectiveSpeedMps;
                    displayRotationTimeActualEl.innerText = formatTimeHHMM(timeActualSec);
                }
            }


            function updateUIAfterSimulationTick(data) {
                if (data.end_pivot_coords) {
                    document.getElementById('end_pivot_coords_display').innerText = `[${parseFloat(data.end_pivot_coords[0]).toFixed(4)}, ${parseFloat(data.end_pivot_coords[1]).toFixed(4)}]`;
                }
                if (data.azimuth !== null && data.azimuth !== undefined) {
                     // Assuming azimuth from backend is the current angle
                    document.getElementById('azimuth_result_display').innerText = `${parseFloat(data.current_angle_deg).toFixed(2)}°`;
                }
                 if (data.elapsed_simulation_time_sec !== null && data.elapsed_simulation_time_sec !== undefined) {
                    document.getElementById('simulation_timer_display').innerText = formatTime(data.elapsed_simulation_time_sec);
                }
                if (data.status_message) {
                    updateStatusDisplay(data.status_message);
                }
            }

            async function pollSimulationUpdate() {
                try {
                    const response = await fetch('/get_simulation_update');
                    const result = await response.json();
                    if (result.success) {
                        updateUIAfterSimulationTick(result);
                        if (result.simulation_running) {
                            // Reload to update map if simulation is running and changes occurred.
                            // This is heavy, but simplest for Folium.
                            // A small delay before reload to make it slightly less frantic.
                            setTimeout(() => window.location.reload(), 250);
                        } else {
                            // If simulation stopped from backend, ensure frontend state matches
                            if (simulationIntervalId) {
                                clearInterval(simulationIntervalId);
                                simulationIntervalId = null;
                                document.getElementById('start_stop_button').innerText = 'Start Simulation';
                                document.getElementById('start_stop_button').style.backgroundColor = '#28a745'; // Green
                            }
                        }
                    } else {
                        console.error("Error polling simulation update:", result.message);
                        Swal.fire('Polling Error', result.message || 'Unknown error during polling.', 'error');
                        // Stop polling on error to prevent spamming
                        if (simulationIntervalId) clearInterval(simulationIntervalId);
                        simulationIntervalId = null;
                        document.getElementById('start_stop_button').innerText = 'Start Simulation';
                        document.getElementById('start_stop_button').style.backgroundColor = '#28a745';
                    }
                } catch (err) {
                    console.error('Network error during polling:', err);
                    Swal.fire('Network Error', 'Polling failed: ' + err.toString(), 'error');
                    if (simulationIntervalId) clearInterval(simulationIntervalId);
                    simulationIntervalId = null;
                    document.getElementById('start_stop_button').innerText = 'Start Simulation';
                    document.getElementById('start_stop_button').style.backgroundColor = '#28a745';
                }
            }

            async function handleStartStopSimulation() {
                const startStopButton = document.getElementById('start_stop_button');
                if (simulationIntervalId) { // Currently running, so stop it
                    try {
                        const response = await fetch('/stop_simulation', { method: 'POST' });
                        const result = await response.json();
                        if (result.success) {
                            Swal.fire('Simulation Stopped', result.message, 'info');
                            clearInterval(simulationIntervalId);
                            simulationIntervalId = null;
                            startStopButton.innerText = 'Start Simulation';
                            startStopButton.style.backgroundColor = '#28a745'; // Green
                            updateStatusDisplay(result.status_message || 'IAApp(SwalFix): Simulation stopped.');
                             // Final poll to get the last state and update timer accurately
                            const finalState = await (await fetch('/get_simulation_update')).json();
                            if(finalState.success) updateUIAfterSimulationTick(finalState);

                        } else {
                            Swal.fire('Error Stopping', result.message || 'Unknown error.', 'error');
                        }
                    } catch (err) {
                        Swal.fire('Network Error', 'Failed to stop simulation: ' + err.toString(), 'error');
                    }
                } else { // Currently stopped, so start it
                    const direction = document.querySelector('input[name="direction"]:checked').value;
                    const speedMps = parseFloat(document.getElementById('speed_select').value) / 60.0; // Convert m/min to m/s
                    const workCyclePercentage = parseInt(document.getElementById('work_cycle_slider').value);
                    // currentAcceleration is a global JS var, updated by accel buttons

                    if (speedMps <= 0) {
                        Swal.fire('Invalid Speed', 'Please select a valid speed greater than 0.', 'warning');
                        return;
                    }
                    const centerPivotSet = !document.getElementById('center_pivot_coords_display').innerText.includes('Not set');
                    const pivotLengthSet = !document.getElementById('pivot_length_display').innerText.includes('Not set');

                    if (!centerPivotSet || !pivotLengthSet) {
                        Swal.fire('Configuration Incomplete', 'Please set Center Pivot and Pivot Length before starting simulation.', 'warning');
                        return;
                    }

                    try {
                        const response = await fetch('/start_simulation', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ direction, speed_mps: speedMps, work_cycle_percentage: workCyclePercentage, time_acceleration: currentAcceleration })
                        });
                        const result = await response.json();
                        if (result.success) {
                            Swal.fire('Simulation Started', result.message, 'success');
                            startStopButton.innerText = 'Stop Simulation';
                            startStopButton.style.backgroundColor = '#dc3545'; // Red
                            updateStatusDisplay(result.status_message || 'IAApp(SwalFix): Simulation running...');
                            // Poll very frequently initially to get first update quickly, then reload will happen.
                            // The reload itself will handle subsequent updates to the map.
                            // Polling interval should be longer if not reloading, e.g. 1000-2000ms.
                            // Since we reload, this interval is more about how often we check if backend stopped it.
                            simulationIntervalId = setInterval(pollSimulationUpdate, 1500);
                        } else {
                            Swal.fire('Error Starting', result.message || 'Unknown error.', 'error');
                        }
                    } catch (err) {
                        Swal.fire('Network Error', 'Failed to start simulation: ' + err.toString(), 'error');
                    }
                }
            }

            async function handleResetSimulation() {
                const confirmation = await Swal.fire({ title: 'Confirm Reset Simulation', text: "Reset pivot to North and timer to zero?", icon: 'warning', showCancelButton: true, confirmButtonText: 'Yes, Reset', cancelButtonText: 'Cancel'});
                if (confirmation.isConfirmed) {
                    try {
                        // Stop simulation if running
                        if (simulationIntervalId) {
                           await fetch('/stop_simulation', { method: 'POST' });
                           clearInterval(simulationIntervalId);
                           simulationIntervalId = null;
                           document.getElementById('start_stop_button').innerText = 'Start Simulation';
                           document.getElementById('start_stop_button').style.backgroundColor = '#28a745';
                        }

                        const response = await fetch('/reset_simulation', { method: 'POST' });
                        const result = await response.json();
                        if (result.success) {
                            Swal.fire('Simulation Reset', result.message, 'success');
                            updateUIAfterSimulationTick(result); // Update displays like timer, coords
                            document.getElementById('simulation_timer_display').innerText = formatTime(0);
                            // Reload to reflect reset position on map
                            window.location.reload();
                        } else {
                            Swal.fire('Error Resetting Simulation', result.message || 'Unknown error.', 'error');
                        }
                    } catch (err) {
                        Swal.fire('Network Error', 'Failed to reset simulation: ' + err.toString(), 'error');
                    }
                }
            }

            async function updateBackendAcceleration(newAccel) {
                if (simulationIntervalId) { // Only if simulation is running
                    // To apply new acceleration, we can send it to an update endpoint
                    // This ensures the backend's calculation uses the new factor immediately.
                    try {
                        const response = await fetch('/update_simulation_params', {
                             method: 'POST',
                             headers: { 'Content-Type': 'application/json' },
                             body: JSON.stringify({ time_acceleration: newAccel })
                        });
                        const result = await response.json();
                        if (!result.success) {
                             Swal.fire('Accel Update Error', result.message || 'Could not update acceleration.', 'error');
                        } else {
                            // console.log("Acceleration updated on backend.");
                        }
                    } catch (err) {
                        Swal.fire('Network Error', 'Failed to update acceleration: ' + err.toString(), 'error');
                    }
                }
            }


            // Event Listeners Setup
            document.addEventListener('DOMContentLoaded', function() {
                updateWorkCycleDisplay(); // For cosmetic update of slider %
                updateCalculatedDataDisplays(); // For calculated data section

                const workCycleSliderEl = document.getElementById('work_cycle_slider');
                if (workCycleSliderEl) {
                    workCycleSliderEl.addEventListener('input', function() {
                        updateWorkCycleDisplay(); // Cosmetic
                        updateCalculatedDataDisplays(); // Update data
                        // If simulation is running, update work cycle on backend
                        if (simulationIntervalId) {
                            fetch('/update_simulation_params', {
                                 method: 'POST',
                                 headers: { 'Content-Type': 'application/json' },
                                 body: JSON.stringify({ work_cycle_percentage: parseInt(this.value) })
                            });
                        }
                    });
                }

                document.getElementById('start_stop_button').addEventListener('click', handleStartStopSimulation);
                document.getElementById('reset_simulation_button').addEventListener('click', handleResetSimulation);

                document.querySelectorAll('.accel-button').forEach(button => {
                    button.addEventListener('click', function() {
                        currentAcceleration = parseInt(this.dataset.accel);
                        // Update styles for accel buttons
                        document.querySelectorAll('.accel-button').forEach(btn => btn.style.backgroundColor = ''); // Reset all
                        this.style.backgroundColor = '#007bff'; // Highlight active
                        // console.log("Current acceleration set to: " + currentAcceleration);
                        updateBackendAcceleration(currentAcceleration);
                    });
                });

                // Update speed/direction on backend if changed while running, and update calculated data
                const speedSelectEl = document.getElementById('speed_select');
                if (speedSelectEl) {
                    speedSelectEl.addEventListener('change', function() {
                        updateCalculatedDataDisplays();
                        if (simulationIntervalId) {
                            const newSpeedMps = parseFloat(this.value) / 60.0;
                            fetch('/update_simulation_params', {
                                 method: 'POST',
                                 headers: { 'Content-Type': 'application/json' },
                                 body: JSON.stringify({ selected_speed_mps: newSpeedMps })
                            });
                        }
                    });
                }

                document.querySelectorAll('input[name="direction"]').forEach(radio => {
                    radio.addEventListener('change', function() {
                        if (simulationIntervalId) {
                             fetch('/update_simulation_params', {
                                 method: 'POST',
                                 headers: { 'Content-Type': 'application/json' },
                                 body: JSON.stringify({ direction: this.value })
                            });
                        }
                    });
                });

            });


            function enableCenterPivotMapClick() {
                const centerPivotIsSet_el = document.getElementById('center_pivot_coords_display');
                const centerPivotIsSet = centerPivotIsSet_el && !centerPivotIsSet_el.innerText.includes('Not set');
                if (centerPivotIsSet) {
                    Swal.fire('Info', 'Center Pivot is already set. Reset if you want to change it by map click.', 'info');
                    return;
                }
                allowCenterPivotMapClick = true;
                updateStatusDisplay('IAApp(SwalFix): Click on the map to set Center Pivot.');
                // Optional: Change button appearance or disable manual inputs while this mode is active
                // document.getElementById('setCenterByClickBtn').innerText = 'Map Click Enabled (Click Map)';
            }

            async function setCenterPivotManually() {
                const latInput = document.getElementById('center_lat_manual');
                const lonInput = document.getElementById('center_lon_manual');
                const lat = parseFloat(latInput.value);
                const lon = parseFloat(lonInput.value);

                if (isNaN(lat) || isNaN(lon)) {
                    Swal.fire('Invalid Input', 'Latitude and Longitude must be numbers.', 'error');
                    return;
                }
                if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
                    Swal.fire('Invalid Coordinates', 'Latitude must be between -90 and 90. Longitude between -180 and 180.', 'error');
                    return;
                }

                // Confirmation before setting
                const confirmQuestion = `Set Center Pivot manually to: (${lat.toFixed(6)}, ${lon.toFixed(6)})?`;
                const confirmation = await Swal.fire({ title: 'Confirm Point', text: confirmQuestion, icon: 'question', showCancelButton: true, confirmButtonText: 'Yes', cancelButtonText: 'Cancel' });

                if (confirmation.isConfirmed) {
                    await processGlobalCoordinateSelection(lat.toFixed(6), lon.toFixed(6), 1); // 1 for Center Pivot
                    latInput.value = ''; // Clear input after setting
                    lonInput.value = ''; // Clear input after setting
                }
            }

            async function calculateEndPivotAndDraw() {
                const pivotLengthInput = document.getElementById('pivot_length_input');
                const pivotLength = parseFloat(pivotLengthInput.value);

                if (isNaN(pivotLength) || pivotLength <= 0) {
                    Swal.fire('Invalid Input', 'Pivot Length must be a positive number.', 'error');
                    return;
                }

                const centerPivotIsSet_el = document.getElementById('center_pivot_coords_display');
                if (!centerPivotIsSet_el || centerPivotIsSet_el.innerText.includes('Not set')) {
                    Swal.fire('Missing Center Pivot', 'Please set the Center Pivot coordinates first.', 'info');
                    return;
                }

                try {
                    const response = await fetch('/calculate_end_pivot', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ pivot_length: pivotLength }) // Center Pivot is already in session/app_data
                    });
                    const result = await response.json();
                    if (result.success) {
                        Swal.fire({ title: 'End Pivot Calculated!', text: result.message, icon: 'success', timer: 2000, showConfirmButton: false });
                        // Update displays - this will be handled by page reload triggered by successful setting
                        window.location.reload();
                    } else {
                        Swal.fire('Error Calculating End Pivot', result.message || 'Unknown error.', 'error');
                    }
                } catch (err) {
                    console.error('Error in calculateEndPivotAndDraw:', err);
                    Swal.fire('Network Error', 'Failed to communicate: ' + err.toString(), 'error');
                }
            }

            async function handleGlobalMapInteraction(latitude, longitude) {{
                let targetLoc, confirmQuestion;
                const centerPivotIsSet_el = document.getElementById('center_pivot_coords_display');
                const endPivotIsSet_el = document.getElementById('end_pivot_coords_display');
                const centerPivotIsSet = centerPivotIsSet_el && !centerPivotIsSet_el.innerText.includes('Not set');
                const endPivotIsSet = endPivotIsSet_el && !endPivotIsSet_el.innerText.includes('Not set');

                // Logic for setting points:
                // 1. If allowCenterPivotMapClick is true and Center Pivot is not set, set Center Pivot.
                // 2. (Later, End Pivot might be set differently, e.g., calculated)
                // For now, we adapt the old logic slightly. The main change is disabling map clicks by default.

                if (allowCenterPivotMapClick && !centerPivotIsSet) {{
                    targetLoc = 1; // 1 for Center Pivot
                    confirmQuestion = `Set Center Pivot: (${{latitude}}, ${{longitude}})?`;
                }} else if (!allowCenterPivotMapClick && !centerPivotIsSet) {
                    Swal.fire('Info', 'Click "Set Center Pivot by Map Click" button first or enter coordinates manually.', 'info'); return;
                }
                // The following condition for setting End Pivot via map click will be removed or significantly changed later
                // as End Pivot will be calculated. For now, let's keep a similar structure for loc2 (End Pivot).
                else if (centerPivotIsSet && !endPivotIsSet) {{ // This part will change with pivot length logic
                    targetLoc = 2; // 2 for End Pivot
                    confirmQuestion = `Set End Pivot: (${{latitude}}, ${{longitude}})?`;
                }} else {{
                    Swal.fire('Selection Info', 'Center Pivot is set. End Pivot will be calculated or set based on pivot length.', 'info'); return;
                }}

                const confirmation = await Swal.fire({{ title: 'Confirm Point', text: confirmQuestion, icon: 'question', showCancelButton: true, confirmButtonText: 'Yes', cancelButtonText: 'Cancel' }});
                if (confirmation.isConfirmed) {{ 
                    await processGlobalCoordinateSelection(latitude, longitude, targetLoc);
                    if (targetLoc === 1) {{ // If Center Pivot was set
                        allowCenterPivotMapClick = false; // Disable map click again
                        // Potentially update button text or state here if needed
                    }}
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
        if loc_id == 1: # Center Pivot
            app_data["center_pivot"] = [lat, lon]
            app_data["status_message"] = "IAApp(SwalFix): Center Pivot set. Enter Pivot Length or set End Pivot."
            # If End Pivot was set (e.g. from a previous operation before reset), clear it as Center Pivot changed.
            app_data["end_pivot"] = None
            app_data["azimuth"] = None
            current_message = f"IAApp(SwalFix): Center Pivot recorded: [{lat:.4f}, {lon:.4f}]."
        elif loc_id == 2: # End Pivot (this logic will be mostly replaced by calculation via length)
            if not app_data["center_pivot"]:
                return jsonify({"success": False, "message": "IAApp(SwalFix): Set Center Pivot first."}), 400
            app_data["end_pivot"] = [lat, lon]
            app_data["status_message"] = "IAApp(SwalFix): End Pivot set. Azimuth pending."
            current_message = f"IAApp(SwalFix): End Pivot recorded: [{lat:.4f}, {lon:.4f}]."
        else: return jsonify({"success": False, "message": "IAApp(SwalFix): Invalid location ID."}), 400

        app_data["azimuth"] = None # Always reset azimuth when a point changes
        if app_data["center_pivot"] and app_data["end_pivot"]:
            try:
                az = calculate_azimuth(app_data["center_pivot"][0], app_data["center_pivot"][1], app_data["end_pivot"][0], app_data["end_pivot"][1])
                app_data["azimuth"] = az
                app_data["status_message"] = f"IAApp(SwalFix): Azimuth: {az:.2f}°"
                current_message += f" Azimuth: {az:.2f}°."
            except Exception as e:
                app_data["status_message"] = "IAApp(SwalFix): Error in azimuth calc."
                current_message += f" Calc Error: {str(e)}"

        return jsonify({
            "success": True, "message": current_message, "status_message": app_data["status_message"],
            "center_pivot_coords": app_data["center_pivot"], "end_pivot_coords": app_data["end_pivot"],
            "azimuth": app_data["azimuth"]
        })
    except Exception as e: return jsonify({"success": False, "message": f"IAApp(SwalFix): Server error: {str(e)}"}), 500

@app.route('/reset', methods=['POST'])
def reset_endpoint():
    app_data["center_pivot"], app_data["end_pivot"], app_data["azimuth"], app_data["pivot_length"] = None, None, None, None
    app_data["status_message"] = "IAApp(SwalFix): Reset. Set Center Pivot by map click or manually."

    # Reset simulation state
    app_data["simulation_running"] = False
    app_data["current_angle_deg"] = 0.0
    app_data["selected_speed_mps"] = 0.0
    app_data["direction"] = "cw"
    app_data["work_cycle_percentage"] = 100
    app_data["time_acceleration"] = 1
    app_data["elapsed_simulation_time_sec"] = 0.0
    app_data["last_update_timestamp"] = 0.0
    app_data["current_cycle_elapsed_sec"] = 0.0
    app_data["is_in_run_phase"] = True
    app_data["swept_sector_points"] = []
    app_data["last_angle_added_to_sweep"] = -1.0

    return jsonify({"success": True, "message": "IAApp(SwalFix): All selections and simulation state cleared."})

@app.route('/calculate_end_pivot', methods=['POST'])
def calculate_end_pivot_endpoint():
    try:
        payload = request.get_json()
        pivot_length = payload.get('pivot_length')

        if not pivot_length or not isinstance(pivot_length, (int, float)) or float(pivot_length) <= 0:
            return jsonify({"success": False, "message": "IAApp(SwalFix): Invalid Pivot Length provided."}), 400

        pivot_length = float(pivot_length)
        app_data["pivot_length"] = pivot_length

        if not app_data["center_pivot"]:
            return jsonify({"success": False, "message": "IAApp(SwalFix): Center Pivot not set."}), 400

        center_lat, center_lon = app_data["center_pivot"]

        # Calculate End Pivot at current_angle_deg (which is 0 on initial setup/reset)
        target_bearing = app_data.get("current_angle_deg", 0.0)
        end_lat, end_lon = calculate_destination_point(center_lat, center_lon, pivot_length, target_bearing)

        app_data["end_pivot"] = [end_lat, end_lon]
        app_data["azimuth"] = target_bearing # Azimuth is the current angle for the pivot

        app_data["status_message"] = f"IAApp(SwalFix): End Pivot calculated. Pivot Angle: {target_bearing:.2f}°"

        return jsonify({
            "success": True,
            "message": f"End Pivot calculated at [{end_lat:.4f}, {end_lon:.4f}]. Pivot Angle: {target_bearing:.2f}°.",
            "end_pivot_coords": app_data["end_pivot"],
            "azimuth": app_data["azimuth"],
            "pivot_length": app_data["pivot_length"]
        })

    except Exception as e:
        app_data["status_message"] = "IAApp(SwalFix): Error calculating End Pivot."
        return jsonify({"success": False, "message": f"IAApp(SwalFix): Server error: {str(e)}"}), 500

@app.route('/start_simulation', methods=['POST'])
def start_simulation_endpoint():
    if not app_data.get("center_pivot") or not app_data.get("pivot_length"):
        return jsonify({"success": False, "message": "Center Pivot and Pivot Length must be set."}), 400

    payload = request.get_json()
    app_data["direction"] = payload.get("direction", "cw")
    app_data["selected_speed_mps"] = float(payload.get("speed_mps", 0.0))
    app_data["work_cycle_percentage"] = int(payload.get("work_cycle_percentage", 100))
    app_data["time_acceleration"] = int(payload.get("time_acceleration", 1))

    if app_data["selected_speed_mps"] <= 0:
        return jsonify({"success": False, "message": "Speed must be positive."}), 400
    if not (0 <= app_data["work_cycle_percentage"] <= 100):
        return jsonify({"success": False, "message": "Work cycle must be between 0 and 100."}), 400

    app_data["simulation_running"] = True
    # Do not reset angle or elapsed time here, allow resume
    # app_data["current_angle_deg"] = 0.0 # Reset only on full reset or simulation_reset
    # app_data["elapsed_simulation_time_sec"] = 0.0
    app_data["current_cycle_elapsed_sec"] = 0.0 # Reset cycle phase time
    app_data["is_in_run_phase"] = True         # Always start in a run phase
    app_data["last_update_timestamp"] = time.time()
    app_data["status_message"] = "IAApp(SwalFix): Simulation started."

    # Initialize swept path if it's a fresh start for the sweep visual
    if not app_data["swept_sector_points"] or app_data["current_angle_deg"] == 0: # If list is empty or we are at angle 0
        app_data["swept_sector_points"] = []
        app_data["last_angle_added_to_sweep"] = -1.0 # Force adding the first point

        # Add the initial point (at current angle, expected to be 0 for a new sweep)
        # If current_angle_deg is not 0 but we want sweep from 0, this needs adjustment.
        # For now, sweep starts from current_angle_deg.
        # The request implies sweep starts from 0 azimuth. So, reset_simulation should handle this.
        # If start_simulation is called and current_angle is 0, this is the true start of a sweep.
        if app_data["center_pivot"] and app_data["pivot_length"]:
            # Ensure the very first point corresponds to angle 0 if we are starting fresh
            # This assumes reset_simulation has set current_angle_deg to 0.
            # Or, if we want to always draw from 0 even if current_angle_deg is something else on start:
            initial_sweep_draw_angle = 0.0
            # However, the path should reflect actual movement.
            # So, if current_angle_deg is already X, the sweep starts from X.
            # The request "пройденный сектор" (traversed sector) implies from the start of movement.

            # If the simulation is starting and the current angle is effectively zero,
            # this is the beginning of a new sweep from the reference direction.
            if abs(app_data["current_angle_deg"]) < 0.01: # Check if angle is (near) zero
                app_data["swept_sector_points"] = [] # Clear any previous path
                app_data["last_angle_added_to_sweep"] = -1.0

                # Calculate and add the point at angle 0
                ep_lat, ep_lon = calculate_destination_point(
                    app_data["center_pivot"][0], app_data["center_pivot"][1],
                    app_data["pivot_length"], 0.0 # Explicitly angle 0
                )
                if not app_data["swept_sector_points"]: # Add if list is empty
                     app_data["swept_sector_points"].append([ep_lat, ep_lon])
                     app_data["last_angle_added_to_sweep"] = 0.0
            # If resuming, swept_sector_points should already contain the path up to current_angle_deg
            # and last_angle_added_to_sweep should be correctly set.
            # The _perform_simulation_update_step will then continue adding points.
    return jsonify({"success": True, "message": "Simulation started."})

@app.route('/stop_simulation', methods=['POST'])
def stop_simulation_endpoint():
    if app_data["simulation_running"]:
        # Final update before stopping to capture any remaining time
        _perform_simulation_update_step(is_stopping=True)
    app_data["simulation_running"] = False
    app_data["status_message"] = "IAApp(SwalFix): Simulation stopped."
    return jsonify({"success": True, "message": "Simulation stopped."})

@app.route('/reset_simulation', methods=['POST'])
def reset_simulation_endpoint():
    app_data["simulation_running"] = False
    app_data["current_angle_deg"] = 0.0
    app_data["elapsed_simulation_time_sec"] = 0.0
    app_data["current_cycle_elapsed_sec"] = 0.0
    app_data["is_in_run_phase"] = True
    app_data["swept_sector_points"] = []
    app_data["last_angle_added_to_sweep"] = -1.0 # Reset to ensure first point of new simulation adds

    if app_data["center_pivot"] and app_data["pivot_length"]:
        center_lat, center_lon = app_data["center_pivot"]
        end_lat, end_lon = calculate_destination_point(center_lat, center_lon, app_data["pivot_length"], 0.0)
        app_data["end_pivot"] = [end_lat, end_lon]
        app_data["azimuth"] = 0.0
        message = "Simulation position and timer reset. Pivot at 0 degrees."
    else:
        message = "Simulation timer reset. Set Center Pivot and Length to fully reset position."

    app_data["status_message"] = "IAApp(SwalFix): " + message
    return jsonify({
        "success": True,
        "message": message,
        "end_pivot_coords": app_data.get("end_pivot"),
        "azimuth": app_data.get("azimuth")
    })

@app.route('/update_simulation_params', methods=['POST'])
def update_simulation_params_endpoint():
    if not app_data["simulation_running"]:
        return jsonify({"success": False, "message": "Simulation not running. Cannot update params."}), 400

    payload = request.get_json()
    # Update only parameters that are allowed to change mid-simulation
    if 'time_acceleration' in payload:
        app_data["time_acceleration"] = int(payload['time_acceleration'])
    if 'selected_speed_mps' in payload: # If speed changes are allowed mid-run
        app_data["selected_speed_mps"] = float(payload['selected_speed_mps'])
    if 'direction' in payload:
        app_data["direction"] = payload['direction']
    if 'work_cycle_percentage' in payload:
         app_data["work_cycle_percentage"] = int(payload['work_cycle_percentage'])

    # After param update, recalculate current cycle progress with new params if needed, or simply let next tick adjust.
    # For simplicity, the next tick of get_simulation_update will use the new params.
    # We should update the last_update_timestamp to avoid a large jump if params change significantly.
    _perform_simulation_update_step() # Apply current delta with old params
    app_data["last_update_timestamp"] = time.time() # Reset timestamp for new params

    return jsonify({"success": True, "message": "Simulation parameters updated."})


def _perform_simulation_update_step(is_stopping=False):
    """Helper function to perform a single simulation update step."""
    if not app_data.get("simulation_running", False) and not is_stopping:
        return

    if not app_data.get("center_pivot") or not app_data.get("pivot_length") or app_data["pivot_length"] <= 0:
        app_data["simulation_running"] = False # Stop if config invalid
        return

    delta_t_real = time.time() - app_data['last_update_timestamp']
    if delta_t_real <= 0 and not is_stopping: # Avoid issues with time going backwards or no change
        return

    delta_t_simulated_effective = delta_t_real * app_data['time_acceleration']

    time_moved_this_step = 0.0

    if app_data['work_cycle_percentage'] == 0: # Always paused if 0%
        app_data['is_in_run_phase'] = False
    elif app_data['work_cycle_percentage'] == 100: # Always running if 100%
        app_data['is_in_run_phase'] = True
        time_moved_this_step = delta_t_simulated_effective
    else: # Work cycle logic for 1-99%
        total_cycle_duration_sec = 60.0 # Standard cycle time for percentage logic
        run_duration_sec = total_cycle_duration_sec * (app_data['work_cycle_percentage'] / 100.0)
        pause_duration_sec = total_cycle_duration_sec - run_duration_sec

        # Accumulate effective time into the current phase
        app_data['current_cycle_elapsed_sec'] += delta_t_simulated_effective

        if app_data['is_in_run_phase']:
            if app_data['current_cycle_elapsed_sec'] < run_duration_sec:
                time_moved_this_step = delta_t_simulated_effective
            else: # End of run phase
                time_moved_this_step = delta_t_simulated_effective - (app_data['current_cycle_elapsed_sec'] - run_duration_sec)
                if pause_duration_sec > 0:
                    app_data['is_in_run_phase'] = False
                app_data['current_cycle_elapsed_sec'] -= run_duration_sec # Rollover to next phase
        else: # Is in pause phase
            if app_data['current_cycle_elapsed_sec'] >= pause_duration_sec:
                # End of pause phase, switch to run
                app_data['is_in_run_phase'] = True
                app_data['current_cycle_elapsed_sec'] -= pause_duration_sec # Rollover to run phase
                # Any time rolled over into run phase contributes to movement
                time_moved_this_step = app_data['current_cycle_elapsed_sec'] if app_data['current_cycle_elapsed_sec'] < run_duration_sec else run_duration_sec
            # else, still in pause, time_moved_this_step remains 0

    if time_moved_this_step > 0 and app_data["selected_speed_mps"] > 0:
        # Angular speed in radians per second
        angular_speed_rad_per_sec = app_data['selected_speed_mps'] / app_data['pivot_length']
        angle_change_rad = angular_speed_rad_per_sec * time_moved_this_step
        angle_change_deg = math.degrees(angle_change_rad)

        if app_data['direction'] == "cw":
            app_data['current_angle_deg'] += angle_change_deg
        else: # ccw
            app_data['current_angle_deg'] -= angle_change_deg

        app_data['current_angle_deg'] = (app_data['current_angle_deg'] + 360) % 360

        center_lat, center_lon = app_data["center_pivot"]
        end_lat, end_lon = calculate_destination_point(center_lat, center_lon, app_data["pivot_length"], app_data["current_angle_deg"])
        app_data["end_pivot"] = [end_lat, end_lon]
        app_data["azimuth"] = app_data["current_angle_deg"] # Azimuth tracks the current angle
        app_data['elapsed_simulation_time_sec'] += time_moved_this_step

        # Add to swept path if angle changed enough or it's the first point after 0
        # Ensure that last_angle_added_to_sweep is initialized correctly (e.g. to 0 or -1 for first point)
        # The direction of sweep matters for angle comparison

        current_total_angle_from_start = app_data["current_angle_deg"]
        # Normalize last_angle_added_to_sweep to be comparable if it was -1
        last_added_norm = app_data["last_angle_added_to_sweep"] if app_data["last_angle_added_to_sweep"] != -1.0 else 0.0

        # Check if it's the first point to be added after the initial point at angle 0
        is_first_movement_point = (app_data["last_angle_added_to_sweep"] == 0.0 and len(app_data["swept_sector_points"]) == 1 and abs(current_total_angle_from_start) > 0.001)

        # Calculate angular distance moved since last point addition
        # This needs to handle wrap-around at 360 and direction
        angle_diff = 0
        if app_data['direction'] == 'cw':
            if current_total_angle_from_start >= last_added_norm:
                angle_diff = current_total_angle_from_start - last_added_norm
            else: # Wrapped around
                angle_diff = (360 - last_added_norm) + current_total_angle_from_start
        else: # ccw
            if current_total_angle_from_start <= last_added_norm:
                angle_diff = last_added_norm - current_total_angle_from_start
            else: # Wrapped around
                angle_diff = last_added_norm + (360 - current_total_angle_from_start)

        angle_diff = abs(angle_diff) # We care about magnitude of change

        if angle_diff >= SWEEP_ANGLE_RESOLUTION_DEG or is_first_movement_point:
            # If swept_sector_points is empty but current_angle is 0, it should have been initialized in start_simulation
            # This ensures we don't add the angle 0 point multiple times if simulation starts at 0 and doesn't move immediately.
            if not (abs(app_data["current_angle_deg"] - app_data["last_angle_added_to_sweep"]) < 0.001 and len(app_data["swept_sector_points"]) > 0 ):
                 app_data["swept_sector_points"].append([end_lat, end_lon])
                 app_data["last_angle_added_to_sweep"] = app_data["current_angle_deg"]


    app_data['last_update_timestamp'] = time.time()


@app.route('/get_simulation_update', methods=['GET'])
def get_simulation_update_endpoint():
    if app_data["simulation_running"]:
        _perform_simulation_update_step()

    return jsonify({
        "success": True,
        "simulation_running": app_data["simulation_running"],
        "end_pivot_coords": app_data.get("end_pivot"),
        "current_angle_deg": app_data.get("current_angle_deg"),
        "azimuth": app_data.get("azimuth"), # Redundant with current_angle_deg but for consistency
        "elapsed_simulation_time_sec": app_data.get("elapsed_simulation_time_sec"),
        "is_in_run_phase": app_data.get("is_in_run_phase"), # For UI feedback if needed
        "status_message": app_data.get("status_message")
    })

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