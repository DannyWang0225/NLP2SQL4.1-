# -*- coding: utf-8 -*-
import requests
import json
from config import LLM_API_URL, GEMINI_API_KEY

def call_llm_api(prompt, is_json_output=False):
    """
    A helper function to call the Gemini API.
    
    Args:
        prompt (str): The prompt to send to the model.
        is_json_output (bool): Whether to request JSON format output from the model.
        
    Returns:
        str: The content returned by the model or an error message.
    """
    if is_json_output:
        # Add instruction for JSON output to the prompt
        prompt += "\n\nPlease provide the output in a valid JSON format."

    request_data = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    }

    headers = {
        'Content-Type': 'application/json',
        'X-goog-api-key': GEMINI_API_KEY
    }

    try:
        response = requests.post(
            LLM_API_URL,
            headers=headers,
            data=json.dumps(request_data),
            timeout=60
        )
        response.raise_for_status()
        response_json = response.json()
        # Extract the text from the response
        content = response_json['candidates'][0]['content']['parts'][0]['text']
        return content
    except requests.exceptions.RequestException as e:
        return f"Error: Failed to call the Gemini API. Details: {e}"
    except (KeyError, IndexError) as e:
        return f"Error: The data format returned from the Gemini API is incorrect. Details: {e}"
    except Exception as e:
        return f"An unknown error occurred while calling the model: {e}"
