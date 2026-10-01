"""Playing a reply while it streams in, and knowing how far playback got."""

import numpy as np
import pytest
import sounddevice as sd

from app import audio_io
from app.audio_io import StreamPlayer

RATE = 1000  # 1 sample = 1 ms, so positions read directly
BLOCK = 50


class FakeOutput:
    """Stands in for the speaker: the test pulls blocks through with play()."""

    last = None

    def __init__(self, samplerate, channels, dtype, callback, finished_callback, device=None):
        self.callback, self.finished_callback = callback, finished_callback
        self.heard: list[int] = []
        self.stopped = self.aborted = False
        FakeOutput.last = self

    def start(self):
        pass

    def play(self, blocks=1):
        for _ in range(blocks):
            if self.stopped:
                return
            out = np.full((BLOCK, 1), -1, dtype=np.int16)
            try:
                self.callback(out, BLOCK, None, None)
            except sd.CallbackStop:
                self.stopped = True
                self.finished_callback()
            self.heard += out[:, 0].tolist()

    def abort(self):
        self.aborted = True

    def close(self):
        pass


@pytest.fixture()
def player(qapp, monkeypatch):
    monkeypatch.setattr(audio_io.sd, "OutputStream", FakeOutput)
    monkeypatch.setattr(StreamPlayer, "LEAD_IN_SECONDS", 0.0)
    p = StreamPlayer()
    p.played, p.drain_count = [], [0]
    p.sentence_played.connect(p.played.append)
    p.drained.connect(lambda: p.drain_count.__setitem__(0, p.drain_count[0] + 1))
    return p


def pcm(value: int, ms: int) -> bytes:
    return np.full(ms * RATE // 1000, value, dtype=np.int16).tobytes()


def flush(qapp):
    qapp.processEvents()


def test_sentences_play_back_to_back_in_order(qapp, player):
    player.start(RATE)
    player.feed(0, pcm(1, 30))
    player.feed(0, pcm(2, 40))
    player.feed(1, pcm(3, 50))
    player.end()
    FakeOutput.last.play(3)
    flush(qapp)
    heard = FakeOutput.last.heard
    assert heard[:120] == [1] * 30 + [2] * 40 + [3] * 50, "no gaps, no reordering"
    assert player.played == [0, 1]
    assert player.drain_count[0] == 1 and not player.active


def test_a_late_chunk_means_silence_not_the_end(qapp, player):
    player.start(RATE)
    player.feed(0, pcm(5, 20))
    FakeOutput.last.play(1)
    assert FakeOutput.last.heard[:50] == [5] * 20 + [0] * 30
    assert not FakeOutput.last.stopped, "still waiting for more"
    player.feed(1, pcm(6, 50))
    player.end()
    FakeOutput.last.play(2)
    flush(qapp)
    assert player.played == [0, 1] and player.drain_count[0] == 1


def test_stopping_says_which_sentence_and_how_far_in(qapp, player):
    player.start(RATE)
    player.feed(0, pcm(1, 100))
    player.feed(1, pcm(2, 300))
    FakeOutput.last.play(4)  # 200 ms: all of sentence 0, 100 ms into sentence 1
    assert player.stop() == (1, pytest.approx(100.0))
    assert FakeOutput.last.aborted and not player.active
    flush(qapp)
    assert player.drain_count[0] == 0, "a stopped reply isn't a finished one"


def test_between_sentences_the_last_one_counts_as_heard_whole(qapp, player):
    player.start(RATE)
    player.feed(0, pcm(1, 100))
    FakeOutput.last.play(3)  # 100 ms of speech, then waiting on sentence 1
    assert player.stop() == (0, pytest.approx(100.0))


def test_stopping_before_any_speech(qapp, player):
    player.start(RATE)
    assert player.stop() == (0, 0.0)
    assert player.stop() is None, "nothing playing any more"


def test_a_new_reply_replaces_the_old_one(qapp, player):
    player.start(RATE)
    player.feed(0, pcm(1, 100))
    first = FakeOutput.last
    player.start(RATE)
    assert first.aborted
    player.feed(0, pcm(9, 50))
    player.end()
    FakeOutput.last.play(2)
    assert FakeOutput.last.heard[:50] == [9] * 50
