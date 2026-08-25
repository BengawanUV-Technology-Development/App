"""Normalize MAVLink source clocks without confusing them with Ground time."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_NSEC_PER_USEC = 1_000
_NSEC_PER_MSEC = 1_000_000


@dataclass(frozen=True)
class NormalizedSourceTime:
    """Source timestamp plus its provenance."""

    timestamp_ns: int | None
    raw_value: int | float | None
    clock_domain: str | None
    valid: bool


class MavlinkTimeNormalizer:
    """Map supported FC boot timestamps to UTC when ``SYSTEM_TIME`` allows it.

    MAVLink messages do not share one universal timestamp contract.  A
    ``time_boot_ms`` value remains invalid for UTC correlation until a
    ``SYSTEM_TIME`` message supplies both Unix UTC and boot time.  GPS raw
    timestamps with an epoch-sized value are accepted as absolute UTC; smaller
    values are treated as FC microseconds and use the same explicit mapping.
    """

    def __init__(self) -> None:
        self._boot_to_utc_offset_ns: int | None = None

    @property
    def boot_to_utc_offset_ns(self) -> int | None:
        return self._boot_to_utc_offset_ns

    def normalize(self, message: Any) -> NormalizedSourceTime:
        message_type = self._message_type(message)

        # Observe this before normalizing the message so the SYSTEM_TIME
        # packet can establish the mapping for subsequent samples.
        if message_type == "SYSTEM_TIME":
            self._observe_system_time(message)
            unix_usec = self._int_or_none(getattr(message, "time_unix_usec", None))
            if unix_usec is not None and unix_usec > 0:
                return NormalizedSourceTime(
                    timestamp_ns=unix_usec * _NSEC_PER_USEC,
                    raw_value=unix_usec,
                    clock_domain="utc_epoch_usec",
                    valid=True,
                )

        if message_type in {"GLOBAL_POSITION_INT", "ATTITUDE", "ATTITUDE_QUATERNION"}:
            raw = self._int_or_none(getattr(message, "time_boot_ms", None))
            if raw is None:
                return NormalizedSourceTime(None, None, "fc_boot_ms", False)
            if self._boot_to_utc_offset_ns is not None:
                return NormalizedSourceTime(
                    timestamp_ns=self._boot_to_utc_offset_ns + raw * _NSEC_PER_MSEC,
                    raw_value=raw,
                    clock_domain="fc_boot_ms_mapped_to_utc",
                    valid=True,
                )
            return NormalizedSourceTime(None, raw, "fc_boot_ms", False)

        if message_type in {"GPS_RAW_INT", "GPS2_RAW"}:
            raw = self._int_or_none(getattr(message, "time_usec", None))
            if raw is None or raw <= 0:
                return NormalizedSourceTime(None, raw, "gps_usec", False)

            # Unix epoch microseconds are currently around 10^15.  A smaller
            # value is retained as FC/GPS microseconds and is only accepted
            # after an explicit SYSTEM_TIME mapping is available.
            if raw >= 100_000_000_000_000:
                return NormalizedSourceTime(
                    timestamp_ns=raw * _NSEC_PER_USEC,
                    raw_value=raw,
                    clock_domain="utc_epoch_usec",
                    valid=True,
                )
            if self._boot_to_utc_offset_ns is not None:
                return NormalizedSourceTime(
                    timestamp_ns=self._boot_to_utc_offset_ns + raw * _NSEC_PER_USEC,
                    raw_value=raw,
                    clock_domain="fc_usec_mapped_to_utc",
                    valid=True,
                )
            return NormalizedSourceTime(None, raw, "fc_or_gps_usec", False)

        return NormalizedSourceTime(None, None, None, False)

    def _observe_system_time(self, message: Any) -> None:
        unix_usec = self._int_or_none(getattr(message, "time_unix_usec", None))
        boot_ms = self._int_or_none(getattr(message, "time_boot_ms", None))
        if unix_usec is None or unix_usec <= 0 or boot_ms is None:
            return
        self._boot_to_utc_offset_ns = (
            unix_usec * _NSEC_PER_USEC - boot_ms * _NSEC_PER_MSEC
        )

    @staticmethod
    def _message_type(message: Any) -> str:
        try:
            return str(message.get_type())
        except Exception:
            return type(message).__name__.upper()

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
