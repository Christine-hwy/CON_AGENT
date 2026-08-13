import io

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError, CouldntEncodeError


class AudioAssemblyError(Exception):
    pass


def assemble_dialogue(audio_chunks, gaps_ms, output_path):
    """Assemble MP3 chunks with a silence gap between adjacent dialogue turns."""
    if not audio_chunks:
        raise AudioAssemblyError("No audio chunks were provided")

    try:
        combined = AudioSegment.from_file(io.BytesIO(audio_chunks[0]), format="mp3")
        for index in range(1, len(audio_chunks)):
            gap = gaps_ms[index - 1] if index - 1 < len(gaps_ms) else 500
            combined += AudioSegment.silent(
                duration=max(0, int(gap)), frame_rate=combined.frame_rate
            )
            combined += AudioSegment.from_file(
                io.BytesIO(audio_chunks[index]), format="mp3"
            )

        combined.export(output_path, format="mp3")
    except (CouldntDecodeError, CouldntEncodeError, OSError, ValueError) as exc:
        raise AudioAssemblyError(f"Failed to assemble dialogue audio: {exc}") from exc

    return output_path
