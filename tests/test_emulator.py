"""Tests for pipod.emulator — iPod emulator state machine."""

import struct
import unittest
from unittest.mock import MagicMock, patch

from pipod.protocol import Packet, Mode, build_packet, PacketReader
from pipod.emulator import Emulator
from pipod.mpris_bridge import MprisBridge, TrackInfo, PlaybackStatus


class EmulatorTestBase(unittest.TestCase):
    """Base class that sets up an emulator with mocked MPRIS and serial."""

    def setUp(self):
        self.mpris = MagicMock(spec=MprisBridge)
        self.mpris.get_track_info.return_value = TrackInfo(
            title="Test Song", artist="Test Artist",
            album="Test Album", duration_ms=240000,
        )
        self.mpris.get_position_ms.return_value = 30000
        self.mpris.get_status.return_value = PlaybackStatus.PLAYING

        self.sent_bytes = bytearray()

        def capture_send(data: bytes):
            self.sent_bytes.extend(data)

        self.emu = Emulator(
            mpris=self.mpris,
            send_fn=capture_send,
            ipod_name="testpod",
        )

    def parse_responses(self) -> list[Packet]:
        """Parse all response packets from sent_bytes."""
        reader = PacketReader()
        return reader.feed(bytes(self.sent_bytes))

    def send_command(self, mode: int, cmd1: int, cmd2: int,
                     params: bytes = b""):
        """Build and dispatch a command packet to the emulator."""
        pkt = Packet(mode=mode, command=(cmd1 << 8) | cmd2, params=params)
        self.sent_bytes.clear()
        self.emu.handle_packet(pkt)


class TestModeSwitching(EmulatorTestBase):
    def test_switch_to_air_mode(self):
        self.send_command(Mode.SWITCHING, 0x01, 0x04)
        self.assertEqual(self.emu.current_mode, Mode.ADVANCED_REMOTE)
        responses = self.parse_responses()
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].mode, Mode.SWITCHING)

    def test_mode_status_query(self):
        self.emu.current_mode = Mode.ADVANCED_REMOTE
        # Single-byte command 0x03
        pkt = Packet(mode=Mode.SWITCHING, command=0x03, params=b"")
        self.sent_bytes.clear()
        self.emu.handle_packet(pkt)
        responses = self.parse_responses()
        self.assertEqual(len(responses), 1)


class TestGetIpodName(EmulatorTestBase):
    def test_returns_configured_name(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x14)
        responses = self.parse_responses()
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].mode, Mode.ADVANCED_REMOTE)
        # Response command should be 0x0015 (request + 1)
        self.assertEqual(responses[0].command, 0x0015)
        # Params should be null-terminated name
        self.assertEqual(responses[0].params, b"testpod\x00")


class TestGetIpodType(EmulatorTestBase):
    def test_returns_type_bytes(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x12)
        responses = self.parse_responses()
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].command, 0x0013)
        self.assertEqual(responses[0].params, bytes([0x01, 0x09]))


class TestGetTimeAndStatus(EmulatorTestBase):
    def test_returns_track_info(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x1C)
        responses = self.parse_responses()
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].command, 0x001D)
        params = responses[0].params
        duration = struct.unpack(">I", params[0:4])[0]
        elapsed = struct.unpack(">I", params[4:8])[0]
        status = params[8]
        self.assertEqual(duration, 240000)
        self.assertEqual(elapsed, 30000)
        self.assertEqual(status, PlaybackStatus.PLAYING)


class TestGetTitle(EmulatorTestBase):
    def test_returns_title(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x20,
                          struct.pack(">I", 0))
        responses = self.parse_responses()
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].command, 0x0021)
        self.assertIn(b"Test Song", responses[0].params)


class TestGetArtist(EmulatorTestBase):
    def test_returns_artist(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x22,
                          struct.pack(">I", 0))
        responses = self.parse_responses()
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].command, 0x0023)
        self.assertIn(b"Test Artist", responses[0].params)


class TestGetAlbum(EmulatorTestBase):
    def test_returns_album(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x24,
                          struct.pack(">I", 0))
        responses = self.parse_responses()
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].command, 0x0025)
        self.assertIn(b"Test Album", responses[0].params)


class TestPlaybackControl(EmulatorTestBase):
    def test_play_pause(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x29, bytes([0x01]))
        self.mpris.play_pause.assert_called_once()

    def test_stop(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x29, bytes([0x02]))
        self.mpris.stop.assert_called_once()

    def test_skip_forward(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x29, bytes([0x03]))
        self.mpris.next.assert_called_once()

    def test_skip_backward(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x29, bytes([0x04]))
        self.mpris.previous.assert_called_once()

    def test_sends_feedback_ack(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x29, bytes([0x01]))
        responses = self.parse_responses()
        self.assertEqual(len(responses), 1)
        # Feedback: cmd 0x0001, result=0x00, for cmd 0x00 0x29
        self.assertEqual(responses[0].command, 0x0001)
        self.assertEqual(responses[0].params[0], 0x00)  # success


class TestPollingMode(EmulatorTestBase):
    def test_enable_polling(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x26, bytes([0x01]))
        self.assertTrue(self.emu.polling_active)

    def test_disable_polling(self):
        self.emu.polling_active = True
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x26, bytes([0x00]))
        self.assertFalse(self.emu.polling_active)

    def test_poll_tick_sends_elapsed(self):
        self.emu.polling_active = True
        self.emu.last_poll_time = 0  # force tick to fire
        self.sent_bytes.clear()
        self.emu.poll_tick()
        responses = self.parse_responses()
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].command, 0x0027)
        elapsed = struct.unpack(">I", responses[0].params)[0]
        self.assertEqual(elapsed, 30000)

    def test_poll_tick_noop_when_disabled(self):
        self.emu.polling_active = False
        self.sent_bytes.clear()
        self.emu.poll_tick()
        self.assertEqual(len(self.sent_bytes), 0)


class TestShuffleRepeat(EmulatorTestBase):
    def test_get_shuffle_mode(self):
        self.emu.shuffle_mode = 1
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x2C)
        responses = self.parse_responses()
        self.assertEqual(responses[0].params, bytes([1]))

    def test_set_shuffle_mode(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x2E, bytes([0x02]))
        self.assertEqual(self.emu.shuffle_mode, 2)

    def test_get_repeat_mode(self):
        self.emu.repeat_mode = 2
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x2F)
        responses = self.parse_responses()
        self.assertEqual(responses[0].params, bytes([2]))

    def test_set_repeat_mode(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x31, bytes([0x01]))
        self.assertEqual(self.emu.repeat_mode, 1)


class TestPlaylistQueries(EmulatorTestBase):
    def test_get_item_count(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x18, bytes([0x05]))
        responses = self.parse_responses()
        count = struct.unpack(">I", responses[0].params)[0]
        self.assertEqual(count, 1)

    def test_get_playlist_position(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x1E)
        responses = self.parse_responses()
        pos = struct.unpack(">I", responses[0].params)[0]
        self.assertEqual(pos, 0)

    def test_get_songs_in_playlist(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0x35)
        responses = self.parse_responses()
        count = struct.unpack(">I", responses[0].params)[0]
        self.assertEqual(count, 1)


class TestUnknownCommand(EmulatorTestBase):
    def test_unknown_sends_generic_ack(self):
        self.send_command(Mode.ADVANCED_REMOTE, 0x00, 0xFF)
        responses = self.parse_responses()
        self.assertEqual(len(responses), 1)
        # Should be a feedback ACK
        self.assertEqual(responses[0].command, 0x0001)


if __name__ == "__main__":
    unittest.main()
