import os
import groq
import config

def test_anyof():
    client = groq.Groq(api_key=os.getenv("GROQ_API_KEY") or config.GROQ_API_KEY)
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "open_browser",
                "description": "Launch the browser.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "headless": {
                            "anyOf": [
                                {"type": "boolean"},
                                {"type": "string"}
                            ],
                            "description": "Run without a visible window.",
                        }
                    },
                    "required": ["headless"],
                },
            },
        }
    ]
    
    try:
        response = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[
                {"role": "system", "content": "Start the browser."},
                {"role": "user", "content": "Launch."}
            ],
            tools=tools,
            tool_choice="auto",
        )
        print("Groq accepted anyOf schema! Response:", response.choices[0].message)
    except Exception as e:
        print("Groq rejected anyOf schema!")
        print(f"Error: {e}")

if __name__ == "__main__":
    test_anyof()
