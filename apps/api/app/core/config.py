from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "compmap_local"

    data_cases_path: str = "/data/cases"
    data_case_index_path: str = "/data/case_index"

    app_title: str = "CompMap API"
    app_version: str = "0.1.0"
    debug: bool = False


settings = Settings()
