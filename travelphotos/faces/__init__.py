"""Local face detection, recognition and filtering (issue #6).

Everything in this package runs on this computer. No module here imports a
network library, and tests check that (tests/test_faces_offline.py). The
model files are fetched once by launcher/download_models.py, outside the
travelphotos package. See docs/decisions/0009-local-face-recognition.md.
"""
