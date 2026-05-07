import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "ITDA Backend"
    API_V1_STR: str = "/api/v1"
    PORT: int = 8000

    # AI Hub API Key (aihub.or.kr → 마이페이지 → API 활용신청)
    AIHUB_API_KEY: str = os.getenv("AIHUB_API_KEY", "")

    # 문화데이터광장 API Key
    CULTURE_API_KEY: str = os.getenv("CULTURE_API_KEY", "")

    # Gemini API Key
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # AI Hub Validation Data Path
    AI_HUB_DATA_PATH: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "morpheme")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
