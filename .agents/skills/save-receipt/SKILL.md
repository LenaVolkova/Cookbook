---
name: save-receipt
description: >
  Skill for saving receipts/recipes step-by-step to a Google Sheet.
  Triggered when the user mentions having, finding, or wanting to save a receipt or recipe.
---

# Save Receipt Skill

This skill allows the agent to interactively collect recipe details (Title, Ingredients, Steps, Category) from the user and save them as a new row in the configured Google Sheet.

## Behavior
1. **Trigger**: Detect if the user says they found, have, or want to save a receipt or recipe.
2. **Interactive Collection**: Ask step-by-step for:
   - **Title**: If a recipe with the same title already exists in the Google Sheet, ask the user for a new title.
   - **Ingredients**: Ask for the ingredients.
   - **Steps**: Ask for the instructions or steps.
   - **Category**: Ask for the category (e.g. Dessert, Main Course).
3. **Storage**: Save the collected information to the Google Sheet under the appropriate columns (Title, Ingredients, Steps, Category).
4. **Completion**: Notify the user of successful storage.
