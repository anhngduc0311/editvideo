"""Compare serial and pipelined Japanese clone TTS with a warm CPU model.

Run from the repository: py -3.13 tts\benchmark_japanese_tts.py
Uses the network and temporary audio/cache files; does not change app settings.
"""
import asyncio
from pathlib import Path
import sys
import tempfile
from time import perf_counter

import edge_tts
import static_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "douyin_editor"))
from voice_clone import JapaneseCloneTTSEngine


def main():
    static_ffmpeg.add_paths()
    texts = [
        "みんな、こんにちは！", "今日は新しい島で冒険します。",
        "まずは木を集めましょう。", "ここに家を建てたいですね。",
        "暗くなる前に準備しよう。", "次は洞窟を探してみます。",
        "ダイヤモンドが見つかりました！", "また次の動画で会いましょう。",
    ]
    with tempfile.TemporaryDirectory(prefix="benchmark_clone_") as work:
        engine = JapaneseCloneTTSEngine(cache_dir=Path(work) / "cache")
        engine._load_model()

        async def download(text, source):
            await edge_tts.Communicate(text, "ja-JP-KeitaNeural", rate="+18%",
                                       pitch="+18Hz", volume="+5%").save(str(source))

        started = perf_counter()
        for index, text in enumerate(texts):
            source = Path(work) / f"serial_{index}.mp3"
            asyncio.run(download(text, source))
            engine._convert_source(text, source, f"serial_{index}")
        serial = perf_counter() - started
        started = perf_counter()
        results = engine.synthesize_phrases(texts)
        pipelined = perf_counter() - started
        started = perf_counter()
        cached = JapaneseCloneTTSEngine(cache_dir=engine.cache_dir).synthesize_phrases(texts)
        reused = perf_counter() - started
        assert results == cached
        assert [item[0] for item in results] == texts
        assert all(item[1] and item[2] > 0 for item in results)
        print(f"PASS: {len(texts)} real Japanese phrases, order/durations/audio cache verified")
        print(f"Serial: {serial:.2f}s; pipelined: {pipelined:.2f}s; cache: {reused:.3f}s")
        print(f"Measured speedup: {serial / pipelined:.2f}x (network conditions affect this result)")


if __name__ == "__main__":
    main()
