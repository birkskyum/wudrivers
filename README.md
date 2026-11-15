# wudrivers

Find and download the driver bundle a PC maker publishes on Windows Update, from Linux.

Many laptops, especially Arm ones, only get their drivers through Windows Update. Their makers don't
post them anywhere else. The drivers carry firmware that Linux needs too: the audio and compute DSP
images, the GPU microcode, the video decoder firmware and so on. `wudrivers` asks Windows Update for a
machine's bundle the way Windows 11 does and fetches it, with no Windows install and no account.

```
$ wudrivers list
LENOVO System Hardware Update (200.0.20.0)
  update 8ac5f653-c97b-4f51-b034-fe17f2f70501 revision 1, product {9b723570-d493-5541-ae58-49087512f816}_arm64, version 200.0.20.0, 113 files, 289.7 MB

$ wudrivers download --extract --only '*.mbn' --only '*.elf' --only '*.jsn' -o drivers
LENOVO System Hardware Update (200.0.20.0): 113 files, 289.7 MB -> drivers/9b723570-d493-5541-ae58-49087512f816-200.0.20.0
  [1/24] qcsubsys_ext_adsp8380
  [2/24] qcnspmcdm_ext_cdsp8380
  ...
```

## How it works

Windows derives a set of computer hardware IDs (CHIDs) from a machine's SMBIOS strings: the maker,
family, product name, SKU, baseboard and BIOS version. Windows 11 asks Windows Update about one
product per CHID, named `{CHID}_arm64` or `{CHID}_amd64`. A maker's bundle for the machine, which
Lenovo, HP, Dell, ASUS, Acer, Samsung, Microsoft and others publish as "System Hardware Update", is
an update for one of those products. Its files are the maker's signed driver packages, one cabinet
file each.

`wudrivers` computes the CHIDs, asks the same delivery service Windows uses for the products, and
requests fresh download links for the bundle it finds. Every file is checked against the SHA-1 and
SHA-256 in Windows Update's metadata before it's kept. With `--only`, it reads each cabinet's file list
through an HTTP range request first and downloads only the cabinets that hold a matching file.

## Install

It needs Python 3.11 or newer and nothing else to list and download. Unpacking (`--extract`) uses
`cabextract`, `bsdtar` from libarchive, or `7z`, whichever is installed.

```
pipx install git+https://github.com/birkskyum/wudrivers
```

## Usage

On the machine itself, `wudrivers` reads the SMBIOS strings from `/sys/class/dmi/id`:

```
wudrivers chids                       # the CHIDs Windows derives for this machine
wudrivers list                        # the bundles Windows Update holds for it
wudrivers download -x -o drivers      # download and unpack them
```

For another machine, give its SMBIOS strings in the format `fwupdtool hwids` prints, or its CHIDs:

```
wudrivers list --hwids machine.txt
wudrivers list --chid 9b723570-d493-5541-ae58-49087512f816
```

| Option | |
| --- | --- |
| `--arch arm64\|amd64` | The Windows architecture to ask for (default `arm64`) |
| `--json` | `list` prints the bundles' metadata, including every file's name, size and digests |
| `-x`, `--extract` | Unpack each cabinet into a folder named after the INF inside it |
| `--keep-cabs` | Keep the signed cabinets next to the unpacked folders |
| `--only GLOB` | Only cabinets holding a file that matches, like `'*.mbn'` or `'qcsubsys*.inf'` |
| `--update ID` | Only the bundle with this update ID, when a machine has several |
| `-j N` | Downloads at the same time (default 8) |

Each bundle lands in `<output>/<CHID>-<version>/`, with its metadata in `bundle.json`.

### One file, for build recipes

`wudrivers fetch` downloads a single file of an update by its update ID, revision and SHA-1, which
`list --json` prints. It needs no hardware IDs, so a recipe can pin a driver cabinet and get a fresh
link for it every time it builds:

```
wudrivers fetch wu://8ac5f653-c97b-4f51-b034-fe17f2f70501/1/02d248b2f6c65de7fae9e7d13154e332d7607a8b -o driver.cab
```

With makepkg, `wu://` becomes a source protocol through `DLAGENTS`, and the recipe's own checksums
apply as for any other source:

```
makedepends=('wudrivers')
DLAGENTS+=('wu::/usr/bin/wudrivers fetch %u -o %o')
source=('qcsubsys_ext_adsp8380.cab::wu://8ac5f653-c97b-4f51-b034-fe17f2f70501/1/<SHA-1>')
```

## Notes

- The service's TLS certificates chain to Microsoft's own update root, which public trust stores don't
  carry, so they aren't verified. Only metadata comes over that channel, and every downloaded file is
  checked against the digests in it.
- Download links expire after a while. Run `wudrivers` again for fresh ones instead of saving them.
- An update can be withdrawn or replaced by a newer revision. Keep the files you depend on.
- The drivers belong to their makers and Microsoft. `wudrivers` fetches what Windows Update serves to
  the machine; it doesn't redistribute anything.

## License

MIT
