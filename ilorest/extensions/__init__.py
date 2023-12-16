"""find and add dynamic extensions"""
import os

tl = []
classNames = []
Commands = {}

extensionDir = os.path.dirname(__file__)

if os.name != "nt":
    replacement = "/"
else:
    replacement = "\\"

for cwd, dirs, filenames in os.walk(extensionDir):
    dirs[:] = [d for d in dirs if not d[0] == "."]
    tl.append((cwd, [files for files in filenames if not files[0] == "."]))

for cwd, names in tl:
    cn = cwd.split("extensions")[-1]
    cn = cn.replace(replacement, ".")
    comms = []
    for name in names:
        if name.endswith(".pyc") and "__" not in name:
            name = name.replace(".pyc", "")
            classNames.append(cn + "." + name + "." + name)
        elif name.endswith(".py") and "__" not in name:
            name = name.replace(".py", "")
            if name + ".pyc" in names:
                continue
            classNames.append(cn + "." + name + "." + name)
