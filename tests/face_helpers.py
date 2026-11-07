"""A fake face engine and synthetic photos/videos for the face tests (#6).

A "face" is a coloured 40x40 square in one of three slots on a grey picture.
The fake engine reads each slot's colour and returns a fixed feature vector
for it, so tests control exactly who is in each file. Photo and video files
are real JPEG/MP4 files read through the same code as real ones.
"""

from __future__ import annotations

import contextlib
import math
import os
import socket
from unittest import mock

import numpy as np
from PIL import Image

from travelphotos.faces.engine import Face

DIM = 8
SLOTS = [(10, 20), (70, 20), (130, 20)]
SIZE = 40
GREY = (128, 128, 128)


def _unit(*pairs):
    v = [0.0] * DIM
    for i, x in pairs:
        v[i] = x
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


# colour -> feature vector
ME = (220, 30, 30)
MOM = (30, 200, 30)
STRANGER = (30, 30, 220)
ME_AGAIN = (230, 210, 30)  # me, other angle: similarity 0.9
ME_BLURRY = (230, 120, 20)  # maybe me: similarity 0.32 (uncertain band)
DAD = (200, 30, 200)
VECTORS = {
    ME: _unit((0, 1.0)),
    MOM: _unit((1, 1.0)),
    STRANGER: _unit((2, 1.0)),
    ME_AGAIN: _unit((0, 0.9), (4, math.sqrt(1 - 0.81))),
    ME_BLURRY: _unit((0, 0.32), (3, math.sqrt(1 - 0.32**2))),
    DAD: _unit((5, 1.0)),
}


class FakeEngine:
    def __init__(self):
        self.calls = 0

    def detect(self, rgb):
        self.calls += 1
        faces = []
        h, w = rgb.shape[:2]
        for x, y in SLOTS:
            cx, cy = x + SIZE // 2, y + SIZE // 2
            if cx >= w or cy >= h:
                continue
            px = tuple(int(v) for v in rgb[cy, cx][:3])
            best = min(VECTORS, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, px)))
            if sum((a - b) ** 2 for a, b in zip(best, px)) < 60**2:
                faces.append(Face(box=(x, y, SIZE, SIZE), score=0.95, embedding=list(VECTORS[best])))
        return faces


def picture(*people) -> Image.Image:
    img = Image.new("RGB", (180, 90), GREY)
    for (x, y), colour in zip(SLOTS, people):
        if colour is not None:
            img.paste(colour, (x, y, x + SIZE, y + SIZE))
    return img


def save_photo(path: str, *people) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    picture(*people).save(path, "JPEG", quality=95)
    return path


def save_video(path: str, appearances: dict, seconds: int = 6, fps: int = 10) -> str:
    """appearances: {colour: (start_s, end_s)} shown in slot 0 during that time."""
    import cv2

    os.makedirs(os.path.dirname(path), exist_ok=True)
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (180, 90))
    assert writer.isOpened()
    for i in range(seconds * fps):
        t = i / fps
        frame = np.full((90, 180, 3), 128, np.uint8)
        for colour, (start, end) in appearances.items():
            if start <= t < end:
                x, y = SLOTS[0]
                frame[y : y + SIZE, x : x + SIZE] = colour[::-1]  # BGR
        writer.write(frame)
    writer.release()
    return path


class NetworkUsed(AssertionError):
    pass


@contextlib.contextmanager
def no_network():
    """Fail any attempt to open a network connection or resolve a name."""

    def refuse(*_a, **_k):
        raise NetworkUsed("network access attempted")

    with mock.patch.object(socket.socket, "connect", refuse), mock.patch.object(
        socket.socket, "connect_ex", refuse
    ), mock.patch.object(socket, "create_connection", refuse), mock.patch.object(socket, "getaddrinfo", refuse):
        yield
