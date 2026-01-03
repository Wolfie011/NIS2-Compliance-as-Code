import yara
from pathlib import Path
import os
import time

class YaraScanner:
    _user_path = str(Path.home().home())
    popular_directories = [_user_path+"\\Downloads",_user_path+"\\Documents",_user_path+"\\Desktop",_user_path+"\\AppData\\Local\\Temp"]
    def __init__(self, rules_dir="./yara_rules/misc"):
        self.rules_dir = Path(rules_dir)
        self.rule_files = sorted(list(self.rules_dir.rglob("*.yar")) + list(self.rules_dir.rglob("*.yara")))
        self.filepaths = {f"namespace{i}" : str(p) for i,p in enumerate(self.rule_files)}
        self.rules = self.compile_rules()
    def compile_rules(self) -> yara.Rules:
        rules = None
        try:
            rules = yara.compile(filepaths=self.filepaths)
            rules.save("./yara_rules/compiled_rules.yarc")
        except Exception as e:
            print(f"YaraScanner Exception: \n{e}")
        return rules

    def malware_fast_scan(self,directories=popular_directories,fast=True,timeout=5) -> list[str]:
        result = []
        print(f"Scan started: {time.ctime(time.time())}")
        for d in directories:
            for root, dirs, files in os.walk(d):
                for file in files:
                    try:
                        f_path = root+"\\"+file
                        matches = self.rules.match(filepath=f_path,externals={"filepath":f_path},fast=fast,timeout=timeout)
                        #print(f"Scanning: {f_path}")
                        if matches:
                            print(f"[!] File matched yara rule: {f_path}")
                            result.append(f_path)
                    except Exception as e:
                        print(e)
        print(f"Scan finished: {time.ctime(time.time())}")
        print("Detected files:")
        [print(x) for x in result]
        return result
    def malware_full_scan(self) -> list[str]:
        self.malware_fast_scan(directories=["C:\\"],timeout=15)

if __name__ == '__main__':
    sc = YaraScanner()
    sc.malware_fast_scan()