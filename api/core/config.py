import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "ITDA Backend"
    API_V1_STR: str = "/api/v1"
    PORT: int = 8000
    
    # 문화데이터광장 API Key
    CULTURE_API_KEY: str = os.getenv("CULTURE_API_KEY", "your_default_api_key_here")

settings = Settings()
