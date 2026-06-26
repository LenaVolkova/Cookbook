from app.agent import check_is_whole_recipe, determine_save_mode_deterministically


def test_check_is_whole_recipe():
    # Long recipe string (chicken noodle soup)
    recipe_str = (
        "Classic Chicken Noodle Soup"
        "Ingredients"
        "1 lb (450g) chicken breast"
        "1 tbsp olive oil"
        "1 medium onion, diced"
        "2 medium carrots, sliced"
        "2 stalks celery, sliced"
        "6 cups chicken broth"
        "1 tsp dried thyme"
        "1 cup egg noodles"
        "Salt and black pepper to taste"
        "Fresh parsley, chopped"
        "Instructions"
        "1. Sauté the vegetables"
        "Heat the olive oil in a large pot over medium heat. Add the onion, carrots, and celery. Cook for 5 minutes until soft."
        "2. Add broth and chicken"
        "Pour in the chicken broth and add the dried thyme. Place the chicken into the pot. Bring to a boil. Reduce heat, cover, and simmer for 15 minutes."
        "3. Shred chicken and cook noodles"
        "Remove the chicken from the pot. Shred the meat using two forks. Return the chicken to the pot. Add the egg noodles. Cook for 8-10 minutes until the noodles are tender."
        "4. Season and serve"
        "Stir in the fresh parsley. Season with salt and pepper to taste. Remove from heat and serve hot."
    )
    assert check_is_whole_recipe(recipe_str) is True

    # Simple chat message (not a recipe)
    assert check_is_whole_recipe("I want to save a recipe step-by-step") is False
    assert check_is_whole_recipe("Hello, how are you?") is False


def test_determine_save_mode_deterministically():
    # Ambiguous/generic save requests -> unknown
    assert determine_save_mode_deterministically("I want to save a recipe") == "unknown"
    assert determine_save_mode_deterministically("save a recipe") == "unknown"
    assert determine_save_mode_deterministically("save recipe") == "unknown"
    assert determine_save_mode_deterministically("new recipe") == "unknown"

    # Explicit step-by-step requests
    assert determine_save_mode_deterministically("step-by-step") == "step-by-step"
    assert determine_save_mode_deterministically("step by step") == "step-by-step"
    assert determine_save_mode_deterministically("interactively") == "step-by-step"

    # Explicit bulk/whole recipe requests
    assert (
        determine_save_mode_deterministically("Whole recipe in one message") == "bulk"
    )
    assert determine_save_mode_deterministically("bulk") == "bulk"
    assert determine_save_mode_deterministically("in bulk") == "bulk"

    # Other random phrases
    assert determine_save_mode_deterministically("Recommend dinner") is None
