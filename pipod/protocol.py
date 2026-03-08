"""
Apple Accessory Protocol (iAP) packet framing.

Packet format:
  0xFF 0x55 [length] [mode] [cmd1] [cmd2] [params...] [checksum]

  - length: number of bytes from mode through last param (inclusive)
  - checksum: (0x100 - (sum of length + payload bytes)) & 0xFF

Reference: http://ipodlinux.org/wiki/Apple_Accessory_Protocol
"""

import struct
import logging
from dataclasses import dataclass, field
from enum import IntEnum

log = logging.getLogger(__name__)

HEADER = bytes([0xFF, 0x55])


class Mode(IntEnum):
    SWITCHING = 0x00
    VOICE_RECORDER = 0x01
    SIMPLE_REMOTE = 0x02
    REQUEST_MODE_STATUS = 0x03
    ADVANCED_REMOTE = 0x04


@dataclass
class Packet:
    """A parsed iAP packet."""
    mode: int
    command: int  # combined cmd1 << 8 | cmd2
    params: bytes = field(default_factory=bytes)

    @property
    def cmd1(self) -> int:
        return (self.command >> 8) & 0xFF

    @property
    def cmd2(self) -> int:
        return self.command & 0xFF


def compute_checksum(payload: bytes) -> int:
    """Compute iAP checksum over length + payload bytes."""
    length = len(payload)
    total = length
    for b in payload:
        total += b
    return (0x100 - total) & 0xFF


def build_packet(mode: int, cmd1: int, cmd2: int,
                 params: bytes = b"") -> bytes:
    """Build a complete iAP packet ready to send over serial."""
    payload = bytes([mode, cmd1, cmd2]) + params
    length = len(payload)
    checksum = compute_checksum(payload)
    return HEADER + bytes([length]) + payload + bytes([checksum])


def build_raw_packet(payload: bytes) -> bytes:
    """Build a packet from raw payload bytes (mode + cmd + params)."""
    length = len(payload)
    checksum = compute_checksum(payload)
    return HEADER + bytes([length]) + payload + bytes([checksum])


class PacketReader:
    """
    State-machine parser for incoming iAP packets from serial.

    Feed bytes via feed(). Complete packets are returned by feed() as a list.
    """

    class _State(IntEnum):
        WAIT_HEADER1 = 0
        WAIT_HEADER2 = 1
        WAIT_LENGTH = 2
        WAIT_DATA = 3
        WAIT_CHECKSUM = 4

    def __init__(self):
        self._state = self._State.WAIT_HEADER1
        self._data_buf = bytearray()
        self._data_len = 0

    def reset(self):
        self._state = self._State.WAIT_HEADER1
        self._data_buf = bytearray()
        self._data_len = 0

    def feed(self, data: bytes) -> list[Packet]:
        """Feed raw bytes, return list of any complete packets parsed."""
        packets = []
        for b in data:
            pkt = self._feed_byte(b)
            if pkt is not None:
                packets.append(pkt)
        return packets

    def _feed_byte(self, b: int) -> Packet | None:
        s = self._State

        if self._state == s.WAIT_HEADER1:
            if b == 0xFF:
                self._state = s.WAIT_HEADER2
            return None

        if self._state == s.WAIT_HEADER2:
            if b == 0x55:
                self._state = s.WAIT_LENGTH
            else:
                self._state = s.WAIT_HEADER1
            return None

        if self._state == s.WAIT_LENGTH:
            self._data_len = b
            self._data_buf = bytearray()
            if self._data_len == 0:
                log.warning("iAP packet with zero length")
                self._state = s.WAIT_HEADER1
                return None
            self._state = s.WAIT_DATA
            return None

        if self._state == s.WAIT_DATA:
            self._data_buf.append(b)
            if len(self._data_buf) >= self._data_len:
                self._state = s.WAIT_CHECKSUM
            return None

        if self._state == s.WAIT_CHECKSUM:
            expected = compute_checksum(bytes(self._data_buf))
            self._state = s.WAIT_HEADER1
            if expected != b:
                log.warning(
                    "iAP checksum mismatch: expected 0x%02X got 0x%02X "
                    "(data: %s)", expected, b, self._data_buf.hex())
                return None
            return self._parse_data()

        return None

    def _parse_data(self) -> Packet | None:
        buf = self._data_buf
        if len(buf) < 2:
            log.warning("iAP packet too short: %d bytes", len(buf))
            return None
        mode = buf[0]
        if len(buf) == 2:
            # Single command byte (e.g. Mode 0 "get status" = 0x03)
            cmd = buf[1]
            params = b""
        elif len(buf) >= 3:
            cmd = (buf[1] << 8) | buf[2]
            params = bytes(buf[3:])
        return Packet(mode=mode, command=cmd, params=params)
