"""Downloading a bundle's files, checking them, and unpacking the driver cabinets."""

import base64
import fnmatch
import hashlib
import os
import re
import shutil
import struct
import subprocess
import tempfile
import urllib.request

from .wu import USER_AGENT


class Error(Exception):
    pass


def _digest(path):
    sha1, sha256 = hashlib.sha1(), hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha1.update(chunk)
            sha256.update(chunk)
    return base64.b64encode(sha1.digest()).decode(), base64.b64encode(sha256.digest()).decode()


def download(file, url, directory):
    """Download one bundle file into directory, unless a copy with the right digests is there."""
    path = os.path.join(directory, file["name"])
    if os.path.exists(path) and _digest(path) == (file["sha1"], file["sha256"] or _digest(path)[1]):
        return path
    partial = path + ".part"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response, open(partial, "wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)
    sha1, sha256 = _digest(partial)
    if sha1 != file["sha1"] or (file["sha256"] and sha256 != file["sha256"]):
        os.remove(partial)
        raise Error(f"{file['name']}: the download doesn't match the digest Windows Update gives")
    os.replace(partial, path)
    return path


def cab_names(url, chunk=65536):
    """The file names inside a cabinet, read from its header with HTTP range requests, so a filter
    can skip cabinets without downloading them."""
    data = b""
    while True:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Range": f"bytes={len(data)}-{len(data) + chunk - 1}"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data += response.read()
        if data[:4] != b"MSCF":
            raise Error("not a cabinet file")
        files_at, count = struct.unpack_from("<I", data, 16)[0], struct.unpack_from("<H", data, 28)[0]
        names, pos = [], files_at
        try:
            for _ in range(count):
                end = data.index(b"\0", pos + 16)
                names.append(data[pos + 16:end].decode("utf-8", "replace"))
                pos = end + 1
            return names
        except (ValueError, struct.error):
            chunk *= 4


def matches(names, patterns):
    """Whether any name matches any glob pattern, ignoring case."""
    return any(fnmatch.fnmatch(n.lower(), p.lower()) for n in names for p in patterns)


def _commands(cab, target):
    """The unpacking commands to try, most dependable first."""
    tools = (("cabextract", ["cabextract", "-q", "-d", target, cab]), ("bsdtar", ["bsdtar", "-xf", cab, "-C", target]),
             ("7z", ["7z", "x", "-y", f"-o{target}", cab]))
    found = [cmd for tool, cmd in tools if shutil.which(tool)]
    if not found:
        raise Error("unpacking needs cabextract, bsdtar (libarchive) or 7z")
    return found


def unpack(cab, directory):
    """Unpack one driver cabinet into directory/<inf name>, the name of the driver package in it."""
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        for cmd in _commands(cab, tmp):
            if subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                break
            for name in os.listdir(tmp):
                path = os.path.join(tmp, name)
                shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        else:
            raise Error(f"{os.path.basename(cab)}: none of the unpackers could read it")
        infs = sorted(n for n in os.listdir(tmp) if n.lower().endswith(".inf"))
        name = os.path.splitext(infs[0])[0] if infs else os.path.splitext(os.path.basename(cab))[0]
        name = re.sub(r"[^\w.-]", "_", name)
        # Two cabinets can hold packages with the same INF name, so a taken name gets a number
        target, n = os.path.join(directory, name), 1
        while os.path.exists(target):
            n += 1
            target = os.path.join(directory, f"{name}-{n}")
        shutil.move(tmp, target)
        os.makedirs(tmp)
    return target
