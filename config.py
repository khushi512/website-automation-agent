"""
Configuration management for the Website Automation Agent.
Loads API keys and task settings from environment variables or .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Groq API key (free tier) — https://console.groq.com/keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Target URL for the automation task
TARGET_URL = "https://ui.shadcn.com/docs/forms/react-hook-form"

# Form values to fill in. 
# Note: The assignment specifies "Name" and "Description" fields. 
# On the Shadcn UI target page, the first form demo (Bug Report) contains "Bug Title" (title) and "Description" fields, which are the main fields to automate.
FORM_VALUES = {
    "title": "khushboo_dev", # Maps to 'Name' (Bug Title input field)
    "description": "Building intelligent GenAI agents and automation pipelines.", # Maps to 'Description' (Description textarea field)
}

# Browser settings
HEADLESS = False          # Set True to run without a visible window
SLOW_MO_MS = 50          # Milliseconds between Playwright actions (helps visibility)
SCREENSHOT_DIR = "screenshots"
VIEWPORT = {"width": 1280, "height": 800}

# Agent loop limits
MAX_AGENT_STEPS = 20     # Hard cap so the loop never runs forever
