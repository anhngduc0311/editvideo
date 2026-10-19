import asyncio
from pathlib import Path
import edge_tts

TEXT = "調査は、シタバナ（ホアスア）が多く植えられている路線を重点的に対象としており、特に人口密集地や住宅地、学校、病院の周辺、ならびに花の香りが日常生活に影響を及ぼしていると住民から苦情や意見が寄せられた地域を中心に行われます。"

async def main():
    output = Path(__file__).with_name("japanese_male_narration.mp3")
    await edge_tts.Communicate(TEXT, "ja-JP-KeitaNeural", rate="-5%").save(str(output))
    print(f"Saved {output} ({output.stat().st_size} bytes)")

if __name__ == "__main__":
    asyncio.run(main())
