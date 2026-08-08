from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .config_merge import deep_merge, load_yaml_if_exists
from .paths import ARCHETYPES_ROOT, DEFAULTS_ROOT, PRODUCTS_ROOT
from .simple_yaml import load_yaml


REQUIRED_PLUGIN_FILES = {
    "manifest.yaml",
}

@dataclass(frozen=True)
class ProductPlugin:
    category_id: str
    root: Path
    manifest: dict[str, Any]
    _merged_config: dict[str, Any] | None = field(default=None, compare=False, repr=False)

    @property
    def product_type(self) -> str:
        config = self.merged_config()
        return str(config.get("product_type") or config.get("amazon_product_type") or self.category_id).upper()

    @property
    def display_name(self) -> str:
        return str(self.merged_config().get("display_name") or self.category_id)

    def file(self, name: str) -> Path:
        return self.root / name

    def load_yaml(self, name: str) -> Any:
        if name == "manifest.yaml":
            return self.merged_config()
        return load_yaml(self.file(name))

    def merged_config(self) -> dict[str, Any]:
        if self._merged_config is not None:
            return self._merged_config
        if str(self.manifest.get("lifecycle") or "").strip().lower() == "unsupported":
            result = dict(self.manifest)
            object.__setattr__(self, "_merged_config", result)
            return result
        result = load_yaml_if_exists(DEFAULTS_ROOT / "product.yaml")
        archetype = str(self.manifest.get("archetype") or result.get("archetype") or "default").strip()
        if archetype and archetype != "default":
            result = deep_merge(result, load_yaml_if_exists(ARCHETYPES_ROOT / f"{archetype}.yaml"))
        result = deep_merge(result, self.manifest)
        object.__setattr__(self, "_merged_config", result)
        return result

    def load_extractors(self) -> Any:
        path = self.file("extractors.py")
        if path.exists():
            raise RuntimeError(
                f"Category extractor modules are retired: {path}. "
                "Use manifest.yaml extractors.product_specific_fields instead."
            )
        return _generic_extractors(self)

    def missing_files(self) -> list[str]:
        return sorted(name for name in REQUIRED_PLUGIN_FILES if not self.file(name).exists())

    def model_preferences(self) -> dict[str, Any]:
        prefs = self.merged_config().get("model_preferences")
        return prefs if isinstance(prefs, dict) else {}


def discover_plugins(products_root: Path = PRODUCTS_ROOT) -> dict[str, ProductPlugin]:
    plugins: dict[str, ProductPlugin] = {}
    if not products_root.exists():
        return plugins
    for root in sorted(path for path in products_root.iterdir() if path.is_dir()):
        manifest_path = root / "manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = load_yaml(manifest_path)
        if not isinstance(manifest, dict):
            raise ValueError(f"Plugin manifest must be a mapping: {manifest_path}")
        category_id = str(manifest.get("category_id") or root.name)
        plugins[category_id] = ProductPlugin(category_id=category_id, root=root, manifest=manifest)
    return plugins


def load_plugin(category_id: str, products_root: Path = PRODUCTS_ROOT) -> ProductPlugin:
    plugins = discover_plugins(products_root)
    if category_id not in plugins:
        available = ", ".join(sorted(plugins)) or "(none)"
        raise KeyError(f"Unknown product category '{category_id}'. Available: {available}")
    return plugins[category_id]


def _generic_extractors(plugin: ProductPlugin) -> Any:
    from products import generic_extractors

    config = plugin.merged_config()
    extractor_cfg = config.get("extractors")
    extractor_cfg = extractor_cfg if isinstance(extractor_cfg, dict) else {}
    field_cfg = extractor_cfg.get("product_specific_fields") or config.get("product_specific_fields") or {}
    fields: dict[str, tuple[str, ...]] = {}
    if isinstance(field_cfg, dict):
        for key, labels in field_cfg.items():
            if isinstance(labels, list):
                fields[str(key)] = tuple(str(label) for label in labels)
            elif labels:
                fields[str(key)] = (str(labels),)
    dimensions = config.get("variation_dimensions")
    variation_dimensions = [str(item) for item in dimensions] if isinstance(dimensions, list) else ["color", "size", "style"]

    def extract_specs(raw: dict[str, Any]) -> dict[str, Any]:
        return generic_extractors.extract_specs_by_fields(raw, fields)

    def product_specific(raw: dict[str, Any]) -> dict[str, Any]:
        specs = dict(extract_specs(raw))
        for output_key, source_key in _extractor_aliases(extractor_cfg).items():
            if output_key not in specs and specs.get(source_key) not in (None, "", []):
                specs[output_key] = specs[source_key]
        return specs

    def extract_variations(raw: dict[str, Any], seed_asin: str) -> dict[str, Any]:
        return generic_extractors.extract_variations(raw, seed_asin, variation_dimensions)

    return SimpleNamespace(
        extract_specs=extract_specs,
        product_specific=product_specific,
        extract_variations=extract_variations,
        image_urls=generic_extractors.image_urls,
    )


def _extractor_aliases(extractor_cfg: dict[str, Any]) -> dict[str, str]:
    aliases = extractor_cfg.get("aliases")
    if not isinstance(aliases, dict):
        return {}
    return {str(key): str(value) for key, value in aliases.items() if key and value}
