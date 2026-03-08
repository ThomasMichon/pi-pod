"""
iPod emulator state machine.

Handles incoming iAP commands from the car stereo and generates
appropriate responses, pretending to be an iPod. Bridges playback
commands to Bluetooth via the MPRIS bridge.

Reference: http://ipodlinux.org/wiki/Apple_Accessory_Protocol
"""

import struct
import time
import logging
from typing import Callable

from .protocol import Packet, Mode, build_packet, build_raw_packet
from .mpris_bridge import MprisBridge, PlaybackStatus

log = logging.getLogger(__name__)


class _Cmd:
    """Mode 4 (Advanced Remote) command constants."""
    # Commands FROM the car (accessory) TO us (the "iPod")
    GET_IPOD_TYPE = 0x0012
    GET_IPOD_NAME = 0x0014
    SWITCH_TO_MAIN_LIBRARY = 0x0016
    SWITCH_TO_ITEM = 0x0017
    GET_ITEM_COUNT = 0x0018
    GET_ITEM_NAMES = 0x001A
    GET_TIME_AND_STATUS = 0x001C
    GET_PLAYLIST_POSITION = 0x001E
    GET_TITLE = 0x0020
    GET_ARTIST = 0x0022
    GET_ALBUM = 0x0024
    SET_POLLING_MODE = 0x0026
    EXECUTE_SWITCH = 0x0028
    PLAYBACK_CONTROL = 0x0029
    GET_SHUFFLE_MODE = 0x002C
    SET_SHUFFLE_MODE = 0x002E
    GET_REPEAT_MODE = 0x002F
    SET_REPEAT_MODE = 0x0031
    GET_SONGS_IN_PLAYLIST = 0x0035
    JUMP_TO_SONG = 0x0037


class _PlaybackCmd:
    """Playback control sub-commands for 0x0029."""
    PLAY_PAUSE = 0x01
    STOP = 0x02
    SKIP_FORWARD = 0x03
    SKIP_BACKWARD = 0x04
    FFWD = 0x05
    FRWD = 0x06
    STOP_FF_RW = 0x07


class _ItemType:
    PLAYLIST = 0x01
    ARTIST = 0x02
    ALBUM = 0x03
    GENRE = 0x04
    SONG = 0x05
    COMPOSER = 0x06


class Emulator:
    """
    iPod emulator that processes iAP packets and generates responses.

    Args:
        mpris: MprisBridge instance for Bluetooth playback control.
        send_fn: Callable that accepts bytes to send over serial.
        ipod_name: Name to report as the iPod name.
    """

    def __init__(self, mpris: MprisBridge, send_fn: Callable[[bytes], None],
                 ipod_name: str = "iPod"):
        self.mpris = mpris
        self.send = send_fn
        self.ipod_name = ipod_name
        self.current_mode = Mode.SIMPLE_REMOTE
        self.polling_active = False
        self.last_poll_time = 0.0
        self.shuffle_mode = 0  # 0=off, 1=songs, 2=albums
        self.repeat_mode = 0   # 0=off, 1=one, 2=all

    def handle_packet(self, pkt: Packet):
        """Dispatch an incoming packet to the appropriate handler."""
        log.debug("RX mode=0x%02X cmd=0x%04X params=%s",
                  pkt.mode, pkt.command, pkt.params.hex() if pkt.params else "")

        if pkt.mode == Mode.SWITCHING:
            self._handle_mode_switch(pkt)
        elif pkt.mode == Mode.ADVANCED_REMOTE:
            self._handle_advanced_remote(pkt)
        elif pkt.mode == Mode.SIMPLE_REMOTE:
            log.info("Simple Remote command ignored: 0x%04X", pkt.command)
        else:
            log.warning("Unknown mode: 0x%02X", pkt.mode)

    def poll_tick(self):
        """Call periodically. If polling is active, send elapsed time."""
        if not self.polling_active:
            return
        now = time.monotonic()
        if now - self.last_poll_time >= 0.5:
            self.last_poll_time = now
            elapsed = self.mpris.get_position_ms()
            # Response: Mode 4, cmd 0x00 0x27, 4-byte elapsed time
            params = struct.pack(">I", elapsed)
            self._send_response(0x0027, params)

    # -- Mode 0: Mode Switching --

    def _handle_mode_switch(self, pkt: Packet):
        cmd = pkt.command
        if cmd == 0x0001:
            # Switch to mode N (param byte is the mode)
            # In a 3-byte payload: mode=0x00, cmd1=0x01, cmd2=<target_mode>
            # But actually cmd is 0x0001 and params[0] is target mode
            # Wait - looking at protocol: 0x01 0x04 means switch to mode 4
            # So cmd1=0x01, cmd2=target_mode. command = 0x01XX
            # Let me re-check: the packet is mode=0x00, data=[0x01, 0x04]
            # so cmd = 0x0104. Hmm, but that doesn't match our parsing which
            # is cmd = (buf[1] << 8) | buf[2].
            # Actually for mode switching: mode=0x00, then the next bytes
            # are the command. 0x01 is "switch mode" and the parameter is
            # the target mode. So cmd=0x01, param=target_mode.
            # But our parser puts buf[1]=0x01, buf[2]=target_mode as command.
            # So command = 0x0104 for "switch to mode 4".
            target_mode = pkt.cmd2
            log.info("Mode switch request → mode 0x%02X", target_mode)
            self.current_mode = target_mode
            # Respond: mode 0x00, cmd 0x04, param = current mode
            self._send_raw(Mode.SWITCHING, 0x00, 0x04,
                           bytes([target_mode]))
        elif cmd == 0x0003 or pkt.cmd1 == 0x03:
            # Get current mode status
            log.info("Mode status request")
            self._send_raw(Mode.SWITCHING, 0x00, 0x04,
                           bytes([self.current_mode]))
        else:
            log.info("Unknown mode-switch command: 0x%04X", cmd)

    # -- Mode 4: Advanced Remote --

    def _handle_advanced_remote(self, pkt: Packet):
        cmd = pkt.command
        handlers = {
            _Cmd.GET_IPOD_TYPE: self._cmd_get_ipod_type,
            _Cmd.GET_IPOD_NAME: self._cmd_get_ipod_name,
            _Cmd.SWITCH_TO_MAIN_LIBRARY: self._cmd_switch_main_library,
            _Cmd.SWITCH_TO_ITEM: self._cmd_switch_to_item,
            _Cmd.GET_ITEM_COUNT: self._cmd_get_item_count,
            _Cmd.GET_ITEM_NAMES: self._cmd_get_item_names,
            _Cmd.GET_TIME_AND_STATUS: self._cmd_get_time_and_status,
            _Cmd.GET_PLAYLIST_POSITION: self._cmd_get_playlist_position,
            _Cmd.GET_TITLE: self._cmd_get_title,
            _Cmd.GET_ARTIST: self._cmd_get_artist,
            _Cmd.GET_ALBUM: self._cmd_get_album,
            _Cmd.SET_POLLING_MODE: self._cmd_set_polling_mode,
            _Cmd.EXECUTE_SWITCH: self._cmd_execute_switch,
            _Cmd.PLAYBACK_CONTROL: self._cmd_playback_control,
            _Cmd.GET_SHUFFLE_MODE: self._cmd_get_shuffle_mode,
            _Cmd.SET_SHUFFLE_MODE: self._cmd_set_shuffle_mode,
            _Cmd.GET_REPEAT_MODE: self._cmd_get_repeat_mode,
            _Cmd.SET_REPEAT_MODE: self._cmd_set_repeat_mode,
            _Cmd.GET_SONGS_IN_PLAYLIST: self._cmd_get_songs_in_playlist,
            _Cmd.JUMP_TO_SONG: self._cmd_jump_to_song,
        }
        handler = handlers.get(cmd)
        if handler:
            handler(pkt)
        else:
            log.warning("Unhandled Mode 4 command: 0x%04X", cmd)
            # Send generic ACK (success) so the car doesn't error out
            self._send_feedback(0x00, pkt.cmd1, pkt.cmd2)

    def _send_response(self, response_cmd: int, params: bytes = b""):
        """Send a Mode 4 response. Response cmd = request cmd + 1."""
        cmd1 = (response_cmd >> 8) & 0xFF
        cmd2 = response_cmd & 0xFF
        data = self.send(
            build_packet(Mode.ADVANCED_REMOTE, cmd1, cmd2, params))
        log.debug("TX response cmd=0x%04X params=%s",
                  response_cmd, params.hex() if params else "")

    def _send_feedback(self, result: int, orig_cmd1: int, orig_cmd2: int):
        """Send Mode 4 feedback (ACK/NACK) for a command."""
        params = bytes([result, orig_cmd1, orig_cmd2])
        self.send(
            build_packet(Mode.ADVANCED_REMOTE, 0x00, 0x01, params))

    def _send_raw(self, mode: int, cmd1: int, cmd2: int,
                  params: bytes = b""):
        """Send a packet with explicit mode and command bytes."""
        self.send(build_packet(mode, cmd1, cmd2, params))

    # -- Command handlers --

    def _cmd_get_ipod_type(self, pkt: Packet):
        log.info("GetIPodType")
        # Respond as a Gen5 30GB: 0x01 0x09
        self._send_response(0x0013, bytes([0x01, 0x09]))

    def _cmd_get_ipod_name(self, pkt: Packet):
        log.info("GetIPodName")
        name_bytes = self.ipod_name.encode("ascii", errors="replace") + b"\x00"
        self._send_response(0x0015, name_bytes)

    def _cmd_switch_main_library(self, pkt: Packet):
        log.info("SwitchToMainLibraryPlaylist")
        self._send_feedback(0x00, 0x00, 0x16)

    def _cmd_switch_to_item(self, pkt: Packet):
        log.info("SwitchToItem: %s", pkt.params.hex())
        self._send_feedback(0x00, 0x00, 0x17)

    def _cmd_get_item_count(self, pkt: Packet):
        item_type = pkt.params[0] if pkt.params else 0
        log.info("GetItemCount type=0x%02X", item_type)
        # We always report 1 item (the current BT stream)
        count = 1
        self._send_response(0x0019, struct.pack(">I", count))

    def _cmd_get_item_names(self, pkt: Packet):
        log.info("GetItemNames: %s", pkt.params.hex())
        # Return a single item: the current track or our device name
        track = self.mpris.get_track_info()
        if pkt.params and len(pkt.params) >= 1:
            item_type = pkt.params[0]
        else:
            item_type = _ItemType.SONG
        if item_type == _ItemType.SONG:
            name = track.title
        elif item_type == _ItemType.ARTIST:
            name = track.artist
        elif item_type == _ItemType.ALBUM:
            name = track.album
        elif item_type == _ItemType.PLAYLIST:
            name = self.ipod_name
        else:
            name = self.ipod_name
        offset = struct.pack(">I", 0)
        name_bytes = name.encode("ascii", errors="replace") + b"\x00"
        self._send_response(0x001B, offset + name_bytes)

    def _cmd_get_time_and_status(self, pkt: Packet):
        log.info("GetTimeAndStatus")
        track = self.mpris.get_track_info()
        elapsed = self.mpris.get_position_ms()
        status = self.mpris.get_status()
        params = struct.pack(">II", track.duration_ms, elapsed)
        params += bytes([status])
        self._send_response(0x001D, params)

    def _cmd_get_playlist_position(self, pkt: Packet):
        log.info("GetPlaylistPosition")
        self._send_response(0x001F, struct.pack(">I", 0))

    def _cmd_get_title(self, pkt: Packet):
        log.info("GetTitle")
        track = self.mpris.get_track_info()
        name_bytes = track.title.encode("ascii", errors="replace") + b"\x00"
        self._send_response(0x0021, name_bytes)

    def _cmd_get_artist(self, pkt: Packet):
        log.info("GetArtist")
        track = self.mpris.get_track_info()
        name_bytes = track.artist.encode("ascii", errors="replace") + b"\x00"
        self._send_response(0x0023, name_bytes)

    def _cmd_get_album(self, pkt: Packet):
        log.info("GetAlbum")
        track = self.mpris.get_track_info()
        name_bytes = track.album.encode("ascii", errors="replace") + b"\x00"
        self._send_response(0x0025, name_bytes)

    def _cmd_set_polling_mode(self, pkt: Packet):
        mode = pkt.params[0] if pkt.params else 0
        self.polling_active = (mode == 0x01)
        self.last_poll_time = time.monotonic()
        log.info("SetPollingMode: %s",
                 "ON" if self.polling_active else "OFF")
        self._send_feedback(0x00, 0x00, 0x26)

    def _cmd_execute_switch(self, pkt: Packet):
        log.info("ExecuteSwitch: %s", pkt.params.hex())
        # Start playback at specified song index; we just play
        self.mpris.play()
        self._send_feedback(0x00, 0x00, 0x28)

    def _cmd_playback_control(self, pkt: Packet):
        cmd = pkt.params[0] if pkt.params else 0
        log.info("PlaybackControl: 0x%02X", cmd)
        if cmd == _PlaybackCmd.PLAY_PAUSE:
            self.mpris.play_pause()
        elif cmd == _PlaybackCmd.STOP:
            self.mpris.stop()
        elif cmd == _PlaybackCmd.SKIP_FORWARD:
            self.mpris.next()
        elif cmd == _PlaybackCmd.SKIP_BACKWARD:
            self.mpris.previous()
        elif cmd in (_PlaybackCmd.FFWD, _PlaybackCmd.FRWD,
                     _PlaybackCmd.STOP_FF_RW):
            pass  # Not mapped to MPRIS
        self._send_feedback(0x00, 0x00, 0x29)

    def _cmd_get_shuffle_mode(self, pkt: Packet):
        log.info("GetShuffleMode")
        self._send_response(0x002D, bytes([self.shuffle_mode]))

    def _cmd_set_shuffle_mode(self, pkt: Packet):
        self.shuffle_mode = pkt.params[0] if pkt.params else 0
        log.info("SetShuffleMode: %d", self.shuffle_mode)
        self._send_feedback(0x00, 0x00, 0x2E)

    def _cmd_get_repeat_mode(self, pkt: Packet):
        log.info("GetRepeatMode")
        self._send_response(0x0030, bytes([self.repeat_mode]))

    def _cmd_set_repeat_mode(self, pkt: Packet):
        self.repeat_mode = pkt.params[0] if pkt.params else 0
        log.info("SetRepeatMode: %d", self.repeat_mode)
        self._send_feedback(0x00, 0x00, 0x31)

    def _cmd_get_songs_in_playlist(self, pkt: Packet):
        log.info("GetSongsInPlaylist")
        self._send_response(0x0036, struct.pack(">I", 1))

    def _cmd_jump_to_song(self, pkt: Packet):
        log.info("JumpToSong: %s", pkt.params.hex())
        self.mpris.play()
        self._send_feedback(0x00, 0x00, 0x37)
