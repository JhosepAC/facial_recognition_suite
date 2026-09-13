"""
Tests for HSV-based color classification (eyes/hair) and for the color filter
in comparative search. Does not depend on insightface/mediapipe.
"""
import pytest

from app.services.person_service import _matches_color_filter
from app.vision.face_attributes import (
    FaceAttributes,
    classify_eye_color_hsv,
    classify_hair_color_hsv,
)


@pytest.mark.parametrize("h,s,v,esperado", [
    (0, 0, 20, "negro"),
    (10, 10, 200, "gris"),
    (15, 60, 80, "marrón"),
    (60, 80, 70, "verde"),
    (110, 90, 90, "azul"),
    (170, 80, 90, "marrón"),
])
def test_classify_eye_color_hsv(h, s, v, esperado):
    assert classify_eye_color_hsv(h, s, v) == esperado


@pytest.mark.parametrize("h,s,v,esperado", [
    (0, 0, 30, "negro"),
    (0, 0, 100, "gris"),
    (0, 0, 200, "canoso"),
    (30, 60, 190, "rubio"),
    (5, 80, 90, "pelirrojo"),
    (20, 80, 90, "castaño"),
])
def test_classify_hair_color_hsv(h, s, v, esperado):
    assert classify_hair_color_hsv(h, s, v) == esperado


def test_color_roundtrip_dict():
    attrs = FaceAttributes(color_ojos="azul", color_pelo="rubio")
    data = attrs.to_dict()
    restored = FaceAttributes.from_dict(data)
    assert restored.color_ojos == "azul"
    assert restored.color_pelo == "rubio"


def test_color_invalido_se_normaliza_a_none():
    data = {"color_ojos": "magenta", "color_pelo": 123}
    restored = FaceAttributes.from_dict(data)
    assert restored.color_ojos is None
    assert restored.color_pelo is None


def test_matches_color_filter():
    attrs = FaceAttributes(color_ojos="verde", color_pelo="negro")
    assert _matches_color_filter(attrs, None, None)
    assert _matches_color_filter(attrs, "verde", None)
    assert _matches_color_filter(attrs, None, "negro")
    assert _matches_color_filter(attrs, "verde", "negro")
    assert not _matches_color_filter(attrs, "azul", None)
    assert not _matches_color_filter(attrs, None, "rubio")
    assert not _matches_color_filter(attrs, "verde", "rubio")


def test_matches_color_filter_sin_atributos():
    assert _matches_color_filter(None, None, None)
    assert not _matches_color_filter(None, "verde", None)
    assert not _matches_color_filter(None, "verde", "negro")
