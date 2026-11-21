"""Look up one word's citation reading in a local synthetic dictionary."""

import argparse
import json
import sys
from pathlib import Path


def lookup_word(source, word_id):
    if not isinstance(source, dict):
        raise ValueError("source must be an object")
    words = source.get("words")
    letters = source.get("letters")
    if not isinstance(words, dict) or not isinstance(letters, dict):
        raise ValueError("words and letters must be objects")
    word = words.get(word_id)
    if not isinstance(word, dict):
        raise ValueError(f"unknown word: {word_id}")
    spelling = word.get("text")
    stress = word.get("stress")
    if not isinstance(spelling, str) or not spelling:
        raise ValueError(f"invalid spelling for {word_id}")
    if stress is not None and (type(stress) is not int or not 0 <= stress < len(spelling)):
        raise ValueError(f"invalid stress for {word_id}")
    reading = []
    for char in spelling:
        entry = letters.get(char)
        if not isinstance(entry, dict):
            raise ValueError(f"missing character: {char}")
        rime, tone = entry.get("rime"), entry.get("tone")
        if not isinstance(rime, str) or not rime or type(tone) is not int or tone not in (1, 2, 3):
            raise ValueError(f"invalid citation reading: {char}")
        reading.append({"char": char, "rime": rime, "tone": tone})
    return {"word": word_id, "text": spelling, "stress": stress, "reading": reading}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("word")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf8"))
        if not isinstance(data, dict):
            raise ValueError("input must be an object")
        result = lookup_word(data.get("source"), args.word)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
