# -*- mode: python -*-
import os

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
            if '.pyc' not in name and '__init__' not in name:
                name = name.replace('.py', '')
                classNames.append('extensions'+cn+'.'+name)
    return classNames

a = Analysis(['.//src//rdmc.py'],
             pathex=[],
             binaries=None,
             datas=[('.//src//extensions', 'extensions')],
             hiddenimports=hiddenImportGet(),
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             cipher=block_cipher)

pyz = PYZ(a.pure, a.zipped_data,
          cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='ilorest',
          debug=False,
          strip=False,
          upx=True,
          icon = './/win32//HPcircle.ico',
          console=True )
