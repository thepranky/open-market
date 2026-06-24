from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Postgres + pgvector
    database_url: str = "postgresql://compmap:compmap_local@localhost:5432/compmap"

    # Google embeddings
    google_api_key: str = ""
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768

    # Semantic search
    semantic_top_k: int = 10
    semantic_similarity_threshold: float = 0.5

    # Data paths
    data_cases_path: str = "/data/cases"
    data_case_index_path: str = "/data/case_index"

    app_title: str = "Meridian API"
    app_version: str = "0.1.0"
    debug: bool = False


settings = Settings()
