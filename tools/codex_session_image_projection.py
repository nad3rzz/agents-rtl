"""Plan image removal from native projected user items without deleting messages."""

import json

ITEM_TABLE_KEYS = {
    "thread_items": ("thread_id", "turn_id", "item_id"),
    "thread_realtime_items": ("thread_id", "item_id"),
}


def inline_images(value):
    images = []
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str) and item.startswith("data:image/"):
            images.append(item)
    return images


def projected_items(connection, thread_id):
    result = {}
    for table, keys in ITEM_TABLE_KEYS.items():
        cursor = connection.execute(
            f"SELECT * FROM {table} WHERE thread_id=? ORDER BY {','.join(keys)}", (thread_id,)
        )
        names = [column[0] for column in cursor.description]
        required = {*keys, "rollout_ordinal", "item_json", "item_type"}
        if table == "thread_items":
            required.add("updated_at_ordinal")
        if not required.issubset(names):
            raise ValueError(f"Unsupported image projection columns: {table}")
        result[table] = [dict(zip(names, row, strict=True)) for row in cursor]
    return result


def clean_projected_user_image(item, source_item):
    if item.get("type") != "userMessage" or source_item.get("type") != "UserMessage":
        raise ValueError("Only proved native UserMessage image projections are supported")
    if item.get("id") != source_item.get("id") or item.get("clientId") != source_item.get("client_id"):
        raise ValueError("Source and projected user-message identities differ")
    projected_content, source_content = item.get("content"), source_item.get("content")
    if not isinstance(projected_content, list) or not isinstance(source_content, list):
        raise TypeError("User message content must be a list")
    if len(projected_content) != len(source_content):
        raise ValueError("Source and projected user-message content lengths differ")
    retained = []
    for projected, source in zip(projected_content, source_content, strict=True):
        if not isinstance(projected, dict) or not isinstance(source, dict):
            raise TypeError("User message content entries must be objects")
        if projected.get("type") == "image":
            if set(projected) != {"type", "detail", "url"} or set(source) != {"type", "image_url"}:
                raise ValueError("Unknown projected/source image shape")
            if source["type"] != "image" or projected["url"] != source["image_url"]:
                raise ValueError("Source and projected image bytes differ")
            if not isinstance(projected["url"], str) or not projected["url"].startswith("data:image/"):
                raise ValueError("Probe supports inline image URLs only")
        else:
            if projected != source:
                raise ValueError("Non-image content differs between source and projection")
            retained.append(projected)
    if not retained:
        raise ValueError("Image-only message semantics are not verified; refusing empty content")
    cleaned = {**item, "content": retained}
    if inline_images(cleaned):
        raise ValueError("Unrecognized inline image remains in projected item")
    return cleaned


def plan_projected_images(connection, thread_id, positions):
    snapshot = projected_items(connection, thread_id)
    updates = []
    for table, rows in snapshot.items():
        for row in rows:
            item = json.loads(row["item_json"])
            if not inline_images(item):
                continue  # Explicitly unchanged, image-free projected item.
            if table == "thread_realtime_items":
                raise ValueError("Realtime image cleanup is not verified; complete the turn first")
            ordinal = row["updated_at_ordinal"]
            if type(ordinal) is not int or ordinal not in positions:
                raise ValueError("Projected image has no proved source ordinal")
            record = positions[ordinal]["record"]
            if record is None or record.get("type") != "event_msg":
                raise ValueError("Projected image source is not a native event")
            event = record["payload"]
            if event.get("type") != "item_completed" or event.get("turn_id") != row["turn_id"]:
                raise ValueError("Projected image source turn/event differs")
            if row["item_type"] != "userMessage":
                raise ValueError("Unsupported projected image item type")
            cleaned = clean_projected_user_image(item, event["item"])
            updates.append({
                "table": table, "key": {key: row[key] for key in ITEM_TABLE_KEYS[table]},
                "old_json": row["item_json"], "new_json": json.dumps(cleaned, ensure_ascii=False),
            })
    return snapshot, updates


def apply_projected_images(connection, updates):
    for update in updates:
        table = update["table"]
        keys = ITEM_TABLE_KEYS[table]
        if set(update["key"]) != set(keys):
            raise ValueError("Invalid projected item identity")
        where = " AND ".join(f"{key}=?" for key in keys)
        changed = connection.execute(
            f"UPDATE {table} SET item_json=? WHERE {where} AND item_json=?",
            (update["new_json"], *(update["key"][key] for key in keys), update["old_json"]),
        ).rowcount
        if changed != 1:
            raise RuntimeError("Projected image changed after planning")


def verify_projected_images(connection, thread_id, snapshot, updates):
    actual = projected_items(connection, thread_id)
    for table, rows in snapshot.items():
        expected = [dict(row) for row in rows]
        for row in expected:
            for update in updates:
                if table == update["table"] and all(row[key] == value for key, value in update["key"].items()):
                    row["item_json"] = update["new_json"]
        if actual[table] != expected:
            raise RuntimeError("Unexpected projected item change outside image content")
        if any(inline_images(json.loads(row["item_json"])) for row in actual[table]):
            raise RuntimeError("Inline image remains in selected thread projection")
