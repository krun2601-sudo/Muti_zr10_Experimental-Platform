#!/bin/bash
# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
# install_gst_dependencies.sh
# Convenience script to install system dependencies required for the GStreamer streaming backend
# and to build PyGObject / pycairo from source if needed.

set -e

echo "Updating package list..."
sudo apt-get update

echo "Installing GStreamer and build dependencies..."
sudo apt-get install -y \
    build-essential \
    pkg-config \
    python3-dev \
    libglib2.0-dev \
    libcairo2-dev \
    libgirepository1.0-dev \
    gstreamer1.0-tools \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    python3-gi \
    python3-gi-cairo \
    python3-gst-1.0 \
    gir1.2-gstreamer-1.0 \
    gir1.2-gst-plugins-base-1.0

echo "Dependencies installed successfully!"
