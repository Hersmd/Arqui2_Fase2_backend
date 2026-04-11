def kpi_document(data):
    return {
        "date": data.get("date"),
        "plastic": data.get("plastic", 0),
        "glass": data.get("glass", 0),
        "metal": data.get("metal", 0),
        "rejects": data.get("rejects", 0),
        "throughput": data.get("throughput", 0)
    }