def state_document(data):
    return {
        "parking": data.get("parking"),
        "door": data.get("door"),
        "barrier": data.get("barrier"),
        "conveyor": data.get("conveyor"),
        "lighting": data.get("lighting"),
        "timestamp": data.get("timestamp")
    }