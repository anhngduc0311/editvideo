"""Exercise the real installer's automatic Ready-page transition with a tiny payload."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
folder = root / 'build' / 'installer-flow-test'
folder.mkdir(exist_ok=True)
source = (root / 'packaging/installer.iss').read_text()
code = source.split('[Code]', 1)[1]
fixture = f'''[Setup]
AppName=EditVideo Installer Flow Test
AppVersion=1.0
DefaultDirName={folder / 'installed'}
PrivilegesRequired=lowest
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
Uninstallable=no
CreateUninstallRegKey=no
OutputDir={folder}
OutputBaseFilename=flow-test
[Files]
Source: "{root / 'README.md'}"; DestDir: "{{app}}"
[Code]
{code}
'''
script = folder / 'test.iss'
script.write_text(fixture, encoding='utf-8')
subprocess.run([str(root / 'build/tools/InnoSetup/ISCC.exe'), '/Q', str(script)], check=True)
# No /SILENT: this verifies the same automatic page transition as double-click.
subprocess.run([str(folder / 'flow-test.exe'), '/SP-', '/NORESTART'], check=True, timeout=30)
assert (folder / 'installed/README.md').is_file()
print('PASS: normal installer launch installs and exits without clicking Install')
