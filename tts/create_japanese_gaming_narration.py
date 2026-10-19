import asyncio
from pathlib import Path

import edge_tts

from create_japanese_narration import TEXT


async def main():
    output = Path(__file__).with_name("japanese_male_minecraft_energetic.mp3")
    await edge_tts.Communicate(
        TEXT,
        "ja-JP-KeitaNeural",
        rate="+18%",
        pitch="+18Hz",
        volume="+5%",
    ).save(str(output))
    print(f"Saved {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
