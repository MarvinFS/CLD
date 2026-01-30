#!/usr/bin/env python
# -*- coding: utf-8 -*-


import unittest
from pathlib import Path
from unittest import TestCase

from pywhispercpp.model import Model, Segment

if __name__ == '__main__':
    pass

WHISPER_CPP_DIR = Path(__file__).parent.parent / 'whisper.cpp'

class TestSegfault(TestCase):
    audio_file = WHISPER_CPP_DIR/ 'samples/jfk.wav'

    def voice_to_text(self, tmp_path):
        # n_threads=1 is 3x faster than n_threads=6 when running in Docker.
        whisper_model = Model('tiny.en-q5_1', n_threads=1)
        segments: list[Segment] = whisper_model.transcribe(tmp_path)
        text = next((segment.text for segment in segments if segment.text and '(' not in segment.text and '[' not in segment.text))
        return text

    def test_sample_file(self):
        expected_text = "ask not what your country can do for you"
        text = self.voice_to_text(str(self.audio_file))
        self.assertIn(expected_text.lower(), text.lower(),
                      f"Expected text '{expected_text}' not found in transcription: '{text}'")


if __name__ == '__main__':
    unittest.main()
