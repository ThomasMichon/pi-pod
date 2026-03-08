"""
pi-pod: iPod Accessory Protocol emulator for Raspberry Pi.

Entry point — opens the serial port, instantiates the emulator, and
runs the main read/dispatch/poll loop.
"""

import argparse
import logging
import sys
import time

from .protocol import PacketReader
from .emulator import Emulator
from .mpris_bridge import MprisBridge

log = logging.getLogger("pipod")


def parse_args():
    p = argparse.ArgumentParser(
        prog="pipod",
        description="iPod Accessory Protocol emulator for Raspberry Pi")
    p.add_argument(
        "-p", "--port", default="/dev/serial0",
        help="Serial port device (default: /dev/serial0)")
    p.add_argument(
        "-b", "--baud", type=int, default=19200,
        help="Baud rate (default: 19200)")
    p.add_argument(
        "-n", "--name", default="iPod",
        help="iPod name reported to the car stereo (default: iPod)")
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging")
    return p.parse_args()


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    try:
        import serial
    except ImportError:
        log.error("pyserial is required: pip install pyserial")
        sys.exit(1)

    log.info("pi-pod starting: port=%s baud=%d name=%s",
             args.port, args.baud, args.name)

    mpris = MprisBridge()

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,  # 50ms read timeout for responsive polling
        )
    except Exception as e:
        log.error("Failed to open serial port %s: %s", args.port, e)
        sys.exit(1)

    log.info("Serial port %s opened at %d baud", args.port, args.baud)

    def send_bytes(data: bytes):
        ser.write(data)
        ser.flush()
        log.debug("TX [%d bytes]: %s", len(data), data.hex())

    reader = PacketReader()
    emu = Emulator(mpris=mpris, send_fn=send_bytes, ipod_name=args.name)

    log.info("Emulator running — waiting for commands from car stereo")

    try:
        while True:
            data = ser.read(64)
            if data:
                log.debug("RX raw [%d bytes]: %s", len(data), data.hex())
                packets = reader.feed(data)
                for pkt in packets:
                    emu.handle_packet(pkt)
            emu.poll_tick()
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        ser.close()
        log.info("Serial port closed")


if __name__ == "__main__":
    main()
