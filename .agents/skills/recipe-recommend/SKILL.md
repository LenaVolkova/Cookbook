---
name: recipe-recommend
description: >
  Skill for recommending recipes based on ingredients or type of meal.
  Triggered when the user asks what they can cook (e.g. for dinner, from banana, etc.).
---

# Recipe Recommend Skill

This skill allows the agent to search for recipes in the Google Sheet based on user-provided ingredients or meal types, list matching titles, and show details (ingredients and steps) for a selected recipe.

## Behavior
1. **Trigger**: Detect if the user asks for cooking recommendations, recipes from specific ingredients (e.g., banana), or types of meals (e.g., dinner).
2. **Extraction**: Extract keywords representing ingredients or meal type from the query.
3. **Search**: Search category, ingredients, and title fields in the Google Sheet for matching records.
4. **Matching Results**:
   - If recipes are found: List the titles of matching recipes and ask the user if they want details for any of them.
   - If the user specifies a matching recipe, display its ingredients and steps.
   - If no recipe matches: Tell the user that no matching recipe was found, and ask if they want to search for another recipe.
