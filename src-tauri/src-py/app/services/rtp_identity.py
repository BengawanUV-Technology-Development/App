"""Ground copy of the frozen RTP uint64 frame_id extension codec."""

from __future__ import annotations

import struct
from dataclasses import dataclass


FRAME_ID_PROFILE = 0xB0F3


class RtpIdentityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RtpPacket:
    sequence: int
    timestamp: int
    ssrc: int
    marker: bool
    payload_type: int
    frame_id: int | None
    payload_offset: int


def parse_rtp_packet(packet: bytes) -> RtpPacket:
    if len(packet) < 12 or packet[0] >> 6 != 2:
        raise RtpIdentityError("invalid RTP v2 packet")
    csrc_count = packet[0] & 0x0F
    has_extension = bool(packet[0] & 0x10)
    offset = 12 + csrc_count * 4
    if len(packet) < offset:
        raise RtpIdentityError("truncated RTP CSRC list")
    frame_id = None
    if has_extension:
        if len(packet) < offset + 4:
            raise RtpIdentityError("truncated RTP extension header")
        profile, words = struct.unpack_from("!HH", packet, offset)
        extension_size = words * 4
        extension_start = offset + 4
        offset = extension_start + extension_size
        if len(packet) < offset:
            raise RtpIdentityError("truncated RTP extension payload")
        if profile == FRAME_ID_PROFILE:
            if extension_size != 8:
                raise RtpIdentityError("frame_id RTP extension must contain eight bytes")
            frame_id = struct.unpack_from("!Q", packet, extension_start)[0]
    return RtpPacket(
        sequence=struct.unpack_from("!H", packet, 2)[0],
        timestamp=struct.unpack_from("!I", packet, 4)[0],
        ssrc=struct.unpack_from("!I", packet, 8)[0],
        marker=bool(packet[1] & 0x80),
        payload_type=packet[1] & 0x7F,
        frame_id=frame_id,
        payload_offset=offset,
    )


def inject_frame_id(packet: bytes, frame_id: int) -> bytes:
    if isinstance(frame_id, bool) or not isinstance(frame_id, int) or not 0 <= frame_id <= 0xFFFFFFFFFFFFFFFF:
        raise RtpIdentityError("frame_id must be an unsigned 64-bit integer")
    parsed = parse_rtp_packet(packet)
    csrc_end = 12 + (packet[0] & 0x0F) * 4
    extension = struct.pack("!HHQ", FRAME_ID_PROFILE, 2, frame_id)
    if packet[0] & 0x10:
        profile, words = struct.unpack_from("!HH", packet, csrc_end)
        if profile != FRAME_ID_PROFILE:
            raise RtpIdentityError("RTP packet already uses an unsupported header extension")
        old_end = csrc_end + 4 + words * 4
        result = packet[:csrc_end] + extension + packet[old_end:]
    else:
        result = bytes([packet[0] | 0x10]) + packet[1:csrc_end] + extension + packet[csrc_end:]
    if parse_rtp_packet(result).frame_id != frame_id or parsed.timestamp != parse_rtp_packet(result).timestamp:
        raise RtpIdentityError("failed to preserve RTP identity while adding frame_id")
    return result


class RtpTimestampUnwrapper:
    def __init__(self):
        self._highest: int | None = None

    def unwrap(self, timestamp: int) -> int:
        if not 0 <= timestamp <= 0xFFFFFFFF:
            raise ValueError("RTP timestamp must be uint32")
        if self._highest is None:
            self._highest = timestamp
            return timestamp
        base = self._highest & ~0xFFFFFFFF
        candidate = base | timestamp
        if candidate - self._highest > 0x80000000:
            candidate -= 0x100000000
        elif self._highest - candidate > 0x80000000:
            candidate += 0x100000000
        if candidate > self._highest:
            self._highest = candidate
        return candidate
