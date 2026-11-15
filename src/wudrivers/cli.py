"""wudrivers: find and download the driver bundle a PC maker publishes on Windows Update."""

import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

from . import __version__, chid, fetch, wu


def _machine(args):
    """The CHIDs to ask about: given ones, a hwids file's, or this machine's from SMBIOS."""
    chids = [c.strip("{} ").lower() for c in args.chid or []]
    if args.hwids:
        with open(args.hwids) as f:
            fields, listed = chid.from_text(f.read())
        computed = [c for _, c in chid.chids(fields)]
        chids += computed or listed
    elif not chids:
        fields = chid.from_sysfs()
        chids += [c for _, c in chid.chids(fields)]
    if not chids:
        sys.exit("wudrivers: no hardware IDs; give --hwids FILE or --chid GUID, or run on the machine itself")
    return list(dict.fromkeys(chids))


def _size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def cmd_chids(args):
    if args.hwids:
        with open(args.hwids) as f:
            fields, _ = chid.from_text(f.read())
    else:
        fields = chid.from_sysfs()
    for n, c in chid.chids(fields):
        print(f"{{{c}}}  HardwareID-{n:<2}  " + " + ".join(chid.TYPES[n]))


def cmd_list(args):
    bundles = wu.Client(args.arch).bundles(_machine(args))
    if args.json:
        json.dump(bundles, sys.stdout, indent=2)
        print()
        return
    if not bundles:
        print("No maker bundle on Windows Update for these hardware IDs.")
        return
    for b in bundles:
        print(f"{b['title'] or b['product']}\n  update {b['update_id']} revision {b['revision']}, product {b['product']}, "
              f"version {b['version']}, {len(b['files'])} files, {_size(b['size'])}")


def cmd_download(args):
    client = wu.Client(args.arch)
    bundles = client.bundles(_machine(args))
    if args.update:
        bundles = [b for b in bundles if b["update_id"].lower() == args.update.lower()]
    if not bundles:
        sys.exit("wudrivers: no maker bundle on Windows Update for these hardware IDs")
    for b in bundles:
        target = os.path.join(args.output, f"{b['product'].strip('{}').split('}')[0]}-{b['version']}")
        cabs = os.path.join(target, "cab")
        os.makedirs(cabs, exist_ok=True)
        with open(os.path.join(target, "bundle.json"), "w") as f:
            json.dump(b, f, indent=2)
        # Folders a previous run unpacked are replaced, so a rerun doesn't number them twice
        listing = os.path.join(target, "packages.txt")
        if args.extract and os.path.exists(listing):
            for name in open(listing).read().split():
                shutil.rmtree(os.path.join(target, name), ignore_errors=True)
        unpacked = []
        urls = client.file_urls(b["update_id"], b["revision"])
        print(f"{b['title'] or b['product']}: {len(b['files'])} files, {_size(b['size'])} -> {target}", file=sys.stderr)
        missing = [f["name"] for f in b["files"] if f["sha1"] not in urls]
        if missing:
            raise fetch.Error(f"{missing[0]}: Windows Update gave no link for it")
        files = b["files"]
        with ThreadPoolExecutor(args.jobs) as pool:
            if args.only:
                lists = pool.map(lambda f: fetch.cab_names(urls[f["sha1"]]), files)
                files = [f for f, names in zip(files, lists) if fetch.matches(names, args.only)]
            paths = pool.map(lambda f: fetch.download(f, urls[f["sha1"]], cabs), files)
        for i, (file, path) in enumerate(zip(files, paths), 1):
            if args.extract:
                unpacked.append(os.path.basename(fetch.unpack(path, target)))
                with open(listing, "w") as f:
                    f.write("\n".join(unpacked) + "\n")
                print(f"  [{i}/{len(files)}] {unpacked[-1]}", file=sys.stderr)
            else:
                print(f"  [{i}/{len(files)}] {file['name']}", file=sys.stderr)
        if args.extract and not args.keep_cabs:
            for name in os.listdir(cabs):
                os.remove(os.path.join(cabs, name))
            os.rmdir(cabs)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wudrivers", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def machine(p):
        p.add_argument("--hwids", metavar="FILE", help="SMBIOS fields in `fwupdtool hwids` format (default: this machine's)")
        p.add_argument("--chid", action="append", metavar="GUID", help="a computer hardware ID to ask about (repeatable)")
        p.add_argument("--arch", default="arm64", choices=("arm64", "amd64"), help="Windows architecture (default: arm64)")

    p = sub.add_parser("chids", help="print the computer hardware IDs Windows derives from SMBIOS")
    p.add_argument("--hwids", metavar="FILE", help="SMBIOS fields in `fwupdtool hwids` format (default: this machine's)")
    p.set_defaults(func=cmd_chids)
    p = sub.add_parser("list", help="list the maker bundles Windows Update holds for a machine")
    machine(p)
    p.add_argument("--json", action="store_true", help="print the bundles' metadata as JSON")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("download", help="download a machine's maker bundles, checked against their digests")
    machine(p)
    p.add_argument("-o", "--output", default=".", help="directory to download into (default: .)")
    p.add_argument("-x", "--extract", action="store_true", help="unpack each driver cabinet into a folder named after its INF")
    p.add_argument("--keep-cabs", action="store_true", help="keep the cabinet files after unpacking")
    p.add_argument("-j", "--jobs", type=int, default=8, help="downloads at the same time (default: 8)")
    p.add_argument("--update", metavar="ID", help="only the bundle with this update ID")
    p.add_argument("--only", action="append", metavar="GLOB", help="only cabinets holding a file that matches, like '*.mbn' or 'qcsubsys*.inf' (repeatable); "
                   "their file lists are read without downloading them")
    p.set_defaults(func=cmd_download)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (wu.Error, fetch.Error) as e:
        sys.exit(f"wudrivers: {e}")


if __name__ == "__main__":
    main()
