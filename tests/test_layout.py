from displaypad_server.core.layout import generate_layout


def test_generate_layout_6_buttons() -> None:
    layout = generate_layout(6, 240, 320)
    assert len(layout) == 6
    assert layout[0].slot == 1


def test_generate_layout_32_buttons() -> None:
    layout = generate_layout(32, 240, 320)
    assert len(layout) == 32
    assert all(rect.w > 0 and rect.h > 0 for rect in layout)
