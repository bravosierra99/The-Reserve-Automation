"""Tests for ingredient data models, tree building, and utility functions."""


from reserve_automation.core.ingredient import (
    Ingredient,
    build_ingredient_tree,
    flatten_tree,
    get_descendants,
)


class TestIngredientModel:
    """Test Ingredient model basics."""

    def test_minimal_ingredient(self):
        """Create ingredient with just a name."""
        ing = Ingredient(name="Vodka")
        assert ing.name == "Vodka"
        assert ing.parent is None
        assert ing.is_product is False
        assert ing.children == []
        assert ing.ancestors == []

    def test_product_ingredient(self):
        """Create ingredient with product fields."""
        ing = Ingredient(
            name="Svedka Vanilla Vodka",
            parent="Vanilla Vodka",
            cost=12.99,
            volume_ml=750,
            abv=35.0,
        )
        ing.compute_is_product()
        assert ing.is_product is True
        assert ing.cost == 12.99
        assert ing.volume_ml == 750
        assert ing.abv == 35.0

    def test_is_product_false_when_no_product_fields(self):
        """General categories have is_product=False."""
        ing = Ingredient(name="Spirit")
        ing.compute_is_product()
        assert ing.is_product is False

    def test_is_product_true_with_single_field(self):
        """Setting any one product field makes is_product True."""
        ing = Ingredient(name="Test", cost=5.0)
        ing.compute_is_product()
        assert ing.is_product is True

        ing2 = Ingredient(name="Test2", volume_ml=750)
        ing2.compute_is_product()
        assert ing2.is_product is True

        ing3 = Ingredient(name="Test3", abv=40.0)
        ing3.compute_is_product()
        assert ing3.is_product is True

    def test_to_obsidian_dict(self):
        """Obsidian dict contains expected fields."""
        ing = Ingredient(
            name="Svedka",
            parent="Vodka",
            cost=12.99,
        )
        d = ing.to_obsidian_dict()
        assert d["name"] == "Svedka"
        assert d["parent"] == "Vodka"
        assert d["cost"] == 12.99
        assert d["volume_ml"] is None

    def test_vault_path_excluded_from_serialization(self):
        """vault_path should be excluded from model serialization."""
        ing = Ingredient(name="Test", vault_path="2_Ingredients/Test")
        d = ing.model_dump()
        assert "vault_path" not in d


class TestBuildIngredientTree:
    """Test tree building from flat ingredient lists."""

    def _make_ingredients(self):
        """Create a sample flat ingredient list."""
        return [
            Ingredient(name="Spirit"),
            Ingredient(name="Vodka", parent="Spirit"),
            Ingredient(name="Gin", parent="Spirit"),
            Ingredient(name="Flavored Vodka", parent="Vodka"),
            Ingredient(name="Mixer"),
            Ingredient(name="Tonic Water", parent="Mixer"),
        ]

    def test_builds_roots(self):
        """Root nodes (no parent) are returned at top level."""
        ingredients = self._make_ingredients()
        roots = build_ingredient_tree(ingredients)
        root_names = [r.name for r in roots]
        assert "Spirit" in root_names
        assert "Mixer" in root_names

    def test_children_assigned(self):
        """Children are assigned to correct parents."""
        ingredients = self._make_ingredients()
        roots = build_ingredient_tree(ingredients)

        spirit = next(r for r in roots if r.name == "Spirit")
        child_names = [c.name for c in spirit.children]
        assert "Vodka" in child_names
        assert "Gin" in child_names

    def test_nested_children(self):
        """Multi-level nesting works."""
        ingredients = self._make_ingredients()
        roots = build_ingredient_tree(ingredients)

        spirit = next(r for r in roots if r.name == "Spirit")
        vodka = next(c for c in spirit.children if c.name == "Vodka")
        assert len(vodka.children) == 1
        assert vodka.children[0].name == "Flavored Vodka"

    def test_ancestors_computed(self):
        """Ancestor paths are computed correctly."""
        ingredients = self._make_ingredients()
        roots = build_ingredient_tree(ingredients)

        spirit = next(r for r in roots if r.name == "Spirit")
        assert spirit.ancestors == []

        vodka = next(c for c in spirit.children if c.name == "Vodka")
        assert vodka.ancestors == ["Spirit"]

        flavored = vodka.children[0]
        assert flavored.ancestors == ["Spirit", "Vodka"]

    def test_orphan_treated_as_root(self):
        """Ingredient with unknown parent is treated as root."""
        ingredients = [
            Ingredient(name="Orphan", parent="NonExistent"),
        ]
        roots = build_ingredient_tree(ingredients)
        assert len(roots) == 1
        assert roots[0].name == "Orphan"

    def test_empty_list(self):
        """Empty list produces empty tree."""
        roots = build_ingredient_tree([])
        assert roots == []


class TestFlattenTree:
    """Test tree flattening."""

    def test_flatten_preserves_all_nodes(self):
        """Flattening a tree preserves all nodes."""
        ingredients = [
            Ingredient(name="Spirit"),
            Ingredient(name="Vodka", parent="Spirit"),
            Ingredient(name="Gin", parent="Spirit"),
            Ingredient(name="Mixer"),
        ]
        roots = build_ingredient_tree(ingredients)
        flat = flatten_tree(roots)
        flat_names = [f.name for f in flat]
        assert len(flat) == 4
        assert "Spirit" in flat_names
        assert "Vodka" in flat_names
        assert "Gin" in flat_names
        assert "Mixer" in flat_names

    def test_depth_first_order(self):
        """Flatten returns depth-first order."""
        ingredients = [
            Ingredient(name="A"),
            Ingredient(name="B", parent="A"),
            Ingredient(name="C", parent="B"),
            Ingredient(name="D", parent="A"),
        ]
        roots = build_ingredient_tree(ingredients)
        flat = flatten_tree(roots)
        names = [f.name for f in flat]
        assert names == ["A", "B", "C", "D"]


class TestGetDescendants:
    """Test descendant retrieval."""

    def test_get_all_descendants(self):
        """Gets all descendants of a node."""
        ingredients = [
            Ingredient(name="Spirit"),
            Ingredient(name="Vodka", parent="Spirit"),
            Ingredient(name="Gin", parent="Spirit"),
            Ingredient(name="Flavored Vodka", parent="Vodka"),
        ]
        roots = build_ingredient_tree(ingredients)
        spirit = roots[0]

        descendants = get_descendants(spirit)
        desc_names = [d.name for d in descendants]
        assert "Vodka" in desc_names
        assert "Gin" in desc_names
        assert "Flavored Vodka" in desc_names
        assert "Spirit" not in desc_names  # excludes self

    def test_leaf_has_no_descendants(self):
        """Leaf node has no descendants."""
        ingredients = [
            Ingredient(name="Spirit"),
            Ingredient(name="Vodka", parent="Spirit"),
        ]
        roots = build_ingredient_tree(ingredients)
        vodka = roots[0].children[0]

        descendants = get_descendants(vodka)
        assert descendants == []
