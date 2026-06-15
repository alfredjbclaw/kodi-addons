"""Alfred Bridge — Kodi service addon that polls Mac Mini for commands."""

from datetime import datetime
import json

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib.alfred_client import AlfredClient
from resources.lib import manifest as manifest_lib

LOG_PREFIX = "[Alfred Bridge]"

_last_browse_result = None
_MANIFEST = None


def _get_manifest():
    global _MANIFEST
    if _MANIFEST is None:
        try:
            _MANIFEST = manifest_lib.load_manifest()
        except Exception as exc:
            xbmc.log("{} manifest load failed: {}".format(LOG_PREFIX, exc), level=xbmc.LOGWARNING)
            _MANIFEST = {"commands": {}}
    return _MANIFEST


def log(msg, level=xbmc.LOGINFO):
    xbmc.log("{} {}".format(LOG_PREFIX, msg), level=level)


def warn(msg):
    log(msg, xbmc.LOGWARNING)


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

def _format_time(seconds):
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    return "{:02d}:{:02d}:{:02d}".format(h, m, s)


def _get_volume_info():
    req = json.dumps({
        "jsonrpc": "2.0", "method": "Application.GetProperties",
        "params": {"properties": ["volume", "muted"]}, "id": 1
    })
    resp = json.loads(xbmc.executeJSONRPC(req))
    result = resp.get("result", {})
    return result.get("volume", 0), result.get("muted", False)


def gather_status(last_cmd_id):
    player = xbmc.Player()
    volume, muted = _get_volume_info()

    status = {
        "player_state": "idle",
        "volume": volume,
        "muted": muted,
        "last_command_id": last_cmd_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    try:
        if player.isPlaying():
            # Check pause state via Player.GetProperties
            req = json.dumps({
                "jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1
            })
            active = json.loads(xbmc.executeJSONRPC(req)).get("result", [])
            paused = False
            if active:
                pid = active[0]["playerid"]
                req2 = json.dumps({
                    "jsonrpc": "2.0", "method": "Player.GetProperties",
                    "params": {"playerid": pid, "properties": ["speed", "time", "totaltime"]},
                    "id": 1
                })
                props = json.loads(xbmc.executeJSONRPC(req2)).get("result", {})
                paused = props.get("speed", 1) == 0

                t = props.get("time", {})
                tt = props.get("totaltime", {})
                time_sec = t.get("hours", 0) * 3600 + t.get("minutes", 0) * 60 + t.get("seconds", 0)
                total_sec = tt.get("hours", 0) * 3600 + tt.get("minutes", 0) * 60 + tt.get("seconds", 0)
            else:
                time_sec = 0
                total_sec = 0

            status["player_state"] = "paused" if paused else "playing"
            status["now_playing"] = {
                "title": player.getPlayingFile(),
                "file": player.getPlayingFile(),
                "time": _format_time(time_sec),
                "total": _format_time(total_sec),
            }
            try:
                tag = player.getVideoInfoTag()
                if tag and tag.getTitle():
                    status["now_playing"]["title"] = tag.getTitle()
            except Exception:
                pass
    except Exception:
        pass

    if _last_browse_result is not None:
        status["browse_result"] = _last_browse_result

    return status


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------

INPUT_ACTIONS = {
    "up": "Input.Up", "down": "Input.Down",
    "left": "Input.Left", "right": "Input.Right",
    "select": "Input.Select", "back": "Input.Back",
    "home": "Input.Home",
}


def execute_command(cmd):
    name = cmd.get("command")
    raw_params = cmd.get("params", {}) or {}
    manifest = _get_manifest()
    try:
        params = manifest_lib.validate(manifest, name, raw_params)
    except manifest_lib.ValidationError as exc:
        warn("rejecting {}: {}".format(name, exc))
        return
    except Exception as exc:
        warn("manifest check failed ({}); falling through with raw params: {}".format(name, exc))
        params = manifest_lib.normalize_params(name, raw_params)
    player = xbmc.Player()

    if name == "play":
        filepath = params.get("file", "")
        if not filepath:
            warn("play command missing 'file' param")
            return
        resume_pos = params.get("resume_position_seconds")
        player.play(filepath)
        if resume_pos and int(resume_pos) > 0:
            target = int(resume_pos)
            for _ in range(20):
                xbmc.sleep(500)
                if player.isPlaying():
                    break
            try:
                req = json.dumps({
                    "jsonrpc": "2.0", "method": "Player.Seek",
                    "params": {
                        "playerid": 1,
                        "value": {
                            "hours": target // 3600,
                            "minutes": (target % 3600) // 60,
                            "seconds": target % 60,
                            "milliseconds": 0,
                        },
                    },
                    "id": 1,
                })
                xbmc.executeJSONRPC(req)
                log("Resumed to {}s".format(target))
            except Exception as e:
                warn("Resume seek failed: {}".format(e))

    elif name == "pause":
        player.pause()

    elif name == "stop":
        player.stop()

    elif name == "volume":
        level = params.get("level")
        if level is None:
            warn("volume command missing 'level' param")
            return
        req = json.dumps({
            "jsonrpc": "2.0", "method": "Application.SetVolume",
            "params": {"volume": int(level)}, "id": 1
        })
        xbmc.executeJSONRPC(req)

    elif name == "mute":
        mute_val = params.get("mute", True)
        req = json.dumps({
            "jsonrpc": "2.0", "method": "Application.SetMute",
            "params": {"mute": bool(mute_val)}, "id": 1
        })
        xbmc.executeJSONRPC(req)

    elif name == "notify":
        title = params.get("title", "Alfred")
        message = params.get("message", "")
        xbmcgui.Dialog().notification(title, message, xbmcgui.NOTIFICATION_INFO, 5000)

    elif name == "input":
        direction = params.get("action", "").lower()
        method = INPUT_ACTIONS.get(direction)
        if not method:
            warn("unknown input action: {}".format(direction))
            return
        req = json.dumps({"jsonrpc": "2.0", "method": method, "id": 1})
        xbmc.executeJSONRPC(req)

    elif name == "activate_window":
        window = params.get("window", "Home")
        xbmc.executebuiltin("ActivateWindow({})".format(window))

    elif name == "activate_addon":
        addon_id = params.get("addon_id", "")
        if not addon_id:
            warn("activate_addon missing addon_id param")
            return
        xbmc.executebuiltin("RunAddon({})".format(addon_id))

    elif name == "browse":
        path = params.get("path", "")
        if not path:
            warn("browse missing path param")
            return

        # Auto-detect media type
        if path.startswith("plugin://"):
            media_type = "video"
        elif path.startswith("music://"):
            media_type = "music"
        else:
            media_type = params.get("media", "files")

        req = json.dumps({
            "jsonrpc": "2.0",
            "method": "Files.GetDirectory",
            "params": {
                "directory": path,
                "media": media_type,
                "properties": ["title", "label", "file", "filetype", "playcount", "duration"]
            },
            "id": 1
        })
        resp = json.loads(xbmc.executeJSONRPC(req))
        if "result" in resp:
            items = resp["result"].get("files", [])
            global _last_browse_result
            _last_browse_result = {
                "path": path,
                "media": media_type,
                "items": [
                    {
                        "index": i,
                        "label": item.get("label", ""),
                        "title": item.get("title", ""),
                        "file": item.get("file", ""),
                        "filetype": item.get("filetype", "file"),
                        "duration": item.get("duration", 0)
                    }
                    for i, item in enumerate(items)
                ]
            }
            log("Browse {} ({}): {} items".format(path, media_type, len(items)))
        else:
            error_msg = resp.get("error", {}).get("message", "unknown")
            warn("Browse failed for {}: {}".format(path, error_msg))
            _last_browse_result = {"path": path, "error": error_msg, "items": []}

    elif name == "select_item":
        index = int(params.get("index", 0))
        file_path = params.get("file", "")

        if file_path:
            # Play directly by file path if provided
            xbmc.Player().play(file_path)
        else:
            # Navigate by index: go to top first, then move down
            xbmc.executeJSONRPC(json.dumps({
                "jsonrpc": "2.0", "method": "Input.ExecuteAction",
                "params": {"action": "firstpage"}, "id": 1
            }))
            xbmc.sleep(300)
            for _ in range(index):
                xbmc.executeJSONRPC(json.dumps({
                    "jsonrpc": "2.0", "method": "Input.Down", "id": 1
                }))
                xbmc.sleep(150)
            xbmc.sleep(200)
            xbmc.executeJSONRPC(json.dumps({
                "jsonrpc": "2.0", "method": "Input.Select", "id": 1
            }))

    elif name == "flixify_search":
        query = params.get("q", "")
        if not query:
            warn("flixify_search missing q param")
            return
        from urllib.parse import quote_plus
        encoded = quote_plus(query)
        url = "plugin://flixify.com/items?act=search&q={}&url=%2Fsearch".format(encoded)
        xbmc.executebuiltin("RunPlugin({})".format(url))
        log("Searching Flixify for: {}".format(query))

    elif name == "flixify_play":
        item_id = params.get("id", "")
        item_url = params.get("url", "")
        if not item_id:
            warn("flixify_play missing id param")
            return
        from urllib.parse import quote_plus
        if item_url:
            play_url = "plugin://flixify.com/play?id={}&url={}&video=1".format(item_id, quote_plus(item_url))
        else:
            play_url = "plugin://flixify.com/play?id={}&video=1".format(item_id)
        xbmc.Player().play(play_url)
        log("Playing Flixify item: {} url: {}".format(item_id, item_url))

    elif name == "seek":
        # params: {"time": "01:23:45"} or {"seconds": 5025}
        time_str = params.get("time", "")
        seconds = params.get("seconds", None)
        if time_str:
            parts = time_str.split(":")
            if len(parts) == 3:
                seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                seconds = int(parts[0]) * 60 + int(parts[1])
        if seconds is not None:
            req = json.dumps({
                "jsonrpc": "2.0",
                "method": "Player.Seek",
                "params": {
                    "playerid": 1,
                    "value": {
                        "time": {
                            "hours": int(seconds) // 3600,
                            "minutes": (int(seconds) % 3600) // 60,
                            "seconds": int(seconds) % 60,
                            "milliseconds": 0
                        }
                    }
                },
                "id": 1
            })
            xbmc.executeJSONRPC(req)
            log("Seeked to {}s".format(seconds))
        else:
            warn("seek: no valid time or seconds provided")

    elif name == "step":
        direction = params.get("direction", "forward")  # "forward" or "backward"
        step_seconds = int(params.get("seconds", 30))

        # Get current position
        active_req = json.dumps({"jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1})
        active = json.loads(xbmc.executeJSONRPC(active_req)).get("result", [])
        if not active:
            warn("step: no active player")
            return
        pid = active[0]["playerid"]
        props_req = json.dumps({
            "jsonrpc": "2.0", "method": "Player.GetProperties",
            "params": {"playerid": pid, "properties": ["time", "totaltime"]}, "id": 1
        })
        props = json.loads(xbmc.executeJSONRPC(props_req)).get("result", {})
        t = props.get("time", {})
        current_sec = t.get("hours", 0) * 3600 + t.get("minutes", 0) * 60 + t.get("seconds", 0)

        if direction == "forward":
            new_sec = current_sec + step_seconds
        else:
            new_sec = max(0, current_sec - step_seconds)

        seek_req = json.dumps({
            "jsonrpc": "2.0", "method": "Player.Seek",
            "params": {
                "playerid": pid,
                "value": {
                    "time": {
                        "hours": new_sec // 3600,
                        "minutes": (new_sec % 3600) // 60,
                        "seconds": new_sec % 60,
                        "milliseconds": 0
                    }
                }
            },
            "id": 1
        })
        xbmc.executeJSONRPC(seek_req)
        log("Stepped {} {}s from {}s to {}s".format(direction, step_seconds, current_sec, new_sec))

    elif name == "set_speed":
        speed = int(params.get("speed", 1))  # 1=normal, 2=2x, -1=reverse, etc.
        active_req = json.dumps({"jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1})
        active = json.loads(xbmc.executeJSONRPC(active_req)).get("result", [])
        if not active:
            warn("set_speed: no active player")
            return
        pid = active[0]["playerid"]
        req = json.dumps({
            "jsonrpc": "2.0", "method": "Player.SetSpeed",
            "params": {"playerid": pid, "speed": speed},
            "id": 1
        })
        xbmc.executeJSONRPC(req)
        log("Set playback speed to {}x".format(speed))

    else:
        warn("unknown command: {}".format(name))


# ---------------------------------------------------------------------------
# Main service loop
# ---------------------------------------------------------------------------

def main():
    monitor = xbmc.Monitor()
    addon = xbmcaddon.Addon()

    host = addon.getSetting("alfred_host")
    port = addon.getSetting("alfred_port") or "8765"
    public_hostname = (addon.getSetting("public_hostname") or "").strip()
    use_https = (addon.getSetting("use_https_for_public") or "true").lower() == "true"
    prefer_public = (addon.getSetting("prefer_public") or "false").lower() == "true"
    token = addon.getSetting("auth_token")
    poll_interval = int(addon.getSetting("poll_interval") or "2")

    if not host or not token:
        warn("Host or token not configured — exiting.")
        xbmcgui.Dialog().notification(
            "Alfred Bridge", "Configure host & token in addon settings",
            xbmcgui.NOTIFICATION_WARNING, 5000
        )
        return

    local_base = "http://{}:{}".format(host, port)
    public_base = None
    if public_hostname:
        scheme = "https" if use_https else "http"
        public_base = "{}://{}".format(scheme, public_hostname)

    if public_base and prefer_public:
        bases = [public_base, local_base]
    elif public_base:
        bases = [local_base, public_base]
    else:
        bases = [local_base]

    client = AlfredClient(bases, token)
    last_cmd_id = None
    consecutive_failures = 0
    current_interval = poll_interval

    log("Started — bases={} every {}s".format(bases, poll_interval))

    while not monitor.abortRequested():
        try:
            # Poll for command
            cmd = client.get_command()
            if cmd and cmd.get("command"):
                cmd_id = cmd.get("id")
                log("Received command: {} (id={})".format(cmd["command"], cmd_id))
                try:
                    execute_command(cmd)
                    last_cmd_id = cmd_id
                except Exception as exc:
                    warn("Error executing {}: {}".format(cmd["command"], exc))

            # Report status
            try:
                status = gather_status(last_cmd_id)
                client.post_status(status)
            except Exception as exc:
                warn("Error gathering/posting status: {}".format(exc))

            # Reset backoff on success
            consecutive_failures = 0
            current_interval = poll_interval

        except Exception as exc:
            consecutive_failures += 1
            warn("Network error (attempt {}): {}".format(consecutive_failures, exc))
            if consecutive_failures >= 3:
                current_interval = min(current_interval * 2, 30)
                log("Backing off to {}s interval".format(current_interval))

        if monitor.waitForAbort(current_interval):
            break

    log("Shutting down.")


if __name__ == "__main__":
    main()
