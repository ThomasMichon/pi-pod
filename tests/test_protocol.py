"""Tests for pipod.protocol — iAP packet framing."""

import unittest
from pipod.protocol import (
    Packet, PacketReader, build_packet, build_raw_packet, compute_checksum,
    Mode, HEADER,
)


class TestChecksum(unittest.TestCase):
    def test_simple(self):
        # Mode 0x02, cmd 0x00, 0x01 (Simple Remote play)
        payload = bytes([0x02, 0x00, 0x01])
        cs = compute_checksum(payload)
        # length=3, sum = 3 + 0x02 + 0x00 + 0x01 = 6
        # checksum = (0x100 - 6) & 0xFF = 0xFA
        self.assertEqual(cs, 0xFA)

    def test_mode_switch(self):
        # Mode 0x00, cmd 0x01, 0x04 (switch to AiR)
        payload = bytes([0x00, 0x01, 0x04])
        cs = compute_checksum(payload)
        # length=3, sum = 3 + 0 + 1 + 4 = 8
        self.assertEqual(cs, (0x100 - 8) & 0xFF)  # 0xF8

    def test_wraps_at_256(self):
        payload = bytes([0xFF, 0xFF])
        cs = compute_checksum(payload)
        # length=2, sum = 2 + 255 + 255 = 512 & 0xFF = 0
        self.assertEqual(cs, (0x100 - 512) & 0xFF)


class TestBuildPacket(unittest.TestCase):
    def test_simple_remote_play(self):
        pkt = build_packet(Mode.SIMPLE_REMOTE, 0x00, 0x01)
        # 0xFF 0x55 0x03 0x02 0x00 0x01 0xFA
        self.assertEqual(pkt[:2], HEADER)
        self.assertEqual(pkt[2], 3)       # length
        self.assertEqual(pkt[3], 0x02)    # mode
        self.assertEqual(pkt[4], 0x00)    # cmd1
        self.assertEqual(pkt[5], 0x01)    # cmd2
        self.assertEqual(pkt[6], 0xFA)    # checksum

    def test_with_params(self):
        # Mode 4 playback control: play/pause (0x01)
        pkt = build_packet(Mode.ADVANCED_REMOTE, 0x00, 0x29, bytes([0x01]))
        self.assertEqual(pkt[2], 4)       # length: mode + cmd1 + cmd2 + param
        self.assertEqual(pkt[3], 0x04)    # mode
        self.assertEqual(pkt[4], 0x00)
        self.assertEqual(pkt[5], 0x29)
        self.assertEqual(pkt[6], 0x01)    # param

    def test_roundtrip_checksum(self):
        """Built packet should parse with valid checksum."""
        pkt = build_packet(0x04, 0x00, 0x15, b"iPod\x00")
        reader = PacketReader()
        results = reader.feed(pkt)
        self.assertEqual(len(results), 1)


class TestBuildRawPacket(unittest.TestCase):
    def test_matches_build_packet(self):
        a = build_packet(0x04, 0x00, 0x01, bytes([0x00, 0x00, 0x29]))
        payload = bytes([0x04, 0x00, 0x01, 0x00, 0x00, 0x29])
        b = build_raw_packet(payload)
        self.assertEqual(a, b)


class TestPacketReader(unittest.TestCase):
    def test_parse_simple_remote_play(self):
        # 0xFF 0x55 0x03 0x02 0x00 0x01 0xFA
        raw = bytes([0xFF, 0x55, 0x03, 0x02, 0x00, 0x01, 0xFA])
        reader = PacketReader()
        pkts = reader.feed(raw)
        self.assertEqual(len(pkts), 1)
        self.assertEqual(pkts[0].mode, 0x02)
        self.assertEqual(pkts[0].command, 0x0001)
        self.assertEqual(pkts[0].params, b"")

    def test_parse_mode_switch_to_air(self):
        raw = build_packet(Mode.SWITCHING, 0x01, 0x04)
        reader = PacketReader()
        pkts = reader.feed(raw)
        self.assertEqual(len(pkts), 1)
        self.assertEqual(pkts[0].mode, Mode.SWITCHING)
        self.assertEqual(pkts[0].command, 0x0104)

    def test_parse_with_params(self):
        raw = build_packet(Mode.ADVANCED_REMOTE, 0x00, 0x29, bytes([0x03]))
        reader = PacketReader()
        pkts = reader.feed(raw)
        self.assertEqual(len(pkts), 1)
        self.assertEqual(pkts[0].mode, Mode.ADVANCED_REMOTE)
        self.assertEqual(pkts[0].command, 0x0029)
        self.assertEqual(pkts[0].params, bytes([0x03]))

    def test_parse_short_mode0_command(self):
        """Mode 0 'get status' is only 2 payload bytes: mode=0x00, cmd=0x03."""
        payload = bytes([0x00, 0x03])
        cs = compute_checksum(payload)
        raw = HEADER + bytes([2]) + payload + bytes([cs])
        reader = PacketReader()
        pkts = reader.feed(raw)
        self.assertEqual(len(pkts), 1)
        self.assertEqual(pkts[0].mode, 0x00)
        self.assertEqual(pkts[0].command, 0x03)

    def test_bad_checksum_rejected(self):
        raw = bytes([0xFF, 0x55, 0x03, 0x02, 0x00, 0x01, 0x00])  # bad CS
        reader = PacketReader()
        pkts = reader.feed(raw)
        self.assertEqual(len(pkts), 0)

    def test_incremental_feed(self):
        """Parser handles bytes arriving one at a time."""
        raw = build_packet(Mode.ADVANCED_REMOTE, 0x00, 0x14)
        reader = PacketReader()
        pkts = []
        for b in raw:
            pkts.extend(reader.feed(bytes([b])))
        self.assertEqual(len(pkts), 1)
        self.assertEqual(pkts[0].command, 0x0014)

    def test_multiple_packets(self):
        """Parser handles two back-to-back packets."""
        pkt1 = build_packet(Mode.SWITCHING, 0x01, 0x04)
        pkt2 = build_packet(Mode.ADVANCED_REMOTE, 0x00, 0x14)
        reader = PacketReader()
        pkts = reader.feed(pkt1 + pkt2)
        self.assertEqual(len(pkts), 2)
        self.assertEqual(pkts[0].command, 0x0104)
        self.assertEqual(pkts[1].command, 0x0014)

    def test_garbage_before_packet(self):
        """Parser skips garbage bytes before a valid packet."""
        garbage = bytes([0x12, 0x34, 0xAB])
        valid = build_packet(Mode.ADVANCED_REMOTE, 0x00, 0x1C)
        reader = PacketReader()
        pkts = reader.feed(garbage + valid)
        self.assertEqual(len(pkts), 1)
        self.assertEqual(pkts[0].command, 0x001C)

    def test_string_param_roundtrip(self):
        """Packet with null-terminated string param parses correctly."""
        name = b"iPod\x00"
        raw = build_packet(Mode.ADVANCED_REMOTE, 0x00, 0x15, name)
        reader = PacketReader()
        pkts = reader.feed(raw)
        self.assertEqual(len(pkts), 1)
        self.assertEqual(pkts[0].params, name)


class TestPacketProperties(unittest.TestCase):
    def test_cmd1_cmd2(self):
        pkt = Packet(mode=0x04, command=0x0029)
        self.assertEqual(pkt.cmd1, 0x00)
        self.assertEqual(pkt.cmd2, 0x29)

    def test_single_byte_command(self):
        pkt = Packet(mode=0x00, command=0x03)
        self.assertEqual(pkt.cmd1, 0x00)
        self.assertEqual(pkt.cmd2, 0x03)


if __name__ == "__main__":
    unittest.main()
