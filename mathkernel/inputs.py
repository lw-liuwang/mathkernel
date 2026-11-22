"""Shared JSON input validation and resource-report helpers."""

from dataclasses import dataclass
import json
from pathlib import Path


class InputError(ValueError):
    pass


def fields(value, required, optional=(), context="input"):
    if not isinstance(value, dict):
        raise InputError(f"{context} must be an object")
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing or unknown:
        raise InputError(f"{context}: missing={sorted(missing)}, unknown={sorted(unknown)}")
    return value


def positive(value, context):
    if type(value) is not int or value <= 0:
        raise InputError(f"{context} must be a positive integer")
    return value


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise InputError(f"Cannot read {path}: {error}") from error


@dataclass(frozen=True)
class Hardware:
    name: str
    peak_flops_per_second: int
    hbm_bytes_per_second: int
    fast_memory_bytes: int
    element_bytes: int

    @classmethod
    def parse(cls, value):
        keys = ("peak_flops_per_second", "hbm_bytes_per_second", "fast_memory_bytes", "element_bytes")
        fields(value, ("name", *keys), context="hardware")
        if not isinstance(value["name"], str) or not value["name"]:
            raise InputError("hardware.name must be a nonempty string")
        return cls(value["name"], *(positive(value[key], f"hardware.{key}") for key in keys))


def seconds_json(seconds):
    return {"numerator": seconds.numerator, "denominator": seconds.denominator, "approximate": float(seconds)}
