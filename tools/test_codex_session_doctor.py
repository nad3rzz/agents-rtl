from copy import deepcopy

from codex_session_doctor import REMOVED_IMAGE_VALUE
from codex_session_doctor import remove_images_from_structure


def build_empty_clean_stats():
    return {
        "removed_input_image_items": 0,
        "removed_image_text_tags": 0,
        "removed_image_strings": 0,
        "removed_input_image_dicts": 0,
        "cleared_image_lists": 0,
        "removed_image_url_fields": 0,
        "removed_inline_data_images": 0,
    }


def test_image_cleanup_preserves_json_null_values():
    stats = build_empty_clean_stats()
    original = {
        "type": "event_msg",
        "payload": {
            "rate_limits": {
                "secondary": None,
                "individual_limit": None,
            },
            "content": [
                {"type": "input_text", "text": "keep"},
                {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
                None,
            ],
            "nullable_list": [None, {"value": None}],
            "thumbnail": {
                "image_url": "data:image/png;base64,BBBB",
                "label": None,
            },
        },
    }

    cleaned = remove_images_from_structure(original, stats)

    assert cleaned is not REMOVED_IMAGE_VALUE
    assert cleaned == {
        "type": "event_msg",
        "payload": {
            "rate_limits": {
                "secondary": None,
                "individual_limit": None,
            },
            "content": [
                {"type": "input_text", "text": "keep"},
                None,
            ],
            "nullable_list": [None, {"value": None}],
            "thumbnail": {"label": None},
        },
    }
    assert stats["removed_input_image_items"] == 1
    assert stats["removed_image_url_fields"] == 1


def test_non_image_records_are_unchanged():
    original = {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "secondary": None,
                "individual_limit": None,
                "limit_name": None,
                "rate_limit_reached_type": None,
                "spend_control_reached": None,
            },
            "values": [None, False, 0, "", [], {}],
        },
    }
    stats = build_empty_clean_stats()
    assert remove_images_from_structure(original, stats) == original
    assert not any(stats.values())


def test_completed_user_message_removes_whole_image_items():
    original = {
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "completed_at_ms": None,
            "item": {
                "type": "userMessage",
                "id": "message-1",
                "content": [
                    {"type": "text", "text": "keep", "text_elements": []},
                    {"type": "image", "image_url": "data:image/png;base64,AAAA"},
                ],
            },
        },
    }
    untouched = deepcopy(original)
    expected = deepcopy(original)
    expected["payload"]["item"]["content"].pop()
    stats = build_empty_clean_stats()
    cleaned = remove_images_from_structure(original, stats)
    assert original == untouched
    assert cleaned == expected
    assert stats["removed_image_url_fields"] == 1
    assert remove_images_from_structure(cleaned, build_empty_clean_stats()) == cleaned


def test_invalid_image_item_requires_recovery():
    try:
        remove_images_from_structure({"type": "image"}, build_empty_clean_stats())
    except ValueError as error:
        assert "missing image_url" in str(error)
    else:
        raise AssertionError("A broken image item was silently cleaned")


def test_null_and_removed_image_are_distinct():
    assert remove_images_from_structure(None, build_empty_clean_stats()) is None
    assert remove_images_from_structure(
        {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
        build_empty_clean_stats(),
    ) is REMOVED_IMAGE_VALUE
    assert remove_images_from_structure(
        [None, {"image": {"type": "input_image", "image_url": "url"}, "value": None}],
        build_empty_clean_stats(),
    ) == [None, {"value": None}]


def main():
    tests = (
        test_image_cleanup_preserves_json_null_values,
        test_non_image_records_are_unchanged,
        test_completed_user_message_removes_whole_image_items,
        test_invalid_image_item_requires_recovery,
        test_null_and_removed_image_are_distinct,
    )
    for test in tests:
        test()
    print(f"codex_session_doctor tests: {len(tests)} passed")


if __name__ == "__main__":
    main()
