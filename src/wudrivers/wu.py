"""A small client for Windows Update's delivery service (fe3), enough to find and fetch the driver
bundles a PC maker publishes for a machine.

Windows 11 asks the service about one "product" per computer hardware ID, named
"{CHID}_<arch>". A maker's bundle for the machine (Lenovo calls it "System Hardware Update") is a
ProductRelease update for one of those products. Its files are the maker's driver packages as
signed cabinet files, served from Microsoft's content delivery network through short-lived links.
"""

import base64
import datetime
import os
import random
import re
import ssl
import time
import urllib.error
import urllib.request
import uuid
from html import escape, unescape

SERVICE = "https://fe3cr.delivery.mp.microsoft.com/ClientWebService/client.asmx"
SECURED = "https://fe3.delivery.mp.microsoft.com/ClientWebService/client.asmx/secured"
NS = "http://www.microsoft.com/SoftwareDistribution/Server/ClientWebService"
USER_AGENT = "Windows-Update-Agent/10.0.10011.16384 Client-Protocol/2.50"
OS_VERSION = "10.0.26100.1"

# Category and platform update IDs a Windows 11 client reports as installed, as UUP dump's client
# does. The bundles are published under the drivers category, which needs these to evaluate.
INSTALLED_NON_LEAF = (
    1, 2, 3, 10, 11, 17, 19, 2359974, 2359977, 5143990, 5169043, 5169044, 5169047, 8788830, 8806526,
    9125350, 9154769, 10809856, 23110993, 23110994, 23110995, 23110996, 23110999, 23111000, 23111001,
    23111002, 23111003, 23111004, 24513870, 28880263, 30077688, 30486944, 59830006, 59830007, 59830008,
    60484010, 62450018, 62450019, 62450020, 69801474, 98959022, 98959023, 98959024, 98959025, 98959026,
    105939029, 105995585, 106017178, 107825194, 117765322, 129905029, 130040030, 130040031, 130040032,
    130040033, 133399034, 138372035, 138372036, 139536037, 139536038, 139536039, 139536040, 142045136,
    158941041, 158941042, 158941043, 158941044, 159776047, 160733048, 160733049, 160733050, 160733051,
    160733055, 160733056, 161870057, 161870058, 161870059,
)

# The service's certificates chain to Microsoft's own update root, which public trust stores don't
# carry, so they can't be verified here. Only metadata comes over this channel; every downloaded
# file is checked against the SHA-1 and SHA-256 the metadata gives.
_TLS = ssl._create_unverified_context()


class Error(Exception):
    pass


def _iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _device_ticket():
    """An anonymous device ticket in the shape Windows sends; the service accepts it for lookups."""
    raw = (b"\x13\x000\x02\xc3w\x04\x00\x14\xd5\xbc\xaczf\xde\rP\xbe\xdd\xf9\xbb\xa1l\x87\xed\xb9\xe0\x19\x89\x80\x00"
           + random.randbytes(527) + b"\xb4\x01")
    text = "t=" + base64.b64encode(raw).decode() + "&p="
    return base64.b64encode("".join(c + "\0" for c in text).encode()).decode()


class Client:
    def __init__(self, arch="arm64", timeout=120):
        self.arch = arch
        self.timeout = timeout
        self.ticket = _device_ticket()
        self.cookie = None

    def device_attributes(self):
        return "E:" + "&".join([
            "App=WU_OS", "AppVer=" + OS_VERSION, "OSVersion=" + OS_VERSION,
            "OSArchitecture=" + ("AMD64" if self.arch == "amd64" else self.arch.upper()),
            "DeviceFamily=Windows.Desktop", "InstallationType=Client", "FlightRing=Retail", "OSSkuId=48",
            "IsFlightingEnabled=0", "IsRetailOS=1", "BranchReadinessLevel=CB", "CurrentBranch=ge_release",
        ])

    def _envelope(self, action, body, to):
        now = time.time()
        return f"""<s:Envelope xmlns:a="http://www.w3.org/2005/08/addressing" xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Header>
<a:Action s:mustUnderstand="1">{NS}/{action}</a:Action><a:MessageID>urn:uuid:{uuid.uuid4()}</a:MessageID><a:To s:mustUnderstand="1">{to}</a:To>
<o:Security s:mustUnderstand="1" xmlns:o="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
<Timestamp xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"><Created>{_iso(now)}</Created><Expires>{_iso(now + 300)}</Expires></Timestamp>
<wuws:WindowsUpdateTicketsToken wsu:id="ClientMSA" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd" xmlns:wuws="http://schemas.microsoft.com/msus/2014/10/WindowsUpdateAuthorization">
<TicketType Name="MSA" Version="1.0" Policy="MBI_SSL"><Device>{self.ticket}</Device></TicketType></wuws:WindowsUpdateTicketsToken>
</o:Security></s:Header><s:Body><{action} xmlns="{NS}">{body}</{action}></s:Body></s:Envelope>"""

    def _call(self, action, body, url=SERVICE):
        request = urllib.request.Request(url, data=self._envelope(action, body, url).encode(), headers={
            "User-Agent": USER_AGENT, "Content-Type": "application/soap+xml; charset=utf-8"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=_TLS) as response:
                text = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
        fault = re.search(r"<faultstring[^>]*>(.*?)</faultstring>", text, re.S)
        if fault:
            raise Error(f"{action}: {unescape(fault.group(1))}")
        return text

    def _ensure_cookie(self):
        if self.cookie:
            return
        now = _iso(time.time())
        # A last change long ago makes the service send everything instead of changes since then
        text = self._call("GetCookie", f"<oldCookie><Expiration>{now}</Expiration></oldCookie>"
                          f"<lastChange>2019-01-01T00:00:00Z</lastChange><currentTime>{now}</currentTime><protocolVersion>2.0</protocolVersion>")
        m = re.search(r"<Expiration>(.*?)</Expiration>.*?<EncryptedData>(.*?)</EncryptedData>", text, re.S)
        if not m:
            raise Error("GetCookie: no cookie in the answer")
        self.cookie = m.groups()

    def _sync(self, products, installed):
        self._ensure_cookie()
        body = (f"<cookie><Expiration>{self.cookie[0]}</Expiration><EncryptedData>{self.cookie[1]}</EncryptedData></cookie><parameters>"
                "<ExpressQuery>false</ExpressQuery>"
                f"<InstalledNonLeafUpdateIDs>{''.join(f'<int>{i}</int>' for i in installed)}</InstalledNonLeafUpdateIDs>"
                "<OtherCachedUpdateIDs/><SkipSoftwareSync>false</SkipSoftwareSync><NeedTwoGroupOutOfScopeUpdates>true</NeedTwoGroupOutOfScopeUpdates>"
                "<AlsoPerformRegularSync>true</AlsoPerformRegularSync><ComputerSpec/>"
                "<ExtendedUpdateInfoParameters><XmlUpdateFragmentTypes><XmlUpdateFragmentType>Extended</XmlUpdateFragmentType>"
                "<XmlUpdateFragmentType>LocalizedProperties</XmlUpdateFragmentType></XmlUpdateFragmentTypes><Locales><string>en-US</string></Locales></ExtendedUpdateInfoParameters>"
                "<ClientPreferredLanguages/><ProductsParameters><SyncCurrentVersionOnly>false</SyncCurrentVersionOnly>"
                f"<DeviceAttributes>{escape(self.device_attributes())}</DeviceAttributes>"
                f"<CallerAttributes>{escape('E:Interactive=1&IsSeeker=1&SheddingAware=1&')}</CallerAttributes>"
                f"<Products>{escape(';'.join(products))}</Products></ProductsParameters></parameters>")
        text = self._call("SyncUpdates", body)
        m = re.search(r"<NewCookie><Expiration>(.*?)</Expiration><EncryptedData>(.*?)</EncryptedData>", text)
        if m:
            self.cookie = m.groups()
        return text

    def bundles(self, chids, rounds=6):
        """The maker bundles Windows Update holds for any of these CHIDs."""
        names = {f"{{{c.lower()}}}_{self.arch}" for c in chids}
        products = [f"PN={{{c.lower()}}}_{self.arch}&V=0.0.0.0&Source=SMBIOS" for c in chids]
        installed, found = list(INSTALLED_NON_LEAF), {}
        for _ in range(rounds):
            text = self._sync(products, installed)
            for bundle in _parse_bundles(text):
                if bundle["product"].lower() in names:
                    found[bundle["update_id"]] = bundle
            new = [int(i) for i, leaf in re.findall(r"<UpdateInfo><ID>(\d+)</ID>.*?<IsLeaf>(\w+)</IsLeaf>", text, re.S)
                   if leaf == "false" and int(i) not in installed]
            if not new:
                break
            installed += new
        return sorted(found.values(), key=lambda b: b["product"])

    def file_urls(self, update_id, revision=1):
        """{SHA-1 (base64): fresh download link} for the files of one update."""
        body = (f"<updateIDs><UpdateIdentity><UpdateID>{update_id}</UpdateID><RevisionNumber>{revision}</RevisionNumber></UpdateIdentity></updateIDs>"
                "<infoTypes><XmlUpdateFragmentType>FileUrl</XmlUpdateFragmentType><XmlUpdateFragmentType>FileDecryption</XmlUpdateFragmentType></infoTypes>"
                f"<deviceAttributes>{escape(self.device_attributes())}</deviceAttributes>")
        text = self._call("GetExtendedUpdateInfo2", body, SECURED)
        return {d: unescape(u) for d, u in re.findall(r"<FileLocation><FileDigest>(.*?)</FileDigest><Url>(.*?)</Url>", text)}


def _parse_bundles(text):
    """ProductRelease updates in a SyncUpdates answer, with their title, version and files."""
    identities = {}
    for rev, xml in re.findall(r"<UpdateInfo><ID>(\d+)</ID>.*?<Xml>(.*?)</Xml>", text, re.S):
        m = re.search(r'UpdateID="([^"]+)" RevisionNumber="(\d+)"', unescape(xml))
        if m:
            identities[rev] = (m.group(1), int(m.group(2)))
    fragments = {}
    for rev, xml in re.findall(r"<Update><ID>(\d+)</ID><Xml>(.*?)</Xml>", text, re.S):
        fragments.setdefault(rev, []).append(unescape(xml))
    out = []
    for rev, parts in fragments.items():
        xml = "".join(parts)
        props = re.search(r"<ExtendedProperties ([^>]*)>", xml)
        if not props or 'ContentType="ProductRelease"' not in props.group(1) or rev not in identities:
            continue
        attr = dict(re.findall(r'(\w+)="([^"]*)"', props.group(1)))
        title = re.search(r"<Title>(.*?)</Title>", xml, re.S)
        files = []
        for f in re.finditer(r"<File ([^>]*)>(.*?)</File>", xml, re.S):
            a = dict(re.findall(r'(\w+)="([^"]*)"', f.group(1)))
            sha256 = re.search(r'<AdditionalDigest Algorithm="SHA256">(.*?)</AdditionalDigest>', f.group(2))
            files.append({"name": a.get("FileName"), "size": int(a.get("Size", 0)), "sha1": a.get("Digest"),
                          "sha256": sha256.group(1) if sha256 else None})
        update_id, revision = identities[rev]
        out.append({"update_id": update_id, "revision": revision, "revision_id": int(rev),
                    "title": unescape(title.group(1)).strip() if title else None,
                    "product": attr.get("ProductName", ""), "version": attr.get("ReleaseVersion"),
                    "size": int(attr.get("MaxDownloadSize", 0)), "files": files})
    return out
