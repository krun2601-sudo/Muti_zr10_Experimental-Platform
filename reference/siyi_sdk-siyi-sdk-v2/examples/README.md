# Examples

Runnable scripts that demonstrate every major feature of the SDK.
All examples connect over UDP to the default SIYI address (`192.168.144.25:37260`).
Change the host/port as needed for your setup.

## Prerequisites

Install the SDK and any optional dependencies you need:

```bash
pip install -e ..                          # core SDK
pip install -e "..[stream-opencv]"         # add if running RTSP examples
```

Run any example with:

```bash
python examples/<script>.py
```

---

## Gimbal Control

### `udp_heartbeat.py`
Connects over UDP, reads the firmware version, and prints the current gimbal attitude. The
simplest possible sanity check to verify connectivity.

### `set_attitude.py`
Moves the gimbal to an absolute yaw/pitch position (yaw=30°, pitch=−45°), waits, then
returns to centre with one-key centering.

### `gimbal_rotation.py`
Drives the gimbal continuously using speed commands: pan right, stop, tilt down, stop, then
centre. Demonstrates `rotate(yaw, pitch)` with values in the −100…+100 speed range.

### `gimbal_modes.py`
Queries the current gimbal motion mode and then cycles through **Lock → Follow → FPV → Lock**
using `capture(CaptureFuncType.*)`. Prints the mode reported by the gimbal after each switch.

### `single_axis_control.py`
Moves yaw and pitch independently with `set_single_axis()` so one axis can be repositioned
without disturbing the other. Ends with a centering command.

### `gimbal_scan.py`
Performs an automated sweep scan: switches to lock mode, then steps the yaw from −60° to
+60° in seven increments while holding pitch at −20°. Useful as a starting point for survey
or search patterns.

---

## Camera & Optics

### `zoom_control.py`
Queries the zoom range, performs a timed manual zoom-in, stops, jumps to 5× with an absolute
zoom command, reads back the current zoom, then resets to 1×.

### `focus_control.py`
Triggers auto focus at a touch-point (centre of a 1280×720 frame), sweeps manual focus
towards far and near for half a second each, then re-engages auto focus.

### `camera_capture.py`
Registers a function-feedback callback, takes a still photo, starts a 3-second video
recording, and stops it. Prints every feedback event the gimbal sends back.

### `encoding_params.py`
Reads the encoding parameters (codec, resolution, bitrate, frame rate) for the recording,
main, and sub streams, then updates the main stream to H.264 1280×720 at 4 Mbps/30 fps and
verifies the change.

---

## Thermal Imaging

### `thermal_spot_temperature.py`
Reads the temperature at a single pixel (640, 360) with one measurement call.

### `thermal_imaging.py`
Cycles through the Ironbow, Rainbow, and White-Hot pseudo-color palettes, restores the
original, measures spot temperature at the frame centre, and prints the global
min/max temperatures with their pixel coordinates and the current thermal gain setting.

---

## Laser Ranging

### `laser_ranging.py`
Enables the laser rangefinder, polls the distance once per second for five seconds, prints
each reading (or "out of range" when the sensor reports no valid target), then disables the
laser.

---

## Attitude Streaming

### `subscribe_attitude_stream.py`
Subscribes to the gimbal attitude push stream at 10 Hz, prints yaw and pitch for 5 seconds
via a callback, then unsubscribes and turns the stream off.

---

## System Information

### `system_info.py`
Prints a full system snapshot in one shot:
- Camera model name (ZR10, ZR30, A8 mini, etc.) decoded from the hardware ID
- Firmware version (camera / gimbal / zoom)
- Hardware ID (raw hex)
- System time (UNIX µs + boot ms)
- Gimbal system info (laser state)
- Camera system info (recording state, motion mode, mounting direction, HDMI/CVBS output)
- Network configuration (IP, subnet mask, gateway)

### `soft_reboot.py`
Sends a soft-reboot command to the camera and/or gimbal module and prints the acknowledgment.
Pass `--camera` and/or `--gimbal` flags to select which module to reboot:

```bash
python examples/soft_reboot.py --camera           # reboot camera only
python examples/soft_reboot.py --gimbal           # reboot gimbal only
python examples/soft_reboot.py --camera --gimbal  # reboot both
```

---

## Video Streaming (RTSP)

These examples require the `stream-opencv` or `stream-gst` extras.

### `rtsp_opencv_new_gen.py`
Displays the main RTSP stream from a **new-generation** SIYI camera (ZT30, ZT6, ZR30, ZR10)
using the OpenCV backend.

### `rtsp_opencv_old_gen.py`
Same as above but targets **old-generation** cameras (A8 mini, A2 mini) whose stream URL
differs.

### `rtsp_gstreamer.py`
Uses the GStreamer backend instead of OpenCV for lower-latency display of the main stream.

### `rtsp_sub_stream.py`
Opens the **sub stream** (lower-resolution) alongside the main stream using the OpenCV
backend.

### `rtsp_record.py`
Records the RTSP stream to an MP4 file on disk while displaying it in a window.

### `rtsp_with_control.py`
Combines live RTSP display with gimbal control: streams video from the camera while
simultaneously rotating the gimbal and printing attitude data, showing how to use the SDK's
async API and video streaming together.

---

## Default Connection Parameters

| Parameter | Default |
|-----------|---------|
| Host | `192.168.144.25` |
| UDP port | `37260` |
| TCP port | `37260` |

Change these at the top of each script or pass them as arguments if you adapt the examples
for your own application.
