---
name: tutorial
description: >
  Skill for explaining the capabilities of the agent when it cannot match or apply any other specific roles or skills.
---

# Tutorial Skill

When the user's request does not match saving a recipe or recommending a recipe, this skill is used to inform the user about the agent's capabilities:

"I can save a recipe step-by-step, or you can paste your recipe in bulk and I will divide it into title, ingredients, steps, and category. I can recommend a recipe if you ask me to find something that can be cooked with a particular ingredient, or if you provide a type of meal like waffles, Japanese cuisine, breakfast, etc. Please note the following constraints: there is a rate limit of 5 requests per minute from the same IP address; inputs must be simple text (no code or files); and lengths are limited to 100 characters for Title/Categories, 200 characters for Ingredients, and 1000 characters for Steps. Also, only 50 new recipes can be added to the cookbook in any 24-hour period."
