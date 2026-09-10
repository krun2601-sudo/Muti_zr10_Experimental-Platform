/**
 * SIYI SDK Web UI Frontend Logic
 */

class SiyiApp {
    constructor() {
        this.ws = null;
        this.joystickActive = false;
        this.currentPath = "";
        this.currentMediaMode = 0; // 0: Images, 1: Videos
        this.liveViewEnabled = true;
        this.isCameraConnected = false;
        this.isRebooting = false;
        this.theme = localStorage.getItem('theme') || 'dark';

        this.init();
    }

    async init() {
        console.log("SiyiApp: Initializing...");
        try {
            this.initTheme();
            this.liveViewEnabled = localStorage.getItem('liveViewEnabled') !== 'false';
            document.getElementById('config-live-view-toggle').checked = this.liveViewEnabled;
            
            console.log("SiyiApp: Binding events...");
            this.bindEvents();
            
            console.log("SiyiApp: Setting up joystick...");
            this.setupJoystick();
            
            console.log("SiyiApp: Connecting WebSocket...");
            this.connectWS();
            
            // Start proactive connection monitoring
            console.log("SiyiApp: Starting connection monitor...");
            setInterval(() => this.checkConnection(), 3000);
            
            // Initial load
            this.restoreUI();
            console.log("SiyiApp: Initialization complete.");
        } catch (e) {
            console.error("SiyiApp: Initialization crashed!", e);
        }
    }

    initTheme() {
        console.log(`initTheme: Applying '${this.theme}' mode`);
        this.applyTheme();
    }

    applyTheme() {
        if (this.theme === 'light') {
            document.body.classList.add('light-mode');
            const icon = document.querySelector('#theme-toggle-btn i');
            if (icon) {
                icon.className = 'fas fa-sun';
            }
        } else {
            document.body.classList.remove('light-mode');
            const icon = document.querySelector('#theme-toggle-btn i');
            if (icon) {
                icon.className = 'fas fa-moon';
            }
        }
        localStorage.setItem('theme', this.theme);
    }

    toggleTheme() {
        this.theme = this.theme === 'dark' ? 'light' : 'dark';
        this.applyTheme();
    }

    async restoreUI() {
        if (!this.isCameraConnected) {
            console.log("restoreUI skipped: Camera not connected");
            return;
        }
        
        console.log("Restoring UI components...");
        try {
            await this.loadSystemInfo();
        } catch (e) {
            console.warn("Failed to load system info", e);
        }
        
        try {
            await this.loadMedia();
        } catch (e) {
            console.warn("Failed to load media", e);
        }
        
        try {
            this.updateLiveView();
        } catch (e) {
            console.warn("Failed to update live view", e);
        }
    }

    async checkConnection() {
        try {
            const info = await this.get('/api/config/ip');
            if (!info) {
                console.warn("checkConnection: No response from server");
                this.isCameraConnected = false;
            } else {
                const wasConnected = this.isCameraConnected;
                this.isCameraConnected = info.connected || false;

                const overlay = document.getElementById('offline-overlay');
                const title = document.getElementById('overlay-title');
                const msg = document.getElementById('overlay-msg');
                const indicator = document.getElementById('connection-indicator');
                const statusText = document.getElementById('camera-status');

                if (this.isRebooting) {
                    overlay.classList.add('active');
                    title.innerText = "CAMERA REBOOTING";
                    msg.innerText = "Waiting for thermal and system initialization...";
                    indicator.className = 'indicator offline';
                    statusText.innerText = 'REBOOTING...';
                } else if (!this.isCameraConnected) {
                    overlay.classList.add('active');
                    title.innerText = "CAMERA OFFLINE";
                    msg.innerText = "Connection lost. Checking camera status...";
                    indicator.className = 'indicator';
                    statusText.innerText = 'OFFLINE';
                }

                if (this.isCameraConnected) {
                    overlay.classList.remove('active');
                    indicator.className = 'indicator online';
                    statusText.innerText = 'CONNECTED';
                    if (!wasConnected || this.isRebooting) {
                        this.isRebooting = false;
                        console.log("Camera recovery detected. Restoring UI...");
                        this.restoreUI();
                    }
                }
            }
        } catch (e) {
            console.error("Connection check failed", e);
        }
    }

    updateLiveView() {
        const stream = document.getElementById('video-stream');
        const container = stream.parentElement;
        if (this.liveViewEnabled) {
            container.style.display = 'flex';
            stream.src = '/api/stream/video';
            this.post('/api/stream/toggle', null, {enabled: true});
        } else {
            container.style.display = 'none';
            stream.src = '';
            this.post('/api/stream/toggle', null, {enabled: false});
        }
        localStorage.setItem('liveViewEnabled', this.liveViewEnabled);
    }

    bindEvents() {
        // Modals
        document.getElementById('open-config-btn').onclick = () => document.getElementById('config-modal').classList.add('active');
        document.getElementById('close-config-btn').onclick = () => document.getElementById('config-modal').classList.remove('active');
        document.getElementById('save-config-btn').onclick = () => this.saveConfig();

        // Control Buttons
        document.getElementById('photo-btn').onclick = () => this.post('/api/camera/photo');
        document.getElementById('record-btn').onclick = () => this.toggleRecord();
        document.getElementById('center-btn').onclick = () => this.post('/api/gimbal/center');
        
        document.getElementById('zoom-in-btn').onmousedown = () => this.post('/api/camera/zoom', null, {direction: 1});
        document.getElementById('zoom-in-btn').onmouseup = () => this.post('/api/camera/zoom', null, {direction: 0});
        document.getElementById('zoom-out-btn').onmousedown = () => this.post('/api/camera/zoom', null, {direction: -1});
        document.getElementById('zoom-out-btn').onmouseup = () => this.post('/api/camera/zoom', null, {direction: 0});
        
        document.getElementById('focus-near-btn').onmousedown = () => this.post('/api/camera/focus', null, {direction: 1});
        document.getElementById('focus-near-btn').onmouseup = () => this.post('/api/camera/focus', null, {direction: 0});
        document.getElementById('focus-far-btn').onmousedown = () => this.post('/api/camera/focus', null, {direction: -1});
        document.getElementById('focus-far-btn').onmouseup = () => this.post('/api/camera/focus', null, {direction: 0});

        document.getElementById('refresh-media-btn').onclick = () => this.loadMedia();

        // Media Tabs
        document.getElementById('media-tab-img').onclick = () => this.setMediaMode(0);
        document.getElementById('media-tab-vid').onclick = () => this.setMediaMode(1);

        document.getElementById('format-sd-btn').onclick = () => this.formatSD();

        document.getElementById('reboot-camera-btn').onclick = () => this.reboot(true, false);
        document.getElementById('reboot-gimbal-btn').onclick = () => this.reboot(false, true);

        document.getElementById('theme-toggle-btn').onclick = () => this.toggleTheme();

        // Header Toggles
        document.getElementById('config-live-view-toggle').onchange = (e) => {
            this.liveViewEnabled = e.target.checked;
            this.updateLiveView();
        };
    }

    async reboot(camera, gimbal) {
        const target = camera && gimbal ? "Camera & Gimbal" : (camera ? "Camera" : "Gimbal");
        const confirmed = confirm(`Are you sure you want to SOFT REBOOT the ${target}? This will temporarily interrupt connectivity.`);
        if (!confirmed) return;

        try {
            const res = await this.post('/api/system/reboot', {camera, gimbal});
            if (res?.status === 'ok') {
                alert(`${target} reboot command sent successfully.`);
                if (camera) {
                    this.isRebooting = true;
                    this.isCameraConnected = false;
                    this.updateLiveView(); // Stop stream locally
                }
            } else {
                throw new Error("Reboot command failed");
            }
        } catch (e) {
            console.error("Reboot failure", e);
            alert("Error: " + e.message);
        }
    }

    async formatSD() {
        const confirmed = confirm("WARNING: This will permanently erase ALL photos and videos on the SD card. This action cannot be undone. Are you sure you want to proceed?");
        if (!confirmed) return;

        try {
            const res = await this.post('/api/storage/format');
            if (res?.status === 'ok') {
                alert("SD card formatted successfully!");
                this.loadMedia(); // Refresh to show empty state
            } else {
                throw new Error("Format failed");
            }
        } catch (e) {
            console.error("Format failure", e);
            alert("Error: " + e.message);
        }
    }

    setMediaMode(mode) {
        this.currentMediaMode = mode;
        document.getElementById('media-tab-img').classList.toggle('active', mode === 0);
        document.getElementById('media-tab-vid').classList.toggle('active', mode === 1);
        this.loadMedia();
    }

    async post(url, body = {}, params = {}) {
        const queryParams = new URLSearchParams(params).toString();
        const fullUrl = queryParams ? `${url}?${queryParams}` : url;
        try {
            const resp = await fetch(fullUrl, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: body ? JSON.stringify(body) : null
            });
            return await resp.json();
        } catch (e) {
            console.error("POST failed", e);
        }
    }

    async get(url, params = {}) {
        const queryParams = new URLSearchParams(params).toString();
        const fullUrl = queryParams ? `${url}?${queryParams}` : url;
        try {
            const resp = await fetch(fullUrl);
            return await resp.json();
        } catch (e) {
            console.error("GET failed", e);
        }
    }

    async saveConfig() {
        const ip = document.getElementById('config-ip-input').value;
        const resValue = document.getElementById('config-res-select').value;
        
        try {
            if (ip) {
                const res = await this.post('/api/config/ip', {ip});
                if (res?.status === 'ok') {
                    document.getElementById('camera-ip-display').innerText = ip;
                }
            }

            if (resValue) {
                const res = await this.post('/api/camera/encoding', {resolution: resValue});
                if (res?.status !== 'ok') {
                    throw new Error(res?.detail || "Failed to set encoding");
                }
            }

            // Give the camera a moment to apply settings
            await new Promise(r => setTimeout(r, 2000));
            
            document.getElementById('config-modal').classList.remove('active');
            // Reload stream
            if (this.liveViewEnabled) {
                document.getElementById('video-stream').src = `/api/stream/video?t=${Date.now()}`;
            }
            await this.loadSystemInfo();
            
            alert("Settings saved successfully!");
        } catch (e) {
            console.error("Save config failed", e);
            alert("Failed to save settings: " + e.message);
        }
    }

    async toggleRecord() {
        await this.post('/api/camera/record');
        const badge = document.getElementById('recording-badge');
        badge.style.display = badge.style.display === 'none' ? 'block' : 'none';
        document.getElementById('record-btn').classList.toggle('btn-danger');
    }

    setupJoystick() {
        const zone = document.getElementById('joystick-zone');
        const handle = document.getElementById('joystick-handle');
        const rect = zone.getBoundingClientRect();
        const center = {x: rect.width / 2, y: rect.height / 2};
        
        let moveInterval = null;
        let lastVel = {yaw: 0, pitch: 0};
        let rotatePending = false;

        const handleMove = (e) => {
            if (!this.joystickActive) return;
            
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const clientY = e.touches ? e.touches[0].clientY : e.clientY;
            
            let dx = clientX - rect.left - center.x;
            let dy = clientY - rect.top - center.y;
            
            const dist = Math.min(60, Math.sqrt(dx*dx + dy*dy));
            const angle = Math.atan2(dy, dx);
            
            const posX = Math.cos(angle) * dist;
            const posY = Math.sin(angle) * dist;
            
            handle.style.left = `calc(50% + ${posX}px)`;
            handle.style.top = `calc(50% + ${posY}px)`;
            
            // Normalize velocity to -100 to 100
            lastVel = {
                yaw: Math.round((posX / 60) * 100),
                pitch: Math.round(-(posY / 60) * 100)
            };
        };

        const startMove = (e) => {
            this.joystickActive = true;
            handleMove(e);
            moveInterval = setInterval(async () => {
                if (rotatePending) return;
                if (lastVel.yaw !== 0 || lastVel.pitch !== 0) {
                    rotatePending = true;
                    try {
                        await this.post('/api/gimbal/rotate', lastVel);
                    } finally {
                        rotatePending = false;
                    }
                }
            }, 100);
        };

        const stopMove = async () => {
            this.joystickActive = false;
            clearInterval(moveInterval);
            handle.style.left = '50%';
            handle.style.top = '50%';
            lastVel = {yaw: 0, pitch: 0};
            rotatePending = true;
            try {
                await this.post('/api/gimbal/rotate', lastVel);
            } finally {
                rotatePending = false;
            }
        };

        zone.addEventListener('mousedown', startMove);
        window.addEventListener('mousemove', handleMove);
        window.addEventListener('mouseup', stopMove);
        
        zone.addEventListener('touchstart', startMove);
        window.addEventListener('touchmove', handleMove);
        window.addEventListener('touchend', stopMove);
    }

    connectWS() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${window.location.host}/ws/attitude`);
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const yawEl = document.getElementById('att-yaw');
                const pitchEl = document.getElementById('att-pitch');
                const rollEl = document.getElementById('att-roll');
                if (yawEl) yawEl.innerText = data.yaw.toFixed(1);
                if (pitchEl) pitchEl.innerText = data.pitch.toFixed(1);
                if (rollEl) rollEl.innerText = data.roll.toFixed(1);
            } catch (e) {
                console.error("WS Message Error", e);
            }
        };

        this.ws.onclose = () => {
            setTimeout(() => this.connectWS(), 2000);
            document.getElementById('connection-indicator').className = 'indicator';
            document.getElementById('camera-status').innerText = 'RECONNECTING...';
        };

        this.ws.onopen = () => {
            document.getElementById('connection-indicator').className = 'indicator online';
            document.getElementById('camera-status').innerText = 'CONNECTED';
        };
    }

    async loadSystemInfo() {
        console.log("loadSystemInfo: Fetching info...");
        // Fetch encoding info
        const encData = await this.get('/api/camera/encoding');
        if (encData && !encData.detail) {
            const resEl = document.getElementById('info-resolution');
            const bitEl = document.getElementById('info-bitrate');
            const fpsEl = document.getElementById('info-fps');
            if (resEl) resEl.innerText = encData.resolution || "---";
            if (bitEl) bitEl.innerText = `${encData.bitrate_kbps} kbps`;
            if (fpsEl) fpsEl.innerText = encData.frame_rate || "---";
        }

        // Fetch hardware and firmware info
        const sysInfo = await this.get('/api/system/info');
        if (sysInfo && !sysInfo.detail) {
            const camTypeEl = document.getElementById('info-camera-type');
            const camFwEl = document.getElementById('info-camera-fw');
            const gimFwEl = document.getElementById('info-gimbal-fw');
            if (camTypeEl) camTypeEl.innerText = sysInfo.camera_type || "---";
            if (camFwEl) camFwEl.innerText = sysInfo.camera_fw || "---";
            if (gimFwEl) gimFwEl.innerText = sysInfo.gimbal_fw || "---";
        }
    }

    async loadMedia() {
        const grid = document.getElementById('media-grid');
        grid.innerHTML = '<div class="media-thumb"><i class="fas fa-spinner fa-spin"></i></div>';
        document.getElementById('media-path-breadcrumb').innerText = this.currentMediaMode === 0 ? "/root/photo" : "/root/video";
        
        // Load directories
        const dirs = await this.get('/api/media/directories', {type: this.currentMediaMode});
        if (!dirs || dirs.length === 0) {
            grid.innerHTML = '<div class="overlay-card" style="grid-column: 1/-1; text-align: center;">No media found</div>';
            return;
        }

        grid.innerHTML = '';
        for(const dir of dirs) {
            const el = document.createElement('div');
            el.className = 'media-card';
            el.innerHTML = `
                <div class="media-thumb"><i class="fas fa-folder fa-2x"></i></div>
                <div class="media-info">
                    <div class="media-name">${dir.name}</div>
                </div>
            `;
            el.onclick = () => this.openDirectory(dir.path);
            grid.appendChild(el);
        }
    }

    async openDirectory(path) {
        this.currentPath = path;
        document.getElementById('media-path-breadcrumb').innerText = path;
        const grid = document.getElementById('media-grid');
        grid.innerHTML = '<div class="media-thumb"><i class="fas fa-spinner fa-spin"></i></div>';

        const files = await this.get('/api/media/files', {path, type: this.currentMediaMode});
        grid.innerHTML = '';
        
        // Add back button
        const back = document.createElement('div');
        back.className = 'media-card';
        back.innerHTML = `
            <div class="media-thumb"><i class="fas fa-arrow-left fa-2x"></i></div>
            <div class="media-info"><div class="media-name">Back</div></div>
        `;
        back.onclick = () => this.loadMedia();
        grid.appendChild(back);

        if (!files) return;

        const icon = this.currentMediaMode === 0 ? "fa-file-image" : "fa-file-video";

        for(const file of files) {
            const el = document.createElement('div');
            el.className = 'media-card';
            el.innerHTML = `
                <div class="media-thumb"><i class="fas ${icon} fa-2x"></i></div>
                <div class="media-info">
                    <div class="media-name">${file.name}</div>
                    <a href="/api/media/download?url=${encodeURIComponent(file.url)}" target="_blank" class="btn btn-sm btn-primary" style="margin-top: 10px; width: 100%;">Download</a>
                </div>
            `;
            grid.appendChild(el);
        }
    }
}

window.onload = () => new SiyiApp();
