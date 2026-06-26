import json
import logging
import os
import re
import sys
from typing import Any

import vertexai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from google import genai
from google.cloud import aiplatform_v1beta1 as aip_beta
from google.genai import types
from google.protobuf import struct_pb2
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cookbook_frontend")

# Add parent directory to sys.path to import app.agent functions
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

try:
    from app.agent import (
        check_title_exists,
        get_worksheet,
        save_recipe_to_sheet,
        search_recipes_in_sheet,
    )

    logger.info("Successfully imported app.agent modules.")
except ImportError as e:
    logger.error(f"Failed to import app.agent: {e}")

# Load environment variables
root_env = os.path.join(parent_dir, ".env")
if os.path.exists(root_env):
    logger.info(f"Loading environment from {root_env}")
    load_dotenv(root_env)
else:
    load_dotenv()

# Fallback: check deployment_metadata.json in root if AGENT_RUNTIME_ID is not set
metadata_path = os.path.join(parent_dir, "deployment_metadata.json")
runtime_id = os.environ.get("AGENT_RUNTIME_ID")
if not runtime_id and os.path.exists(metadata_path):
    try:
        with open(metadata_path) as f:
            metadata = json.load(f)
            runtime_id = metadata.get("remote_agent_runtime_id")
            logger.info(
                f"Loaded AGENT_RUNTIME_ID from deployment_metadata.json: {runtime_id}"
            )
    except Exception as e:
        logger.warning(f"Failed to load deployment_metadata.json: {e}")

project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
if not project_id:
    try:
        import google.auth

        _, credentials_project = google.auth.default()
        project_id = credentials_project
        logger.info(f"Discovered GCP Project ID from default credentials: {project_id}")
    except Exception as e:
        logger.warning(f"Could not discover project ID: {e}")

# Region defaults to us-east1
location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-east1")

# Format full runtime ID
if runtime_id and runtime_id.startswith("projects/"):
    parts = runtime_id.split("/")
    location = parts[3]
    full_runtime_id = runtime_id
else:
    full_runtime_id = (
        f"projects/{project_id}/locations/{location}/reasoningEngines/{runtime_id}"
        if project_id and runtime_id
        else ""
    )

logger.info(f"Project ID: {project_id}")
logger.info(f"Location: {location}")
logger.info(f"Runtime Resource ID: {full_runtime_id}")

# Initialize Vertex AI
if project_id and location:
    vertexai.init(project=project_id, location=location)

# Setup GAPIC client for Reasoning Engine Execution Service
try:
    client = aip_beta.ReasoningEngineExecutionServiceClient(
        client_options={"api_endpoint": f"{location}-aiplatform.googleapis.com"}
    )
except Exception as e:
    logger.warning(f"Could not initialize ReasoningEngineExecutionServiceClient: {e}")
    client = None

# Setup Google GenAI Client for direct model queries
genai_client = genai.Client(vertexai=True, project=project_id, location=location)

is_in_cloud_run = "K_SERVICE" in os.environ
default_use_local = "False" if is_in_cloud_run else "True"
USE_LOCAL_AGENT = os.environ.get("USE_LOCAL_AGENT", default_use_local).lower() == "true"
if USE_LOCAL_AGENT:
    logger.info("Using local agent runner pathway.")
else:
    logger.info("Using remote Reasoning Engine pathway.")

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Cookbook Agent Manager Dashboard")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def is_simple_text(text: str) -> bool:
    """Checks if the input text is simple text, and not code, file paths, base64 data, etc."""
    # Check for base64 encoded data
    if "data:" in text and ";base64," in text:
        return False

    # Check for markdown code block markers
    if "```" in text:
        return False

    # Check for XML/HTML tags
    text_lower = text.lower()
    if "<html" in text_lower or "<script" in text_lower or "href=" in text_lower:
        return False

    # Check for file path patterns (e.g., /usr/local/bin)
    if text.startswith("/") and len(text.split("/")) > 3:
        return False
    if ":" in text and "\\" in text and len(text.split("\\")) > 2:
        return False

    lines = text.splitlines()
    for line in lines:
        line_stripped = line.strip()
        line_lower = line_stripped.lower()
        if not line_lower:
            continue

        # Match python import: 'import os' or 'from datetime import datetime'
        if re.match(r"^import\s+\w+(\.\w+)*", line_lower):
            return False
        if re.match(r"^from\s+\w+(\.\w+)*\s+import\s", line_lower):
            return False

        # Match python function def: 'def my_func('
        if re.match(r"^def\s+\w+\s*\(", line_lower):
            return False

        # Match python class def: 'class MyClass:'
        if re.match(r"^class\s+\w+", line_lower):
            return False

        # Match js/ts/c++ function definition: 'function name('
        if re.match(r"^function\s+\w+\s*\(", line_lower):
            return False

        # Match JS variable declarations: 'let x =', 'const y ='
        if re.match(r"^(let|const)\s+[a-zA-Z_$][a-zA-Z0-9_$]*\s*=", line_lower):
            return False

        # Match SQL statements: 'select ... from', 'insert into', 'delete from', 'update ... set'
        if re.match(r"^select\s+.*\s+from\s", line_lower):
            return False
        if re.match(r"^insert\s+into\s", line_lower):
            return False
        if re.match(r"^delete\s+from\s", line_lower):
            return False
        if re.match(r"^update\s+\w+\s+set\s", line_lower):
            return False

    # Check for other non-overlapping programming keywords/constructs
    code_indicators = [
        "include <",
        "#include",
        "public class",
        "fn main()",
        "<?php",
        "alert(",
        "console.log(",
    ]
    for ind in code_indicators:
        if ind in text_lower:
            return False

    return True


# Session Store
# Maps: client_session_id (UUID) -> {
#   "gcp_session_id": str,
#   "current_interrupt_id": Optional[str],
#   "current_flow": Optional[str],             # "recommend_confirming", or None
#   "recommend_results": Optional[List[Dict[str, Any]]]
# }
session_store: dict[str, dict[str, Any]] = {}


# Pydantic Schemas
class ChatRequest(BaseModel):
    message: str
    session_id: str


class ParsedRecipe(BaseModel):
    title: str
    ingredients: list[str]
    steps: list[str]
    category: str


class RecipeParseRequest(BaseModel):
    recipe_text: str


class IntentClassification(BaseModel):
    intent: str  # "save", "recommend", or "fallback"
    search_query: str | None = None


class SelectionResolution(BaseModel):
    matched_title: str | None = None
    is_cancelled: bool = False


class RecipeMatchResponse(BaseModel):
    matched_titles: list[str]


# Helper: Format Recipe Details
def format_recipe_details(recipe: dict[str, Any]) -> str:
    return (
        f"Here are the details for **{recipe['title']}**:\n\n"
        f"**Category:** {recipe['category']}\n\n"
        f"**Ingredients:**\n"
        f"{recipe['ingredients']}\n\n"
        f"**Instructions:**\n"
        f"{recipe['steps']}"
    )


# Helper: Run intent classification via Gemini
async def classify_intent(message: str) -> IntentClassification:
    prompt = f"""
    Analyze the user's message and classify their intent:
    1. "save": The user wants to save or store a new recipe (e.g. "I want to save a recipe", "save dessert recipe").
    2. "recommend": The user is asking for recipe recommendations or what to cook (e.g., "what to cook for dinner", "recipes from banana", "recommend something").
    3. "fallback": Any other general conversation, cooking questions, or greetings.

    For "recommend" intent, also extract the key-words representing ingredients or the type of meal in the search_query field (e.g., "banana", "dinner", "chicken").

    User Message: "{message}"
    """
    try:
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=IntentClassification,
                temperature=0.0,
            ),
        )
        data = json.loads(response.text)
        return IntentClassification(**data)
    except Exception as e:
        logger.error(f"Error classifying intent: {e}")
        return IntentClassification(intent="fallback")


# Helper: Run fuzzy matching selector via Gemini
async def resolve_recipe_selection(
    user_message: str, titles: list[str]
) -> SelectionResolution:
    titles_list = "\n".join([f"- {t}" for t in titles])
    prompt = f"""
    You are an intelligent selector. Here is a list of recipe titles available:
    {titles_list}

    The user was asked which recipe they want details for. They answered: "{user_message}"

    Determine which recipe title from the list best matches the user's input.
    Consider:
    - Typos (e.g. "banana cake" matches "Banana Cake")
    - Ordinals (e.g. "the first one", "first option", "1" matches the first title in the list)
    - Partial matching or synonyms.

    Respond in JSON matching the schema. If the user explicitly wants to cancel, say "no", or stop, set is_cancelled to true.
    """
    try:
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SelectionResolution,
                temperature=0.0,
            ),
        )
        data = json.loads(response.text)
        return SelectionResolution(**data)
    except Exception as e:
        logger.error(f"Error resolving recipe selection: {e}")
        return SelectionResolution(matched_title=None, is_cancelled=False)


# Helper: Semantic Recipe Search using Gemini
async def semantic_recipe_search(query: str) -> list[dict[str, Any]]:
    try:
        worksheet = get_worksheet()
        all_records = worksheet.get_all_records()
        if not all_records:
            return []

        recipe_candidates = []
        for r in all_records:
            recipe_candidates.append(
                {
                    "title": r.get("Title", r.get("title", "")),
                    "category": r.get("Category", r.get("category", "")),
                    "ingredients": r.get("Ingredients", r.get("ingredients", "")),
                }
            )

        prompt = f"""
        You are a semantic recipe search assistant.
        Here is a list of recipes from the cookbook database:
        {json.dumps(recipe_candidates, indent=2)}

        The user is searching for: "{query}"

        Identify all recipes that match the user's request.
        Be flexible and use your language and world knowledge. For example:
        - "Japanese kitchen" or "japanese food" should match Sushi, Ramen, or Tempura.
        - "Dessert" should match sweet items.
        - "Healthy breakfast" should match oatmeal or fruit salads.
        - "Something with banana" should match any recipe containing bananas in title or ingredients.

        Return a JSON list of the exact titles of all matching recipes in the matched_titles field. If no recipes match, return an empty list.
        """
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RecipeMatchResponse,
                temperature=0.0,
            ),
        )
        data = json.loads(response.text)
        matched_titles = data.get("matched_titles", [])

        matches = []
        for title in matched_titles:
            for r in all_records:
                r_title = r.get("Title", r.get("title", ""))
                if r_title.strip().lower() == title.strip().lower():
                    matches.append(
                        {
                            "title": r_title,
                            "ingredients": r.get(
                                "Ingredients", r.get("ingredients", "")
                            ),
                            "steps": r.get("Steps", r.get("steps", "")),
                            "category": r.get("Category", r.get("category", "")),
                        }
                    )
                    break
        return matches
    except Exception:
        logger.exception("Semantic search failed, falling back to substring search")
        return search_recipes_in_sheet(query)


@app.get("/", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def get_dashboard(request: Request):
    """Serves the main chat UI dashboard."""
    index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            return f.read()
    else:
        raise HTTPException(status_code=404, detail="index.html not found")


@app.post("/api/recipe/parse", response_model=ParsedRecipe)
@limiter.limit("5/minute")
async def parse_recipe_endpoint(payload: RecipeParseRequest, request: Request):
    if not is_simple_text(payload.recipe_text):
        raise HTTPException(
            status_code=400,
            detail="Invalid input. Only simple text is allowed (no code, file paths, or encoded data).",
        )
    prompt = f"""
    Parse the following recipe text and extract the details:
    - title
    - ingredients (as a list of separate items)
    - steps (as a list of separate instructions/steps in order)
    - category (the type of recipe, e.g. Dessert, Main Course, Soup, Salad. If the category is not explicitly mentioned, derive it intelligently from the title, ingredients, steps, and sense of the recipe. If multiple categories apply, separate them with a comma, e.g., "Dessert, Snack").

    Recipe Text:
    {payload.recipe_text}
    """
    try:
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ParsedRecipe,
                temperature=0.0,
            ),
        )
        data = json.loads(response.text)
        return ParsedRecipe(**data)
    except Exception as e:
        logger.exception("Failed to parse recipe")
        raise HTTPException(
            status_code=500, detail=f"Failed to parse recipe: {e!s}"
        ) from e


@app.post("/api/recipe/save")
@limiter.limit("5/minute")
async def save_recipe_endpoint(recipe: ParsedRecipe, request: Request):
    """Saves parsed, validated, and user-corrected recipe directly to Google Sheets."""
    title = recipe.title.strip()
    category = recipe.category.strip()

    ingredients_str = "\n".join(
        [item.strip() for item in recipe.ingredients if item.strip()]
    )
    steps_str = "\n".join([item.strip() for item in recipe.steps if item.strip()])

    if not title:
        return {"error": "Recipe title cannot be empty."}

    # Input validations
    if len(title) > 100:
        return {"error": "Recipe title cannot exceed 100 characters."}
    if len(category) > 100:
        return {"error": "Recipe category cannot exceed 100 characters."}
    if len(ingredients_str) > 200:
        return {"error": "Ingredients list cannot exceed 200 characters."}
    if len(steps_str) > 1000:
        return {"error": "Steps list cannot exceed 1000 characters."}

    # Simple text check
    for field_name, field_val in [
        ("title", title),
        ("category", category),
        ("ingredients", ingredients_str),
        ("steps", steps_str),
    ]:
        if not is_simple_text(field_val):
            return {
                "error": f"Invalid input in {field_name}. Only simple text is allowed (no code, file paths, or encoded data)."
            }

    try:
        if check_title_exists(title):
            return {
                "error": f"A recipe with the title '{title}' already exists in the Google Sheet. Please choose a different title."
            }

        result = save_recipe_to_sheet(title, ingredients_str, steps_str, category)
        if result.startswith("Error"):
            return {"error": f"Failed to save recipe: {result}"}

        return {
            "success": True,
            "message": f"Successfully saved '{title}' to Google Sheets!",
        }
    except Exception as e:
        logger.exception("Failed to save recipe to sheet")
        return {"error": f"Failed to save recipe: {e!s}"}


@app.post("/api/chat")
@limiter.limit("5/minute")
async def chat_endpoint(payload: ChatRequest, request: Request):
    """Processes chat message and forwards it to Reasoning Engine or local handler."""
    client_sid = payload.session_id
    user_message = payload.message.strip()

    # Symbol limit check
    if len(user_message) > 2000:
        return {
            "response": "Error: Your message is too long. The maximum allowed length is 2000 symbols."
        }

    # Simple text check
    if not is_simple_text(user_message):
        return {
            "response": "Error: Only simple text is allowed. Code, file paths, or encoded data cannot be processed."
        }

    if not USE_LOCAL_AGENT:
        if not project_id or not full_runtime_id:
            return {
                "error": "Google Cloud Project or Agent Runtime ID environment variables are not set. "
                "Please configure GOOGLE_CLOUD_PROJECT and AGENT_RUNTIME_ID."
            }

    # Initialize session state if missing
    if client_sid not in session_store:
        session_store[client_sid] = {
            "gcp_session_id": None,
            "current_interrupt_id": None,
            "current_flow": None,
            "recommend_results": None,
        }

    session_data = session_store[client_sid]
    current_flow = session_data.get("current_flow")

    # If the Reasoning Engine is waiting for user input (active interrupt),
    # bypass recommendation classification/intercept and forward it directly.
    if session_data.get("current_interrupt_id"):
        if USE_LOCAL_AGENT:
            return await forward_to_local_agent(user_message, session_data, client_sid)
        else:
            return await forward_to_reasoning_engine(
                user_message, session_data, client_sid
            )

    # --- CUSTOM RECIPE-RECOMMEND INTERCEPT LOGIC ---

    # 1. Flow: Waiting for fuzzy selection confirmation
    if current_flow == "recommend_confirming":
        matches = session_data.get("recommend_results", [])
        titles = [r["title"] for r in matches]

        resolution = await resolve_recipe_selection(user_message, titles)

        if resolution.is_cancelled:
            session_data["current_flow"] = None
            session_data["recommend_results"] = None
            return {
                "response": "Cancelled search. Let me know what else I can do for you!"
            }

        if resolution.matched_title:
            matched_recipe = next(
                (r for r in matches if r["title"] == resolution.matched_title), None
            )
            if matched_recipe:
                session_data["current_flow"] = None
                session_data["recommend_results"] = None
                return {"response": format_recipe_details(matched_recipe)}

        titles_str = "\n".join([f"- {t}" for t in titles])
        return {
            "response": f"I couldn't recognize '{user_message}' in the list. Please choose one of the following recipes:\n{titles_str}\n\n(Or say 'no' to cancel)"
        }

    # 2. Standard Flow (No active custom flow)
    # Check if the user is asking for a recommendation
    classification = await classify_intent(user_message)
    if classification.intent == "recommend":
        query = classification.search_query or user_message
        return await handle_recommendation_search(query, session_data)

    # 3. Delegate to Remote Reasoning Engine or Local Agent (for save-recipe & general chat)
    if USE_LOCAL_AGENT:
        return await forward_to_local_agent(user_message, session_data, client_sid)
    else:
        return await forward_to_reasoning_engine(user_message, session_data, client_sid)


# Search handler using semantic matching
async def handle_recommendation_search(
    query: str, session_data: dict[str, Any]
) -> dict[str, Any]:
    logger.info(f"Running semantic search for query: {query}")
    matches = await semantic_recipe_search(query)

    # Case 1: 0 Matches found -> Simple response, no state transition, allow fresh start
    if not matches:
        session_data["current_flow"] = None
        session_data["recommend_results"] = None
        return {
            "response": f"I couldn't find any recipe matching '{query}' in the cookbook. What would you like to search or do next?"
        }

    # Case 2: Exactly 1 Match found -> Show details directly
    elif len(matches) == 1:
        session_data["current_flow"] = None
        session_data["recommend_results"] = None
        single_recipe = matches[0]
        return {"response": format_recipe_details(single_recipe)}

    # Case 3: Multiple Matches found -> List and wait for selection
    else:
        session_data["current_flow"] = "recommend_confirming"
        session_data["recommend_results"] = matches
        titles = [r["title"] for r in matches]
        titles_str = "\n".join([f"- {t}" for t in titles])
        return {
            "response": f"I found the following matching recipes:\n{titles_str}\n\nWhich recipe would you like details for?"
        }


# Forwarder to Local Agent Runner
async def forward_to_local_agent(
    message: str, session_data: dict[str, Any], client_sid: str
) -> dict[str, Any]:

    from app.agent_runtime_app import agent_runtime

    if not session_data.get("gcp_session_id"):
        try:
            logger.info("Creating new local agent session")
            res = await agent_runtime.async_create_session(
                user_id="manager_dashboard_user"
            )
            gcp_sid = res["id"]
            session_data["gcp_session_id"] = gcp_sid
            logger.info(f"Created local session: {gcp_sid}")
        except Exception as e:
            logger.exception("Failed to create local agent session")
            return {"error": f"Failed to create local session: {e}"}

    gcp_sid = session_data["gcp_session_id"]
    active_interrupt_id = session_data["current_interrupt_id"]

    # Wrap as function response if resuming an active interrupt
    if active_interrupt_id:
        logger.info(
            f"Resuming local agent interrupt {active_interrupt_id} with message: {message}"
        )
        message_payload = {
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "name": "adk_request_input",
                        "id": active_interrupt_id,
                        "response": {"result": message},
                    }
                }
            ],
        }
        session_data["current_interrupt_id"] = None
    else:
        logger.info(f"Sending standard message to local agent: {message}")
        message_payload = {"role": "user", "parts": [{"text": message}]}

    try:
        final_text_parts = []
        new_interrupt_id = None

        # Call async_stream_query
        async for event in agent_runtime.async_stream_query(
            message=message_payload,
            user_id="manager_dashboard_user",
            session_id=gcp_sid,
        ):
            # Extract text
            content = event.get("content", {})
            parts = content.get("parts", [])
            for part in parts:
                if "text" in part:
                    final_text_parts.append(part["text"])

            # Check for interruptions
            actions = event.get("actions", {})
            state_delta = actions.get("state_delta", {})
            if (
                state_delta
                and "current_interrupt_id" in state_delta
                and state_delta["current_interrupt_id"]
            ):
                new_interrupt_id = state_delta["current_interrupt_id"]
            elif event.get("long_running_tool_ids"):
                new_interrupt_id = event["long_running_tool_ids"][0]

        if new_interrupt_id:
            logger.info(f"New local interruption detected: {new_interrupt_id}")
            session_data["current_interrupt_id"] = new_interrupt_id

        final_response = "".join(final_text_parts)
        if not final_response:
            final_response = "I did not receive any text response. Let me know if you would like to search or save a recipe."

        return {"response": final_response, "current_interrupt_id": new_interrupt_id}

    except Exception as e:
        logger.exception("Error during local agent execution")
        return {"error": f"Error during local execution: {type(e).__name__} - {e}."}


# Forwarder to Reasoning Engine (ADK Agent)
async def forward_to_reasoning_engine(
    message: str, session_data: dict[str, Any], client_sid: str
) -> dict[str, Any]:
    if not session_data.get("gcp_session_id"):
        try:
            logger.info(f"Creating new GCP session for client session: {client_sid}")
            input_struct = struct_pb2.Struct()
            input_struct.update({"user_id": "manager_dashboard_user"})

            req = aip_beta.QueryReasoningEngineRequest(
                name=full_runtime_id, input=input_struct, class_method="create_session"
            )
            res = client.query_reasoning_engine(request=req)
            gcp_sid = res.output.get("id")

            if not gcp_sid:
                raise ValueError("Failed to retrieve session ID from GCP output")

            session_data["gcp_session_id"] = gcp_sid
            logger.info(f"Mapped client session {client_sid} to GCP session {gcp_sid}")
        except Exception as e:
            logger.exception("Failed to initialize session on GCP")
            return {
                "error": f"Failed to initialize GCP session: {type(e).__name__} - {e}. "
                "Please verify your Google Cloud credentials and API configuration."
            }

    gcp_sid = session_data["gcp_session_id"]
    active_interrupt_id = session_data["current_interrupt_id"]

    # Wrap as function response if resuming an active interrupt
    if active_interrupt_id:
        logger.info(f"Resuming interrupt {active_interrupt_id} with message: {message}")
        message_payload = {
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "name": "adk_request_input",
                        "id": active_interrupt_id,
                        "response": {"result": message},
                    }
                }
            ],
        }
        session_data["current_interrupt_id"] = None
    else:
        logger.info(f"Sending standard message: {message}")
        message_payload = {"role": "user", "parts": [{"text": message}]}

    input_dict = {
        "message": message_payload,
        "user_id": "manager_dashboard_user",
        "session_id": gcp_sid,
    }
    input_struct = struct_pb2.Struct()
    input_struct.update(input_dict)

    try:
        req = aip_beta.StreamQueryReasoningEngineRequest(
            name=full_runtime_id, input=input_struct
        )

        response_stream = client.stream_query_reasoning_engine(request=req)
        final_text_parts = []
        new_interrupt_id = None

        for chunk in response_stream:
            data_bytes = chunk.data
            if not data_bytes:
                continue

            try:
                data_str = data_bytes.decode("utf-8")
                event = json.loads(data_str)

                # Extract text
                content = event.get("content", {})
                parts = content.get("parts", [])
                for part in parts:
                    if "text" in part:
                        final_text_parts.append(part["text"])

                # Check for interruptions
                actions = event.get("actions", {})
                state_delta = actions.get("state_delta", {})
                if (
                    state_delta
                    and "current_interrupt_id" in state_delta
                    and state_delta["current_interrupt_id"]
                ):
                    new_interrupt_id = state_delta["current_interrupt_id"]
                elif event.get("long_running_tool_ids"):
                    new_interrupt_id = event["long_running_tool_ids"][0]

            except Exception as parse_err:
                logger.warning(f"Error parsing chunk: {parse_err}")

        if new_interrupt_id:
            logger.info(f"New interruption detected: {new_interrupt_id}")
            session_data["current_interrupt_id"] = new_interrupt_id

        final_response = "".join(final_text_parts)
        if not final_response:
            final_response = "I did not receive any text response. Let me know if you would like to search or save a recipe."

        return {"response": final_response, "current_interrupt_id": new_interrupt_id}

    except Exception as e:
        logger.exception("Error during Reasoning Engine stream execution")
        return {
            "error": f"Error during query execution: {type(e).__name__} - {e}. "
            "Please make sure your Reasoning Engine is deployed and your credentials are correct."
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
