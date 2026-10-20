from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

root = Path(SPECPATH).parent
repo = root.parent
vendor = repo / "tts" / "vendor" / "OpenVoice"
datas = [(str(root / "build" / "assets"), ".")]
binaries = []
hiddenimports = ["capcut_tts_api", "openvoice.api", "edge_tts", "audioop"]
for package in ("customtkinter", "whisper", "capcut_tts_api", "librosa", "eng_to_ipa", "inflect", "unidecode", "pypinyin", "cn2an", "jieba"):
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
datas += collect_data_files("yt_dlp")
datas += copy_metadata("yt-dlp", recursive=True)

a = Analysis([str(root / "desktop_entry.py")], pathex=[str(root), str(vendor)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], runtime_hooks=[],
             excludes=["IPython", "pytest", "tensorboard", "matplotlib", "pandas", "torchvision"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="EditVideoStudio",
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="EditVideoStudio")
