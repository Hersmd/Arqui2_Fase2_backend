def event_document(data):
    return {
        "type": data.get("type"),
        "material": data.get("material"),
        "result": data.get("result"),
        "line": data.get("line"),
        "timestamp": data.get("timestamp")
    }