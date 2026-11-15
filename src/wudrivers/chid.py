"""Computer hardware IDs (CHIDs), the GUIDs Windows derives from a machine's SMBIOS strings.

Windows Update publishes a maker's driver bundle for one of these IDs, so they are what a lookup
needs. The algorithm is Microsoft's ComputerHardwareIds one, as fwupd and systemd implement it:
a version 5 UUID over the UTF-16LE string of the chosen fields joined by '&'.
"""

import hashlib
import os
import re
import uuid

NAMESPACE = uuid.UUID("70ffd812-4c7f-4c7d-0000-000000000000")

# Field names as fwupd's `fwupdtool hwids` prints them
FIELDS = (
    "Manufacturer", "Family", "ProductName", "ProductSku", "BaseboardManufacturer",
    "BaseboardProduct", "BiosVendor", "BiosVersion", "BiosMajorRelease", "BiosMinorRelease",
    "EnclosureKind",
)

# HardwareID-0 to HardwareID-14, most specific first
TYPES = (
    ("Manufacturer", "Family", "ProductName", "ProductSku", "BiosVendor", "BiosVersion", "BiosMajorRelease", "BiosMinorRelease"),
    ("Manufacturer", "Family", "ProductName", "BiosVendor", "BiosVersion", "BiosMajorRelease", "BiosMinorRelease"),
    ("Manufacturer", "ProductName", "BiosVendor", "BiosVersion", "BiosMajorRelease", "BiosMinorRelease"),
    ("Manufacturer", "Family", "ProductName", "ProductSku", "BaseboardManufacturer", "BaseboardProduct"),
    ("Manufacturer", "Family", "ProductName", "ProductSku"),
    ("Manufacturer", "Family", "ProductName"),
    ("Manufacturer", "ProductSku", "BaseboardManufacturer", "BaseboardProduct"),
    ("Manufacturer", "ProductSku"),
    ("Manufacturer", "ProductName", "BaseboardManufacturer", "BaseboardProduct"),
    ("Manufacturer", "ProductName"),
    ("Manufacturer", "Family", "BaseboardManufacturer", "BaseboardProduct"),
    ("Manufacturer", "Family"),
    ("Manufacturer", "EnclosureKind"),
    ("Manufacturer", "BaseboardManufacturer", "BaseboardProduct"),
    ("Manufacturer",),
)

# /sys/class/dmi/id files for each field. chassis_type is decimal there and bios_release is "major.minor".
SYSFS = {
    "Manufacturer": "sys_vendor", "Family": "product_family", "ProductName": "product_name",
    "ProductSku": "product_sku", "BaseboardManufacturer": "board_vendor", "BaseboardProduct": "board_name",
    "BiosVendor": "bios_vendor", "BiosVersion": "bios_version", "EnclosureKind": "chassis_type",
}


def normalise(fields):
    """Strip the strings and write the numeric fields as Windows hashes them: the BIOS release numbers,
    which SMBIOS and fwupd give in decimal, as two hex digits, and the enclosure kind in lowercase hex."""
    out = {}
    for key, value in fields.items():
        value = "" if value is None else str(value).strip()
        if not value:
            continue
        if key in ("BiosMajorRelease", "BiosMinorRelease"):
            value = format(int(value, 0), "02x")
        elif key == "EnclosureKind":
            value = value.lower().removeprefix("0x")
        out[key] = value
    return out


def chid(values):
    data = "&".join(values).encode("utf-16-le")
    digest = bytearray(hashlib.sha1(NAMESPACE.bytes + data).digest()[:16])
    digest[6] = (digest[6] & 0x0F) | 0x50
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def chids(fields):
    """[(type number, CHID)] for every type whose fields are all known, most specific first."""
    fields = normalise(fields)
    return [(n, chid([fields[k] for k in keys])) for n, keys in enumerate(TYPES) if all(k in fields for k in keys)]


def from_sysfs(root="/sys/class/dmi/id"):
    """This machine's fields from the kernel's SMBIOS export."""
    fields = {}
    for key, name in SYSFS.items():
        try:
            with open(os.path.join(root, name)) as f:
                fields[key] = f.read().strip()
        except OSError:
            pass
    if fields.get("EnclosureKind", "").isdigit():
        fields["EnclosureKind"] = format(int(fields["EnclosureKind"]), "x")
    try:
        with open(os.path.join(root, "bios_release")) as f:
            major, _, minor = f.read().strip().partition(".")
        fields["BiosMajorRelease"], fields["BiosMinorRelease"] = major, minor
    except OSError:
        pass
    return fields


def from_text(text):
    """Fields and listed CHIDs from `fwupdtool hwids` output or a file in its format."""
    fields, listed = {}, []
    for line in text.splitlines():
        m = re.match(r"\s*(\w+):\s*(.*?)\s*$", line)
        if m and m.group(1) in FIELDS:
            fields[m.group(1)] = m.group(2)
        g = re.match(r"\s*\{?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\}?", line)
        if g:
            listed.append(g.group(1).lower())
    return fields, listed
