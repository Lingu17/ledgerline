"""Turn a pytest JUnit report into GitHub Actions error annotations (readable via the public checks API)."""
import sys
import xml.etree.ElementTree as ET

failed = 0
for case in ET.parse(sys.argv[1]).getroot().iter("testcase"):
    for bad in list(case.findall("failure")) + list(case.findall("error")):
        failed += 1
        if failed <= 40:
            msg = (bad.get("message") or "").replace("\n", " ")[:300].replace("%", "%25")
            print(f"::error title={case.get('classname')}.{case.get('name')}::{msg}")
print(f"{failed} failing tests")
sys.exit(1 if failed else 0)
