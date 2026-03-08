"""
MPRIS D-Bus bridge for controlling Bluetooth media playback.

Connects to the session bus and finds the Bluetooth media player
exposed by mpris-proxy (bluez AVRCP → MPRIS bridge).
"""

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

try:
    import dbus
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False
    log.warning("dbus module not available; MPRIS bridge will use stubs")


@dataclass
class TrackInfo:
    title: str = "Unknown"
    artist: str = "Unknown"
    album: str = "Unknown"
    duration_ms: int = 0


class PlaybackStatus:
    STOPPED = 0
    PLAYING = 1
    PAUSED = 2


class MprisBridge:
    """Interface to a Bluetooth media player via MPRIS D-Bus."""

    MPRIS_PATH = "/org/mpris/MediaPlayer2"
    MPRIS_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
    DBUS_PROPS_IFACE = "org.freedesktop.DBus.Properties"
    MPRIS_PREFIX = "org.mpris.MediaPlayer2."

    def __init__(self):
        self._bus = None
        self._player_name = None
        self._player = None
        self._props = None
        if HAS_DBUS:
            try:
                self._bus = dbus.SessionBus()
                log.info("Connected to D-Bus session bus")
            except Exception as e:
                log.error("Failed to connect to D-Bus: %s", e)

    def _find_player(self) -> bool:
        """Find an MPRIS media player on the bus (preferring bluez/BT)."""
        if not self._bus:
            return False
        try:
            bus_obj = self._bus.get_object(
                "org.freedesktop.DBus", "/org/freedesktop/DBus")
            names = bus_obj.ListNames(
                dbus_interface="org.freedesktop.DBus")
            mpris_names = [
                str(n) for n in names if str(n).startswith(self.MPRIS_PREFIX)
            ]
            if not mpris_names:
                return False
            # Prefer a bluez/bluetooth player
            bt_names = [n for n in mpris_names if "bluez" in n.lower()]
            chosen = bt_names[0] if bt_names else mpris_names[0]
            if chosen != self._player_name:
                log.info("Using MPRIS player: %s", chosen)
                self._player_name = chosen
                obj = self._bus.get_object(chosen, self.MPRIS_PATH)
                self._player = dbus.Interface(
                    obj, self.MPRIS_PLAYER_IFACE)
                self._props = dbus.Interface(
                    obj, self.DBUS_PROPS_IFACE)
            return True
        except Exception as e:
            log.debug("Error finding MPRIS player: %s", e)
            self._player_name = None
            self._player = None
            self._props = None
            return False

    def _get_prop(self, prop: str):
        """Get a property from the MPRIS Player interface."""
        if not self._props:
            return None
        try:
            return self._props.Get(self.MPRIS_PLAYER_IFACE, prop)
        except Exception as e:
            log.debug("Error getting property %s: %s", prop, e)
            return None

    def get_status(self) -> int:
        """Get playback status as an iAP-compatible integer."""
        if not self._find_player():
            return PlaybackStatus.STOPPED
        status = self._get_prop("PlaybackStatus")
        if status == "Playing":
            return PlaybackStatus.PLAYING
        elif status == "Paused":
            return PlaybackStatus.PAUSED
        return PlaybackStatus.STOPPED

    def get_position_ms(self) -> int:
        """Get current playback position in milliseconds."""
        if not self._find_player():
            return 0
        pos = self._get_prop("Position")
        if pos is not None:
            return int(pos) // 1000  # D-Bus Position is in microseconds
        return 0

    def get_track_info(self) -> TrackInfo:
        """Get metadata for the currently playing track."""
        info = TrackInfo()
        if not self._find_player():
            return info
        metadata = self._get_prop("Metadata")
        if not metadata:
            return info
        try:
            title = metadata.get("xesam:title", "")
            if title:
                info.title = str(title)
            artists = metadata.get("xesam:artist", [])
            if artists:
                info.artist = str(artists[0]) if artists else "Unknown"
            album = metadata.get("xesam:album", "")
            if album:
                info.album = str(album)
            length = metadata.get("mpris:length", 0)
            if length:
                info.duration_ms = int(length) // 1000  # microseconds → ms
        except Exception as e:
            log.debug("Error parsing metadata: %s", e)
        return info

    def play(self):
        if self._find_player() and self._player:
            try:
                self._player.Play()
            except Exception as e:
                log.error("MPRIS Play failed: %s", e)

    def pause(self):
        if self._find_player() and self._player:
            try:
                self._player.Pause()
            except Exception as e:
                log.error("MPRIS Pause failed: %s", e)

    def play_pause(self):
        if self._find_player() and self._player:
            try:
                self._player.PlayPause()
            except Exception as e:
                log.error("MPRIS PlayPause failed: %s", e)

    def stop(self):
        if self._find_player() and self._player:
            try:
                self._player.Stop()
            except Exception as e:
                log.error("MPRIS Stop failed: %s", e)

    def next(self):
        if self._find_player() and self._player:
            try:
                self._player.Next()
            except Exception as e:
                log.error("MPRIS Next failed: %s", e)

    def previous(self):
        if self._find_player() and self._player:
            try:
                self._player.Previous()
            except Exception as e:
                log.error("MPRIS Previous failed: %s", e)
