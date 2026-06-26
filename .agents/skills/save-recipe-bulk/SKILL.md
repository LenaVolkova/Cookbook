---
name: save-recipe-bulk
description: >
  Skill for saving a whole recipe in bulk to a Google Sheet.
  Triggered when the user wants to specify or paste a whole recipe at once.
---

# Save Recipe Bulk Skill

This skill allows the agent to take a full recipe provided by the user in bulk, automatically parse it into specific components (Title, Ingredients, Steps, Category), derive any missing components, let the user verify and correct the parsed fields, and finally save it to the Google Sheet.

## Behavior
1. **Trigger**: Detect if the user wants to specify/paste a whole recipe at once, or derive this preference from the dialogue.
2. **Bulk Input**: If the user has not already provided the recipe text, prompt them to paste/enter it.
3. **Parsing & Derivation**: Use Gemini to divide the text into Title, Ingredients, Steps, and Category.
   - If Title is missing, derive it from ingredients/steps.
   - If Ingredients are missing, derive them from steps/title.
   - If Category is missing, derive it.
   - If Steps are missing, generate them.
4. **Correction Loop**: Show the parsed details to the user and ask if they are correct.
   - If the user provides corrections, apply them dynamically using LLM and show the updated details.
   - Repeat until the user approves.
5. **Storage**: Save the approved recipe to the Google Sheet.
6. **Completion**: Notify the user.
