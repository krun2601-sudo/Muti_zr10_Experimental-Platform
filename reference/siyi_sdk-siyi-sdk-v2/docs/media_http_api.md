# Camera Media HTTP API

SIYI gimbal cameras expose a REST API on port **82** for browsing and downloading photos and videos stored on the TF card. This is separate from the binary UDP/TCP command protocol — it runs as a lightweight web server on the camera itself.

The SDK wraps this API in the `MediaClient` class.

## Connection details

| Property | Value |
|---|---|
| Default host | `192.168.144.25` |
| Port | `82` |
| Base URL | `http://192.168.144.25:82//cgi-bin/media.cgi` |
| Transport | HTTP/1.1, GET requests with query-string parameters |

No authentication is required.

## Quick start

```python
import asyncio
from siyi_sdk import MediaClient, MediaType

async def main() -> None:
    async with MediaClient("192.168.144.25") as media:
        # List photo directories
        dirs = await media.list_directories(MediaType.IMAGES)
        for d in dirs:
            count = await media.get_media_count(MediaType.IMAGES, d.path)
            print(f"{d.name}/  ({count} photos)")

        # Fetch the first 10 photos from the first directory
        if dirs:
            files = await media.list_files(MediaType.IMAGES, dirs[0].path, start=0, count=10)
            for f in files:
                print(f.name, "→", f.url)

asyncio.run(main())
```

## `MediaClient` API

```python
class MediaClient(host="192.168.144.25", port=82, timeout=5.0)
```

Async context manager. All methods are safe to `await` from any asyncio event loop — the underlying `urllib` calls run in a thread-pool executor.

### `list_directories(media_type) → list[MediaDirectory]`

Returns the date-based directories available on the camera for the given media type.

```python
dirs = await media.list_directories(MediaType.IMAGES)
# [MediaDirectory(name='20240630', path='photo/20240630'), ...]
```

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `media_type` | `MediaType` | `IMAGES` | `MediaType.IMAGES` or `MediaType.VIDEOS` |

**Returns** `list[MediaDirectory]` — each entry has `.name` (display name) and `.path` (pass to subsequent calls).

---

### `get_media_count(media_type, path="") → int`

Returns the number of files under `path`. Pass an empty string to get the total across all directories.

```python
total = await media.get_media_count(MediaType.IMAGES)
per_dir = await media.get_media_count(MediaType.IMAGES, "photo/20240630")
```

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `media_type` | `MediaType` | `IMAGES` | `MediaType.IMAGES` or `MediaType.VIDEOS` |
| `path` | `str` | `""` | Directory path from `list_directories`. Empty = all. |

**Returns** `int`

---

### `list_files(media_type, path="", start=0, count=50) → list[MediaFile]`

Returns a paginated slice of files under `path`.

```python
files = await media.list_files(MediaType.VIDEOS, "video/20240630", start=0, count=20)
for f in files:
    print(f.name, f.url)   # download directly via HTTP GET on f.url
```

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `media_type` | `MediaType` | `IMAGES` | `MediaType.IMAGES` or `MediaType.VIDEOS` |
| `path` | `str` | `""` | Directory path. Empty = all files of that type. |
| `start` | `int` | `0` | Zero-based start index. |
| `count` | `int` | `50` | Maximum files to return. Clamped to available files. |

**Returns** `list[MediaFile]` — each entry has `.name` (filename) and `.url` (direct download URL).

---

### `list_all_files(media_type, path="", page_size=50) → list[MediaFile]`

Convenience wrapper that auto-paginates `list_files` until all files are fetched.

```python
all_photos = await media.list_all_files(MediaType.IMAGES, "photo/20240630")
```

---

## Data models

### `MediaType`

```python
class MediaType(IntEnum):
    IMAGES = 0
    VIDEOS = 1
```

### `MediaDirectory`

```python
@dataclass(frozen=True)
class MediaDirectory:
    name: str   # e.g. "20240630"
    path: str   # e.g. "photo/20240630"
```

### `MediaFile`

```python
@dataclass(frozen=True)
class MediaFile:
    name: str   # e.g. "IMG_0042.jpg"
    url: str    # e.g. "http://192.168.144.25:82/photo/20240630/IMG_0042.jpg"
```

## Raw HTTP endpoints

The three endpoints below are what `MediaClient` calls internally. You can hit them directly with any HTTP client if needed.

### GET `/api/v1/getdirectories`

List date-based directories.

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `media_type` | int | `0` = images, `1` = videos |

**Example request**
```
GET http://192.168.144.25:82//cgi-bin/media.cgi/api/v1/getdirectories?media_type=0
```

**Example response**
```json
{
  "code": 200,
  "success": true,
  "data": {
    "media_type": 0,
    "directories": [
      { "name": "20240630", "path": "photo/20240630" },
      { "name": "20240701", "path": "photo/20240701" }
    ]
  }
}
```

---

### GET `/api/v1/getmediacount`

File count in a directory (or total).

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `media_type` | int | `0` = images, `1` = videos |
| `path` | string | Directory path, or empty string for total |

**Example request**
```
GET http://192.168.144.25:82//cgi-bin/media.cgi/api/v1/getmediacount?media_type=0&path=photo/20240630
```

**Example response**
```json
{
  "code": 200,
  "success": true,
  "data": {
    "media_type": 0,
    "count": 42,
    "path": "photo/20240630"
  }
}
```

---

### GET `/api/v1/getmedialist`

Paginated file list with direct download URLs.

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `media_type` | int | `0` = images, `1` = videos |
| `path` | string | Directory path, or empty string for all |
| `start` | int | Zero-based start index |
| `count` | int | Number of files to return |

**Example request**
```
GET http://192.168.144.25:82//cgi-bin/media.cgi/api/v1/getmedialist?media_type=0&path=photo/20240630&start=0&count=10
```

**Example response**
```json
{
  "code": 200,
  "success": true,
  "data": {
    "media_type": 0,
    "path": "photo/20240630",
    "list": [
      { "name": "IMG_0001.jpg", "url": "http://192.168.144.25:82/photo/20240630/IMG_0001.jpg" },
      { "name": "IMG_0002.jpg", "url": "http://192.168.144.25:82/photo/20240630/IMG_0002.jpg" }
    ]
  }
}
```

## Error handling

All methods raise `siyi_sdk.exceptions.TransportError` on failure — either an HTTP error from the camera (`4xx`) or a network-level failure (camera unreachable, timeout).

```python
from siyi_sdk.exceptions import TransportError

try:
    dirs = await media.list_directories(MediaType.IMAGES)
except TransportError as e:
    print(f"Could not reach camera media API: {e}")
```

## Downloading files

The `.url` field in each `MediaFile` is a standard HTTP URL. Download with any HTTP client:

```python
import urllib.request

for f in files:
    urllib.request.urlretrieve(f.url, f.name)
```

Or async with `aiohttp`:

```python
import aiohttp

async with aiohttp.ClientSession() as session:
    for f in files:
        async with session.get(f.url) as resp:
            data = await resp.read()
            with open(f.name, "wb") as fh:
                fh.write(data)
```
