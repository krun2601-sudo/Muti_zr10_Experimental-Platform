# SIYI Web UI

The SIYI Web UI is a modern, responsive web interface for controlling SIYI gimbal cameras and managing media on the SD card.

## Features

- **Live Video**: Proxied MJPEG stream from the camera's RTSP source.
- **Gimbal Control**: 
    - Virtual joystick for velocity control.
    - One-key centering.
    - Real-time attitude readout (Yaw, Pitch, Roll).
- **Camera Control**:
    - Take photos.
    - Start/Stop video recording.
    - Manual Zoom and Focus control.
    - Touch-to-focus (via UI coordinates).
- **Media Management**:
    - Browse date-based directories.
    - List image and video files.
    - Direct download links for media files.
- **Configuration**:
    - Change camera IP address on-the-fly.
    - View and modify encoding parameters.

## Prerequisites

Before running the Web UI, ensure you have the necessary system dependencies for GStreamer (if using the GStreamer backend for video):

```bash
sudo ./install_gst_dependencies.sh
```

## Installation

Install the SDK with web dependencies:

```bash
pip install -e ".[web]"
```

## Running the Server

Start the FastAPI backend:

```bash
python -m web_ui.server
```

By default, the server runs on **port 8082**. Access it at:
`http://localhost:8082`

## Architecture

- **Backend**: FastAPI (Python). It uses `SIYIClient` for commands and `MediaClient` for SD card access.
- **Frontend**: Vanilla HTML5, CSS3, and JavaScript (ES6+).
- **Communication**:
    - **REST API**: For discrete commands and configuration.
    - **WebSockets**: For real-time attitude data at 10Hz.
    - **MJPEG**: For live video streaming in the browser without requiring external plugins.

## Configuration

You can change the camera IP directly from the UI by clicking the gear icon in the header. This will re-initialize the SDK clients without restarting the server.
