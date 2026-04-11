from pymongo import MongoClient
from app.config.settings import settings

client = MongoClient(
	settings.MONGO_URI,
	serverSelectionTimeoutMS=settings.MONGO_SERVER_SELECTION_TIMEOUT_MS,
	connectTimeoutMS=settings.MONGO_CONNECT_TIMEOUT_MS,
)
db = client[settings.DB_NAME]