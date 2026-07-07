"""
config.py
Central configuration, loaded from environment variables (.env).
Production-grade with Pydantic validation and multi-provider support.
"""

import os
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()


class BrowserConfig(BaseModel):
    """Browser-related configuration."""
    headless: bool = Field(default=False, description="Run browser without visible window")
    slow_mo_ms: int = Field(default=0, ge=0, le=1000, description="Delay between actions in ms")
    viewport_width: int = Field(default=1280, ge=320, le=4096)
    viewport_height: int = Field(default=800, ge=240, le=2160)
    screenshot_dir: str = Field(default="screenshots")
    
    @property
    def viewport(self) -> dict:
        return {"width": self.viewport_width, "height": self.viewport_height}


class LLMConfig(BaseModel):
    """LLM provider configuration."""
    provider: Literal["groq", "openai", "anthropic"] = Field(
        default="groq", description="LLM provider to use"
    )
    api_key: str = Field(..., description="API key for the LLM provider")
    model_name: str = Field(
        default="groq/qwen/qwen3.6-27b",
        description="Model name in LiteLLM format (e.g., 'groq/llama-3.3-70b-versatile')"
    )
    max_tokens: int = Field(default=4000, ge=100, le=100000)
    temperature: float = Field(default=0.7, ge=0, le=2)
    
    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not v:
            raise ValueError("API key is required. Set it in .env file.")
        return v


class AgentConfig(BaseModel):
    """Agent runtime configuration."""
    max_steps: int = Field(default=25, ge=1, le=100)
    max_memory_items: int = Field(default=5, ge=1, le=20)
    summary_max_chars: int = Field(default=160, ge=50, le=500)
    max_rate_limit_retries: int = Field(default=6, ge=0, le=10)
    rate_limit_backoff_seconds: float = Field(default=25.0, ge=1, le=60)


class Config(BaseModel):
    """Main configuration container."""
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    llm: LLMConfig
    agent: AgentConfig = Field(default_factory=AgentConfig)
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def load_config() -> Config:
    """Load and validate configuration from environment."""
    # Map environment variables to config
    llm_provider = os.getenv("LLM_PROVIDER", "groq")
    api_key = os.getenv("GROQ_API_KEY", "")
    
    # Support multiple provider API keys
    if llm_provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
    elif llm_provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
    
    return Config(
        browser=BrowserConfig(
            headless=os.getenv("HEADLESS", "false").lower() == "true",
            slow_mo_ms=int(os.getenv("SLOW_MO_MS", "0")),
            viewport_width=int(os.getenv("VIEWPORT_WIDTH", "1280")),
            viewport_height=int(os.getenv("VIEWPORT_HEIGHT", "800")),
            screenshot_dir=os.getenv("SCREENSHOT_DIR", "screenshots"),
        ),
        llm=LLMConfig(
            provider=llm_provider,
            api_key=api_key,
            model_name=os.getenv("MODEL_NAME", "groq/qwen/qwen3.6-27b"),
            max_tokens=int(os.getenv("MAX_TOKENS", "4000")),
            temperature=float(os.getenv("TEMPERATURE", "0.7")),
        ),
        agent=AgentConfig(
            max_steps=int(os.getenv("MAX_AGENT_STEPS", "25")),
            max_memory_items=int(os.getenv("MAX_MEMORY_ITEMS", "5")),
            summary_max_chars=int(os.getenv("SUMMARY_MAX_CHARS", "160")),
            max_rate_limit_retries=int(os.getenv("MAX_RATE_LIMIT_RETRIES", "6")),
            rate_limit_backoff_seconds=float(os.getenv("RATE_LIMIT_BACKOFF_SECONDS", "25.0")),
        ),
    )


# Global config instance (loaded once)
config = load_config()

# Export for backward compatibility
GROQ_API_KEY = config.llm.api_key
MODEL_NAME = config.llm.model_name
HEADLESS = config.browser.headless
SLOW_MO_MS = config.browser.slow_mo_ms
VIEWPORT = config.browser.viewport
SCREENSHOT_DIR = config.browser.screenshot_dir
MAX_AGENT_STEPS = config.agent.max_steps
MAX_MEMORY_ITEMS = config.agent.max_memory_items
SUMMARY_MAX_CHARS = config.agent.summary_max_chars
MAX_RATE_LIMIT_RETRIES = config.agent.max_rate_limit_retries
RATE_LIMIT_BACKOFF_SECONDS = config.agent.rate_limit_backoff_seconds