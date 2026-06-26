# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
from zoneinfo import ZoneInfo
import os
import uuid
from pydantic import BaseModel

import google.auth
from google.auth import default
import gspread

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.models import Gemini
from google.adk.workflow import Workflow, node, START, Edge
from google.genai import types

# GCP Environment variables
_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

SPREADSHEET_ID = "1WSfQTmJR9PZ6s3qHDecLGNyebQC5PpYlw5Erm7_s3ps"


class CookBookState(BaseModel):
    title: str | None = None
    ingredients: str | None = None
    steps: str | None = None
    category: str | None = None
    bulk_text: str | None = None
    flow_state: str | None = (
        None  # None, 'getting_title', 'getting_ingredients', 'getting_steps', 'getting_category', 'recommend_searching', 'recommend_confirming', 'recommend_retry', 'recommend_waiting_query'
    )
    current_interrupt_id: str | None = None
    recommend_query: str | None = None
    recommend_results: list[dict] | None = None


def get_worksheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "service-account.json",
    )
    if os.path.exists(json_path):
        gc = gspread.service_account(filename=json_path)
    else:
        credentials, _ = default(scopes=scopes)
        gc = gspread.Client(auth=credentials)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.get_worksheet(0)


def check_title_exists(title: str) -> bool:
    """Checks if a recipe with the same title already exists in the Google Sheet."""
    try:
        worksheet = get_worksheet()
        # Check first column (Title) values
        col1 = worksheet.col_values(1)
        for val in col1:
            if val.strip().lower() == title.strip().lower():
                return True
        return False
    except Exception as e:
        print(f"Error checking title: {type(e).__name__} - {e}")
        return False


def derive_category_with_llm(title: str, ingredients: str, steps: str) -> str:
    """Uses Gemini to derive recipe categories based on title, ingredients, and steps."""
    try:
        model_instance = Gemini(model="gemini-flash-latest")
        client = model_instance.api_client
        prompt = f"""
        Analyze the following recipe and determine the most appropriate categories (e.g. Dessert, Main Course, Soup, Salad, Snack, Breakfast, Vegetarian, etc.).
        You can return multiple categories if applicable, separated by a comma (e.g., "Dessert, Snack").
        
        Recipe Title: {title}
        Ingredients:
        {ingredients}
        
        Steps:
        {steps}
        
        Return ONLY the comma-separated categories, nothing else.
        """
        response = client.models.generate_content(
            model="gemini-flash-latest", contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"Error deriving category: {e}")
        return "Uncategorized"


def check_daily_limit_reached() -> bool:
    """Checks if 50 or more recipes have been added to the sheet in the last 24 hours."""
    try:
        worksheet = get_worksheet()
        all_records = worksheet.get_all_records()
        if not all_records:
            return False

        now = datetime.datetime.now(ZoneInfo("UTC"))
        one_day_ago = now - datetime.timedelta(hours=24)

        count = 0
        for r in all_records:
            ts_str = r.get("Timestamp", r.get("timestamp", ""))
            if ts_str:
                try:
                    ts = datetime.datetime.fromisoformat(ts_str)
                    if ts > one_day_ago:
                        count += 1
                except ValueError:
                    pass
        return count >= 50
    except Exception as e:
        print(f"Error checking daily limit: {e}")
        return False


def save_recipe_to_sheet(
    title: str, ingredients: str, steps: str, category: str
) -> str:
    """Appends a new recipe/receipt row to the Google Sheet."""
    try:
        if check_daily_limit_reached():
            return "Error: The daily limit of 50 new recipes has been reached. Please try again tomorrow."

        category_clean = category.strip().lower() if category else ""
        if not category_clean or category_clean in [
            "skip",
            "none",
            "no category",
            "null",
            "undefined",
            "unknown",
            "any",
        ]:
            category = derive_category_with_llm(title, ingredients, steps)

        worksheet = get_worksheet()
        # Add headers if sheet is empty
        try:
            headers = worksheet.row_values(1)
        except Exception:
            headers = []

        headers_lower = [h.strip().lower() for h in headers if h]
        if not headers_lower or "title" not in headers_lower:
            worksheet.append_row(
                ["Title", "Ingredients", "Steps", "Category", "Timestamp"]
            )

        timestamp = datetime.datetime.now(ZoneInfo("UTC")).isoformat()
        worksheet.append_row([title, ingredients, steps, category, timestamp])
        return "Recipe saved successfully!"
    except Exception as e:
        return f"Error saving recipe: {type(e).__name__} - {str(e) or 'Permission/Scope issue (check your Google login scopes)'}"


def search_recipes_in_sheet(query: str) -> list[dict]:
    """Search for recipes where query matches title, ingredients, steps, or category."""
    try:
        worksheet = get_worksheet()
        all_records = worksheet.get_all_records()
        q = query.strip().lower()
        if not q:
            return []
        results = []
        for r in all_records:
            norm_r = {k.lower(): str(v) for k, v in r.items()}
            title = norm_r.get("title", "")
            ingredients = norm_r.get("ingredients", "")
            category = norm_r.get("category", "")
            steps = norm_r.get("steps", "")

            if (
                (q in title.lower())
                or (q in ingredients.lower())
                or (q in category.lower())
                or (q in steps.lower())
            ):
                results.append(
                    {
                        "title": r.get("Title", r.get("title", "")),
                        "ingredients": r.get("Ingredients", r.get("ingredients", "")),
                        "steps": r.get("Steps", r.get("steps", "")),
                        "category": r.get("Category", r.get("category", "")),
                    }
                )
        return results
    except Exception as e:
        print(f"Error searching recipes: {type(e).__name__} - {e}")
        return []


# --- Intent Classification Schema ---
class IntentClassification(BaseModel):
    intent: str  # "save", "recommend", or "fallback"
    search_query: str | None = None  # extracted keywords if intent is "recommend"


async def classify_and_extract_intent(user_message: str) -> IntentClassification:
    model_instance = Gemini(model="gemini-flash-latest")
    client = model_instance.api_client

    prompt = f"""
    Analyze the user's message and classify their intent:
    1. "save": The user wants to save or store a new recipe or receipt.
    2. "recommend": The user is asking for recipe recommendations or what to cook (e.g., "what to cook for dinner", "recipes from banana", "recommend something").
    3. "fallback": Any other general conversation, cooking questions, or greetings.
    
    For "recommend" intent, also extract the key-words representing ingredients or the type of meal (e.g., "banana", "dinner", "chicken").
    
    User Message: "{user_message}"
    """

    response = await client.aio.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=IntentClassification,
            temperature=0.0,
        ),
    )
    import json

    data = json.loads(response.text)
    return IntentClassification(**data)


# --- Graph Nodes ---


def check_is_whole_recipe(text: str) -> bool:
    text_lower = text.lower()

    # Heuristics for ingredients
    has_ingredients_word = "ingredient" in text_lower
    # common ingredient units/terms
    ingredient_terms = [
        "tbsp",
        "tsp",
        "cup",
        "g ",
        "oz",
        "lb",
        "ml",
        "spoon",
        "clove",
        "pinch",
        "salt",
        "pepper",
        "oil",
        "water",
        "chopped",
        "sliced",
        "diced",
    ]
    has_ingredient_terms = (
        sum(1 for term in ingredient_terms if term in text_lower) >= 2
    )

    # Heuristics for instructions
    has_instructions_word = any(
        w in text_lower
        for w in ["instruction", "step", "direction", "method", "preparation", "prep"]
    )
    # common cooking verbs
    cooking_verbs = [
        "cook",
        "bake",
        "heat",
        "boil",
        "fry",
        "stir",
        "simmer",
        "mix",
        "blend",
        "serve",
        "sauté",
        "pour",
        "remove",
        "add ",
        "place ",
    ]
    has_cooking_verbs = sum(1 for verb in cooking_verbs if verb in text_lower) >= 2

    # If the text is very long and has ingredients and steps indicators, it is a whole recipe
    if len(text) > 150:
        if (has_ingredients_word or has_ingredient_terms) and (
            has_instructions_word or has_cooking_verbs
        ):
            return True

    return False


def determine_save_mode_deterministically(message: str) -> str | None:
    msg = message.strip().lower().replace("-", " ").replace("_", " ")
    # remove common punctuation
    for char in [".", ",", "!", "?", "'", '"']:
        msg = msg.replace(char, "")

    # Generic save requests -> unknown (should ask user to choose mode)
    generic_phrases = {
        "save a recipe",
        "i want to save a recipe",
        "save recipe",
        "add a recipe",
        "add recipe",
        "create a recipe",
        "create recipe",
        "new recipe",
        "store a recipe",
        "store recipe",
        "save",
        "add",
        "create",
    }
    if msg in generic_phrases:
        return "unknown"

    # Explicit step-by-step requests
    step_phrases = {
        "step by step",
        "interactively",
        "one detail at a time",
        "one by one",
        "step-by-step",
        "interactive",
        "steps",
    }
    if any(phrase in msg for phrase in step_phrases):
        return "step-by-step"

    # Explicit bulk requests
    bulk_phrases = {
        "bulk",
        "all at once",
        "whole recipe in one message",
        "whole recipe",
        "in bulk",
        "paste the whole recipe",
        "paste recipe",
        "one message",
    }
    if any(phrase in msg for phrase in bulk_phrases):
        return "bulk"

    return None


class SaveModeDetection(BaseModel):
    mode: str  # "step-by-step", "bulk", or "unknown"
    recipe_text: str | None = None  # extracted recipe text if present


async def detect_save_mode(user_message: str) -> SaveModeDetection:
    model_instance = Gemini(model="gemini-flash-latest")
    client = model_instance.api_client

    prompt = f"""
    Analyze the user's message to determine how they want to save their recipe:
    1. "step-by-step": The user explicitly requests to save the recipe step-by-step (e.g., "step-by-step", "interactively", "one detail at a time").
    2. "bulk": The user explicitly requests to paste or enter the whole recipe at once (e.g., "bulk", "all at once", "whole recipe", "in bulk", "specify the whole recipe"), OR they have already pasted/provided the recipe text (ingredients, steps, etc.) in their message.
    3. "unknown": The user simply says they want to save a recipe (e.g., "I want to save a recipe", "add a recipe", "save this") but has NOT specified whether they want to do it step-by-step or in bulk, and has not provided the recipe details yet.
    
    If the user has already provided recipe details (like ingredients, a list of steps, or a full recipe text) in their message, you MUST classify the mode as "bulk" and extract the recipe text into the recipe_text field.
    
    User Message: "{user_message}"
    """

    response = await client.aio.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SaveModeDetection,
            temperature=0.0,
        ),
    )
    import json

    data = json.loads(response.text)
    return SaveModeDetection(**data)


class ParsedRecipe(BaseModel):
    title: str
    ingredients: str
    steps: str
    category: str


async def parse_bulk_recipe_text(recipe_text: str) -> ParsedRecipe:
    model_instance = Gemini(model="gemini-flash-latest")
    client = model_instance.api_client

    prompt = f"""
    You are an expert chef and assistant. Your job is to extract and derive the recipe details from the text provided.
    
    Instructions:
    1. Divide the recipe into: Title, Ingredients, Steps, and Category.
    2. If any of these fields are missing or not explicitly stated in the input text, you MUST derive or generate them based on the other parts of the recipe:
       - If Title is missing, generate a creative and accurate title based on the ingredients and steps.
       - If Ingredients are missing, analyze the steps/title and list the required ingredients.
       - If Category is missing, determine the most appropriate category (e.g., Dessert, Main Course, Soup, Salad, Snack, Breakfast, Vegetarian, etc.).
       - If Steps are missing, generate clear, logical step-by-step instructions on how to cook/prepare the recipe based on the title and ingredients.
       
    Input Recipe Text:
    {recipe_text}
    """

    response = await client.aio.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ParsedRecipe,
            temperature=0.0,
        ),
    )
    import json

    data = json.loads(response.text)
    return ParsedRecipe(**data)


async def apply_recipe_corrections(
    current: ParsedRecipe, correction_message: str
) -> ParsedRecipe:
    model_instance = Gemini(model="gemini-flash-latest")
    client = model_instance.api_client

    prompt = f"""
    The user wants to make corrections to a recipe that was previously parsed.
    
    Current Recipe Details:
    - Title: {current.title}
    - Ingredients: {current.ingredients}
    - Steps: {current.steps}
    - Category: {current.category}
    
    User's Correction/Feedback:
    "{correction_message}"
    
    Apply the requested changes. Keep everything else exactly the same unless the user explicitly requested a change or it's logically implied.
    """

    response = await client.aio.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ParsedRecipe,
            temperature=0.0,
        ),
    )
    import json

    data = json.loads(response.text)
    return ParsedRecipe(**data)


def is_approval(message: str) -> bool:
    msg = message.strip().lower()
    return msg in [
        "yes",
        "y",
        "sure",
        "ok",
        "yeah",
        "looks good",
        "correct",
        "save",
        "save it",
        "perfect",
        "good",
    ]


def is_cancellation(message: str) -> bool:
    msg = message.strip().lower()
    return msg in ["cancel", "stop", "exit", "quit"]


@node
async def recipe_router(ctx: Context, node_input: types.Content) -> Event:
    """Determines whether the user wants to initiate the recipe saving flow or recommendation flow."""
    user_message = ""
    if node_input and node_input.parts:
        user_message = " ".join([p.text for p in node_input.parts if p.text])

    # 1. Prioritize whole-recipe detection. If the message is a whole recipe,
    # immediately trigger the bulk parsing flow, bypassing any active flow states.
    if check_is_whole_recipe(user_message):
        return Event(
            output=user_message,
            route="bulk_parse",
            state={
                "flow_state": "confirming_bulk_recipe",
                "bulk_text": user_message,
                "title": None,
                "ingredients": None,
                "steps": None,
                "category": None,
                "current_interrupt_id": None,
                "recommend_query": None,
                "recommend_results": None,
            },
        )

    # 2. If we are already in progress of a flow, route to that node
    flow_state = ctx.state.get("flow_state")
    if flow_state:
        if flow_state.startswith("recommend_"):
            return Event(output=user_message, route="recommend")
        elif flow_state == "getting_save_mode":
            return Event(output=user_message, route="save_mode_select")
        elif flow_state == "getting_bulk_recipe":
            return Event(output=user_message, route="bulk_collect")
        elif flow_state == "confirming_bulk_recipe":
            return Event(output=user_message, route="bulk_parse")
        else:
            return Event(output=user_message, route="collect")

    # 3. If no flow is active, classify the user message using LLM
    try:
        classification = await classify_and_extract_intent(user_message)
        intent = classification.intent
        search_query = classification.search_query
    except Exception as e:
        print(f"Error classifying intent: {e}")
        intent = "fallback"
        search_query = None

    if intent == "save":
        # First use deterministic checks for save mode
        mode = determine_save_mode_deterministically(user_message)
        recipe_text = None

        if mode is None:
            # Fall back to LLM mode detection
            detection = await detect_save_mode(user_message)
            mode = detection.mode
            recipe_text = detection.recipe_text
        else:
            if mode == "bulk" and check_is_whole_recipe(user_message):
                recipe_text = user_message

        if mode == "bulk":
            if recipe_text and recipe_text.strip():
                return Event(
                    output=recipe_text,
                    route="bulk_parse",
                    state={
                        "flow_state": "confirming_bulk_recipe",
                        "bulk_text": recipe_text,
                        "title": None,
                        "ingredients": None,
                        "steps": None,
                        "category": None,
                        "current_interrupt_id": None,
                        "recommend_query": None,
                        "recommend_results": None,
                    },
                )
            else:
                return Event(
                    output="",
                    route="bulk_collect",
                    state={
                        "flow_state": "getting_bulk_recipe",
                        "bulk_text": None,
                        "title": None,
                        "ingredients": None,
                        "steps": None,
                        "category": None,
                        "current_interrupt_id": None,
                        "recommend_query": None,
                        "recommend_results": None,
                    },
                )
        elif mode == "step-by-step":
            return Event(
                output=user_message,
                route="collect",
                state={
                    "flow_state": "getting_title",
                    "title": None,
                    "ingredients": None,
                    "steps": None,
                    "category": None,
                    "current_interrupt_id": None,
                    "recommend_query": None,
                    "recommend_results": None,
                },
            )
        else:  # "unknown"
            return Event(
                output=user_message,
                route="save_mode_select",
                state={
                    "flow_state": "getting_save_mode",
                    "title": None,
                    "ingredients": None,
                    "steps": None,
                    "category": None,
                    "current_interrupt_id": None,
                    "recommend_query": None,
                    "recommend_results": None,
                },
            )
    elif intent == "recommend":
        return Event(
            output=user_message,
            route="recommend",
            state={
                "flow_state": "recommend_searching",
                "recommend_query": search_query or user_message,
                "recommend_results": None,
                "current_interrupt_id": None,
                "title": None,
                "ingredients": None,
                "steps": None,
                "category": None,
                "bulk_text": None,
            },
        )
    else:
        return Event(output=user_message, route="fallback")


@node(rerun_on_resume=True)
async def determine_save_mode(ctx: Context, node_input: str | None = None) -> Event:
    current_id = ctx.state.get("current_interrupt_id")
    resume_val = (
        ctx.resume_inputs.get(current_id) if current_id and ctx.resume_inputs else None
    )

    if not resume_val:
        new_id = f"mode_{uuid.uuid4().hex[:4]}"
        yield Event(
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text="Would you like to save this recipe step-by-step, or paste the whole recipe in one message?"
                    )
                ],
            ),
            state={"current_interrupt_id": new_id},
        )
        yield RequestInput(
            interrupt_id=new_id,
            message="Would you like to save step-by-step or paste the whole recipe in one message?",
        )
        return

    # User replied, analyze the response
    user_choice = resume_val.strip()

    # 1. Deterministic check
    mode = determine_save_mode_deterministically(user_choice)
    recipe_text = None

    if mode is None:
        # 2. LLM fallback check
        detection = await detect_save_mode(user_choice)
        mode = detection.mode
        recipe_text = detection.recipe_text
    else:
        if mode == "bulk" and check_is_whole_recipe(user_choice):
            recipe_text = user_choice

    if mode == "bulk":
        if recipe_text and recipe_text.strip():
            yield Event(
                output=recipe_text,
                route="bulk_parse",
                state={
                    "flow_state": "confirming_bulk_recipe",
                    "bulk_text": recipe_text,
                    "current_interrupt_id": None,
                },
            )
        else:
            yield Event(
                output="",
                route="bulk_collect",
                state={
                    "flow_state": "getting_bulk_recipe",
                    "bulk_text": None,
                    "current_interrupt_id": None,
                },
            )
    elif mode == "step-by-step":
        yield Event(
            output="",
            route="collect",
            state={
                "flow_state": "getting_title",
                "current_interrupt_id": None,
            },
        )
    else:
        # Still unclear, ask again
        new_id = f"mode_{uuid.uuid4().hex[:4]}"
        yield Event(
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text="I didn't quite catch that. Would you like to save it step-by-step, or paste the whole recipe in one message?"
                    )
                ],
            ),
            state={"current_interrupt_id": new_id},
        )
        yield RequestInput(
            interrupt_id=new_id,
            message="Please answer: step-by-step or paste the whole recipe?",
        )


@node(rerun_on_resume=True)
async def collect_bulk_recipe(ctx: Context, node_input: str | None = None) -> Event:
    current_id = ctx.state.get("current_interrupt_id")
    resume_val = (
        ctx.resume_inputs.get(current_id) if current_id and ctx.resume_inputs else None
    )

    if not resume_val:
        new_id = f"bulk_recipe_{uuid.uuid4().hex[:4]}"
        yield Event(
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text="Please paste or type the whole recipe here (including ingredients, instructions, etc.):"
                    )
                ],
            ),
            state={"current_interrupt_id": new_id},
        )
        yield RequestInput(
            interrupt_id=new_id, message="Please enter the recipe in bulk:"
        )
        return

    # User provided the recipe text
    recipe_text = resume_val.strip()
    yield Event(
        output=recipe_text,
        route="bulk_parse",
        state={
            "flow_state": "confirming_bulk_recipe",
            "bulk_text": recipe_text,
            "current_interrupt_id": None,
        },
    )


@node(rerun_on_resume=True)
async def parse_and_confirm_bulk_recipe(
    ctx: Context, node_input: str | None = None
) -> Event:
    title = ctx.state.get("title")
    ingredients = ctx.state.get("ingredients")
    steps = ctx.state.get("steps")
    category = ctx.state.get("category")
    bulk_text = ctx.state.get("bulk_text") or node_input

    current_id = ctx.state.get("current_interrupt_id")
    resume_val = (
        ctx.resume_inputs.get(current_id) if current_id and ctx.resume_inputs else None
    )

    # If we haven't parsed the recipe yet, do it now
    if not (title or ingredients or steps or category):
        try:
            parsed = await parse_bulk_recipe_text(bulk_text)
            title = parsed.title
            ingredients = parsed.ingredients
            steps = parsed.steps
            category = parsed.category

            # Check if title already exists in the sheet
            if check_title_exists(title):
                title = f"{title} (New)"
        except Exception as e:
            title = "Imported Recipe"
            ingredients = bulk_text
            steps = "Please review steps."
            category = "Uncategorized"

        yield Event(
            state={
                "title": title,
                "ingredients": ingredients,
                "steps": steps,
                "category": category,
                "bulk_text": bulk_text,
            }
        )

    # Display current parsed recipe and ask for approval/corrections
    if not resume_val:
        new_id = f"confirm_{uuid.uuid4().hex[:4]}"
        msg = (
            f"I've parsed the recipe details. Please review them:\n\n"
            f"**Title**: {title}\n"
            f"**Category**: {category}\n\n"
            f"**Ingredients**:\n{ingredients}\n\n"
            f"**Instructions/Steps**:\n{steps}\n\n"
            f"Does this look correct? You can say **Yes** to save, or specify any corrections you'd like to make (e.g. 'Change title to X', 'Add Y to ingredients')."
        )
        yield Event(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=msg)],
            ),
            state={"current_interrupt_id": new_id},
        )
        yield RequestInput(
            interrupt_id=new_id,
            message="Does this look correct? (Yes/No or list corrections)",
        )
        return

    # We got feedback from the user
    feedback = resume_val.strip()

    if is_approval(feedback):
        yield Event(
            output={
                "title": title,
                "ingredients": ingredients,
                "steps": steps,
                "category": category,
            },
            route="finish",
            state={"current_interrupt_id": None},
        )
        return
    elif is_cancellation(feedback):
        yield Event(
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text="Save cancelled. Let me know if you want to do anything else!"
                    )
                ],
            ),
            state={
                "flow_state": None,
                "bulk_text": None,
                "title": None,
                "ingredients": None,
                "steps": None,
                "category": None,
                "current_interrupt_id": None,
            },
        )
        return
    else:
        # Apply corrections
        current = ParsedRecipe(
            title=title, ingredients=ingredients, steps=steps, category=category
        )
        try:
            updated = await apply_recipe_corrections(current, feedback)
            title = updated.title
            ingredients = updated.ingredients
            steps = updated.steps
            category = updated.category
        except Exception as e:
            yield Event(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text="Sorry, I had trouble updating the recipe based on your feedback. Let's try again."
                        )
                    ],
                )
            )

        # Clear resume_val and show updated values
        new_id = f"confirm_{uuid.uuid4().hex[:4]}"
        msg = (
            f"Here are the updated recipe details. Please review:\n\n"
            f"**Title**: {title}\n"
            f"**Category**: {category}\n\n"
            f"**Ingredients**:\n{ingredients}\n\n"
            f"**Instructions/Steps**:\n{steps}\n\n"
            f"Does this look correct now? You can say **Yes** to save, or specify further corrections."
        )
        yield Event(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=msg)],
            ),
            state={
                "title": title,
                "ingredients": ingredients,
                "steps": steps,
                "category": category,
                "current_interrupt_id": new_id,
            },
        )
        yield RequestInput(
            interrupt_id=new_id,
            message="Does this look correct now? (Yes/No or list corrections)",
        )


tutorial_agent = LlmAgent(
    name="tutorial_agent",
    model="gemini-flash-latest",
    instruction=(
        "You are a helpful cookbook assistant. Since the user's request does not match any other roles (saving a recipe or recommending a recipe), "
        "you must explain your capabilities to the user by telling them exactly: "
        '"I can save a recipe step-by-step, or you can paste your recipe in bulk and I will divide it into title, ingredients, steps, and category. '
        "I can recommend a recipe if you ask me to find something that can be cooked with a particular ingredient, or if you provide a type of meal like waffles, Japanese cuisine, breakfast, etc. "
        'Please note the following constraints: there is a rate limit of 5 requests per minute from the same IP address; inputs must be simple text (no code or files); and lengths are limited to 100 characters for Title/Categories, 200 characters for Ingredients, and 1000 characters for Steps. Also, only 50 new recipes can be added to the cookbook in any 24-hour period."'
    ),
)


@node(rerun_on_resume=True)
async def collect_recipe_details(ctx: Context, node_input: str | None = None) -> Event:
    """Step-by-step collector for Title, Ingredients, Steps, and Category."""
    flow_state = ctx.state.get("flow_state")

    title = ctx.state.get("title")
    ingredients = ctx.state.get("ingredients")
    steps = ctx.state.get("steps")
    category = ctx.state.get("category")

    current_id = ctx.state.get("current_interrupt_id")
    resume_val = (
        ctx.resume_inputs.get(current_id) if current_id and ctx.resume_inputs else None
    )

    # 1. Collect and validate Title
    if not title:
        if current_id and current_id.startswith("title_") and resume_val:
            title_from_user = resume_val.strip()
            if check_title_exists(title_from_user):
                new_id = f"title_{uuid.uuid4().hex[:4]}"
                yield Event(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(
                                text=f"A recipe with the title '{title_from_user}' already exists. Please choose a different title."
                            )
                        ],
                    ),
                    state={"current_interrupt_id": new_id},
                )
                yield RequestInput(
                    interrupt_id=new_id, message="Please choose a different title:"
                )
                return
            else:
                title = title_from_user
                yield Event(
                    state={"title": title, "current_interrupt_id": None},
                )
                # Fall through to collect ingredients
        else:
            new_id = f"title_{uuid.uuid4().hex[:4]}"
            yield Event(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text="Let's save your recipe. What is the title of the recipe?"
                        )
                    ],
                ),
                state={"current_interrupt_id": new_id},
            )
            yield RequestInput(
                interrupt_id=new_id, message="What is the title of the recipe?"
            )
            return

    # 2. Collect Ingredients
    if not ingredients:
        if current_id and current_id.startswith("ing_") and resume_val:
            ingredients = resume_val.strip()
            yield Event(
                state={"ingredients": ingredients, "current_interrupt_id": None},
            )
            # Fall through to collect steps
        else:
            new_id = f"ing_{uuid.uuid4().hex[:4]}"
            yield Event(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=f"Title: '{title}'. What are the ingredients?"
                        )
                    ],
                ),
                state={"current_interrupt_id": new_id},
            )
            yield RequestInput(interrupt_id=new_id, message="What are the ingredients?")
            return

    # 3. Collect Steps
    if not steps:
        if current_id and current_id.startswith("steps_") and resume_val:
            steps = resume_val.strip()
            yield Event(state={"steps": steps, "current_interrupt_id": None})
            # Fall through to collect category
        else:
            new_id = f"steps_{uuid.uuid4().hex[:4]}"
            yield Event(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text="Ingredients recorded. What are the instructions/steps?"
                        )
                    ],
                ),
                state={"current_interrupt_id": new_id},
            )
            yield RequestInput(interrupt_id=new_id, message="What are the steps?")
            return

    # 4. Collect Category
    if not category:
        if current_id and current_id.startswith("cat_") and resume_val:
            category = resume_val.strip()
            yield Event(
                state={"category": category, "current_interrupt_id": None},
            )
            # Fall through to finish
        else:
            new_id = f"cat_{uuid.uuid4().hex[:4]}"
            yield Event(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text="Steps recorded. What category does this recipe belong to (e.g. Dessert, Main Course)?"
                        )
                    ],
                ),
                state={"current_interrupt_id": new_id},
            )
            yield RequestInput(interrupt_id=new_id, message="What is the category?")
            return

    # 5. All data collected, route to finish node
    yield Event(
        output={
            "title": title,
            "ingredients": ingredients,
            "steps": steps,
            "category": category,
        },
        route="finish",
    )


@node
def save_and_finish(ctx: Context, node_input: dict) -> Event:
    """Saves the recipe to Google Sheet and resets the conversation workflow state."""
    title = node_input.get("title")
    ingredients = node_input.get("ingredients")
    steps = node_input.get("steps")
    category = node_input.get("category")

    result = save_recipe_to_sheet(title, ingredients, steps, category)

    if result.startswith("Error"):
        return Event(
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text=f"Sorry, I encountered an error while saving your recipe to the Google Sheet: {result}"
                    )
                ],
            ),
        )

    return Event(
        content=types.Content(
            role="model",
            parts=[
                types.Part.from_text(
                    text=f"Success! I've saved your recipe '{title}' to the Google Sheet under the category '{category}'."
                )
            ],
        ),
        state={
            "flow_state": None,
            "title": None,
            "ingredients": None,
            "steps": None,
            "category": None,
            "current_interrupt_id": None,
            "recommend_query": None,
            "recommend_results": None,
        },
    )


@node(rerun_on_resume=True)
async def recommend_recipes(ctx: Context, node_input: str | None = None) -> Event:
    """Handles searching recipes in the sheet and showing details of the selected recipe."""
    flow_state = ctx.state.get("flow_state")
    query = ctx.state.get("recommend_query")
    results = ctx.state.get("recommend_results")
    current_id = ctx.state.get("current_interrupt_id")

    resume_val = (
        ctx.resume_inputs.get(current_id) if current_id and ctx.resume_inputs else None
    )

    # 1. State: searching
    if flow_state == "recommend_searching":
        if not query:
            new_id = f"query_{uuid.uuid4().hex[:4]}"
            yield Event(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text="What ingredient or meal type would you like to search for?"
                        )
                    ],
                ),
                state={
                    "flow_state": "recommend_waiting_query",
                    "current_interrupt_id": new_id,
                },
            )
            yield RequestInput(
                interrupt_id=new_id, message="What would you like to search for?"
            )
            return

        found = search_recipes_in_sheet(query)
        if not found:
            new_id = f"retry_{uuid.uuid4().hex[:4]}"
            yield Event(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=f"I couldn't find any recipe that matches '{query}'. Would you like to search for another recipe? (Yes/No)"
                        )
                    ],
                ),
                state={"current_interrupt_id": new_id, "flow_state": "recommend_retry"},
            )
            yield RequestInput(
                interrupt_id=new_id,
                message="Would you like to search for another recipe? (Yes/No)",
            )
            return
        else:
            titles = [r["title"] for r in found]
            titles_str = "\n".join([f"- {t}" for t in titles])

            new_id = f"select_{uuid.uuid4().hex[:4]}"
            yield Event(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=f"I found the following matching recipes:\n{titles_str}\n\nWhich recipe would you like details for?"
                        )
                    ],
                ),
                state={
                    "recommend_results": found,
                    "current_interrupt_id": new_id,
                    "flow_state": "recommend_confirming",
                },
            )
            yield RequestInput(
                interrupt_id=new_id, message="Please choose a recipe to see details:"
            )
            return

    # 2. State: retry check
    if flow_state == "recommend_retry":
        if resume_val:
            val_lower = resume_val.strip().lower()
            if val_lower in ["yes", "y", "sure", "ok", "yeah"]:
                new_id = f"query_{uuid.uuid4().hex[:4]}"
                yield Event(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(
                                text="What ingredient or meal type would you like to search for?"
                            )
                        ],
                    ),
                    state={
                        "current_interrupt_id": new_id,
                        "flow_state": "recommend_waiting_query",
                    },
                )
                yield RequestInput(
                    interrupt_id=new_id, message="What would you like to search for?"
                )
                return
            else:
                yield Event(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(
                                text="Okay! Let me know if you want to do anything else."
                            )
                        ],
                    ),
                    state={
                        "flow_state": None,
                        "recommend_query": None,
                        "recommend_results": None,
                        "current_interrupt_id": None,
                    },
                )
                return

    # 3. State: waiting for new query input
    if flow_state == "recommend_waiting_query":
        if resume_val:
            new_query = resume_val.strip()
            yield Event(
                state={
                    "recommend_query": new_query,
                    "flow_state": "recommend_searching",
                    "current_interrupt_id": None,
                }
            )
            # Rerun the search
            found = search_recipes_in_sheet(new_query)
            if not found:
                new_id = f"retry_{uuid.uuid4().hex[:4]}"
                yield Event(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(
                                text=f"I couldn't find any recipe that matches '{new_query}'. Would you like to search for another recipe? (Yes/No)"
                            )
                        ],
                    ),
                    state={
                        "current_interrupt_id": new_id,
                        "flow_state": "recommend_retry",
                    },
                )
                yield RequestInput(
                    interrupt_id=new_id,
                    message="Would you like to search for another recipe? (Yes/No)",
                )
                return
            else:
                titles = [r["title"] for r in found]
                titles_str = "\n".join([f"- {t}" for t in titles])

                new_id = f"select_{uuid.uuid4().hex[:4]}"
                yield Event(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(
                                text=f"I found the following matching recipes:\n{titles_str}\n\nWhich recipe would you like details for?"
                            )
                        ],
                    ),
                    state={
                        "recommend_results": found,
                        "current_interrupt_id": new_id,
                        "flow_state": "recommend_confirming",
                    },
                )
                yield RequestInput(
                    interrupt_id=new_id,
                    message="Please choose a recipe to see details:",
                )
                return

    # 4. State: selection confirmation
    if flow_state == "recommend_confirming":
        if resume_val and results:
            selected_title = resume_val.strip().lower()

            matched_recipe = None
            for r in results:
                if r["title"].strip().lower() == selected_title:
                    matched_recipe = r
                    break

            if matched_recipe:
                recipe_details = (
                    f"Here are the details for **{matched_recipe['title']}**:\n\n"
                    f"**Category:** {matched_recipe['category']}\n\n"
                    f"**Ingredients:**\n{matched_recipe['ingredients']}\n\n"
                    f"**Instructions:**\n{matched_recipe['steps']}"
                )
                yield Event(
                    content=types.Content(
                        role="model", parts=[types.Part.from_text(text=recipe_details)]
                    ),
                    state={
                        "flow_state": None,
                        "recommend_query": None,
                        "recommend_results": None,
                        "current_interrupt_id": None,
                    },
                )
                return
            else:
                if selected_title in ["no", "stop", "exit", "cancel"]:
                    yield Event(
                        content=types.Content(
                            role="model",
                            parts=[types.Part.from_text(text="Cancelled search.")],
                        ),
                        state={
                            "flow_state": None,
                            "recommend_query": None,
                            "recommend_results": None,
                            "current_interrupt_id": None,
                        },
                    )
                    return

                titles = [r["title"] for r in results]
                titles_str = "\n".join([f"- {t}" for t in titles])

                new_id = f"select_{uuid.uuid4().hex[:4]}"
                yield Event(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(
                                text=f"I didn't find '{resume_val}' in the list. Please type one of the listed recipes:\n{titles_str}\n\n(Or say 'no' to cancel)"
                            )
                        ],
                    ),
                    state={"current_interrupt_id": new_id},
                )
                yield RequestInput(
                    interrupt_id=new_id,
                    message="Please choose a recipe to see details:",
                )
                return


# --- Workflow Graph Definition ---

root_agent = Workflow(
    name="cook_book_workflow",
    state_schema=CookBookState,
    edges=[
        (START, recipe_router),
        Edge(from_node=recipe_router, to_node=tutorial_agent, route="fallback"),
        Edge(from_node=recipe_router, to_node=collect_recipe_details, route="collect"),
        Edge(from_node=collect_recipe_details, to_node=save_and_finish, route="finish"),
        Edge(from_node=recipe_router, to_node=recommend_recipes, route="recommend"),
        Edge(
            from_node=recipe_router,
            to_node=determine_save_mode,
            route="save_mode_select",
        ),
        Edge(
            from_node=recipe_router, to_node=collect_bulk_recipe, route="bulk_collect"
        ),
        Edge(
            from_node=recipe_router,
            to_node=parse_and_confirm_bulk_recipe,
            route="bulk_parse",
        ),
        Edge(
            from_node=determine_save_mode,
            to_node=collect_bulk_recipe,
            route="bulk_collect",
        ),
        Edge(
            from_node=determine_save_mode,
            to_node=parse_and_confirm_bulk_recipe,
            route="bulk_parse",
        ),
        Edge(
            from_node=determine_save_mode,
            to_node=collect_recipe_details,
            route="collect",
        ),
        Edge(
            from_node=collect_bulk_recipe,
            to_node=parse_and_confirm_bulk_recipe,
            route="bulk_parse",
        ),
        Edge(
            from_node=parse_and_confirm_bulk_recipe,
            to_node=save_and_finish,
            route="finish",
        ),
    ],
    description="A cook book agent that can help save recipes step-by-step or recommend recipes from a Google Sheet.",
)

# App wrapping with Resumability Config enabled for Human-in-the-Loop inputs
app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True),
)
