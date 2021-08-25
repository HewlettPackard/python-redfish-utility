# -*- mode: python -*-
import os
import sys
import compileall

block_cipher = None

def hiddenImportGet():
    tl = []
    classNames = []
    _Commands = {}

    extensionDir = os.path.dirname(os.getcwd()+ '/src')

    replacement = '/'

    for (cwd, dirs, filenames) in os.walk(extensionDir):
        dirs[:] = [d for d in dirs if not d[0] == '.']
        tl.append((cwd,[files for files in filenames if not files[0] == '.']))

    for cwd, names in tl:
        cn = cwd.split('extensions')[-1]
        cn = cn.replace(replacement, '.')
        for name in names:
            if '.pyc' in name and '__init__' not in name:
                name = name.replace('.pyc', '')
                classNames.append('extensions'+cn+'.'+name)

    if sys.version_info[0] == 2:
        classNames.append('urllib2')

    return classNames

def getData():
    datalist = []
    extensionDir = os.path.dirname(os.getcwd()+ '/src/extensions/')
    for (cwd, dirs, _) in os.walk(extensionDir):
        for dir in dirs:
            tempstr = cwd.split('/src/')[-1]+'/'+dir+'/'
            datalist.append(('./src/' + tempstr + '*.pyc', tempstr))
    return datalist

compileall.compile_dir('.', force=True, quiet=True, legacy=True)

a = Analysis(['.//src//rdmc.py'],
                pathex=[],
                binaries=None,
                datas=getData(),
                hiddenimports=hiddenImportGet(),
                hookspath=[],
                runtime_hooks=[],
                excludes=[],
                cipher=block_cipher)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz,
            a.scripts,
            a.binaries,
            a.zipfiles,
            a.datas,
            name='ilorest',
            debug=False,
            strip=False,
            upx=True,
            console=True )
