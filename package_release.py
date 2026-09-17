from pathlib import Path
import hashlib
import zipfile
root = Path(__file__).resolve().parent
output = root / 'InkCompanion-1.5-Windows-x64.zip'
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for file in (root / 'dist' / 'InkCompanion-1.5').rglob('*'):
        if file.is_file():
            archive.write(file, Path('InkCompanion-1.5') / file.relative_to(root / 'dist' / 'InkCompanion-1.5'))
    for name in ['README.md', 'PROTOCOL.md', 'VALIDATION.md']:
        archive.write(root / name, name)
    for file in root.glob('*.py'):
        archive.write(file, Path('source') / file.name)
    for name in ['requirements.txt', 'build.ps1', 'setup.ps1', 'start.cmd']:
        archive.write(root / name, Path('source') / name)
    archive.write(root / 'research' / 'screen-test.png', 'test-image.png')
    archive.write(root / 'research' / 'bwr-test-source.png', 'validation/bwr-test-source.png')
    archive.write(root / 'research' / 'bwr-test-preview.png', 'validation/bwr-test-preview.png')
    for position in ['right', 'left', 'top', 'bottom']:
        archive.write(root / 'research' / f'sidebar-{position}.png',
                      f'validation/sidebar-{position}.png')
    for suffix in ['.json', '.log', '.connect.log']:
        file = root / 'research' / ('screen-test-20260914T121550Z' + suffix)
        archive.write(file, Path('validation') / file.name)
    for suffix in ['.json', '.log']:
        file = root / 'research' / ('bwr-screen-test-20260914T133041Z' + suffix)
        archive.write(file, Path('validation') / file.name)
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
print(output)
print('SHA256', hashlib.sha256(output.read_bytes()).hexdigest())
