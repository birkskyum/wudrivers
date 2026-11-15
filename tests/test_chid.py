import unittest

from wudrivers import chid

# An IdeaPad 5 2-in-1 14Q8X9 as `fwupdtool hwids` prints it, with the CHIDs Windows derives
HWIDS = """BiosVendor: LENOVO
BiosVersion: Q1CN25WW
BiosMajorRelease: 1
BiosMinorRelease: 25
Manufacturer: LENOVO
Family: IdeaPad 5 2-in-1 14Q8X9
ProductName: 83GH
ProductSku: LENOVO_MT_83GH_BU_idea_FM_IdeaPad 5 2-in-1 14Q8X9
EnclosureKind: 1f
BaseboardManufacturer: LENOVO
BaseboardProduct: LNVNB161216
"""
EXPECTED = [
    "db0cb253-2dc7-5164-8ce7-6ed312c1dd9b", "72fe9329-cc32-5032-8714-d7ec08a9d441", "aa4cb99b-c4ff-56a4-8b63-ab59db887972",
    "d622845f-0305-5b33-b081-b7519488ed65", "9b723570-d493-5541-ae58-49087512f816", "eb458c6d-45b2-5299-95b7-87723235240e",
    "920bf110-b027-51fc-97e5-bb9b46e78c75", "9276913a-a9da-5237-b4e8-c8502197264a", "a8a28ecb-200f-59c6-8fe3-62fa670fb80d",
    "24248bed-dbd2-5e4f-ba41-4e03a09b904a", "68320834-1316-5dad-babf-ae31cc3ff58c", "d15b437b-55bf-5bd8-8a88-eb4b9e54cb97",
    "32b7e294-a252-5a72-b3c6-6197f08c64f1",
]


class ChidTest(unittest.TestCase):
    def test_from_text(self):
        fields, _ = chid.from_text(HWIDS)
        got = [c for n, c in chid.chids(fields) if n != 13 and n != 14]
        self.assertEqual(got, EXPECTED)

    def test_sysfs_numbers(self):
        # sysfs gives the chassis type and BIOS release in decimal
        fields, _ = chid.from_text(HWIDS)
        fields.update(EnclosureKind="1f")
        decimal = dict(fields, BiosMajorRelease="1", BiosMinorRelease="25")
        self.assertEqual(chid.chids(fields), chid.chids(decimal))


if __name__ == "__main__":
    unittest.main()
