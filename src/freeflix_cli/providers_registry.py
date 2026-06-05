from typing import Callable, List, Optional


class ProviderRegistry:
    def __init__(self):
        self.providers = []

    def register(
        self,
        name: str,
        handler: Callable,
        supported_languages: Optional[List[str]] = None,
        category: str = "anime",
    ):
        """
        Register a streaming provider.

        :param name: Display name of the provider (e.g. '🎌 Anime-Sama').
        :param handler: The function to execute when this provider is chosen.
        :param supported_languages: List of content languages ('fr', 'en', …)
            this source is relevant for. ``None`` means the source applies to
            every language and is always shown. The user's chosen content
            language (asked first on launch) decides which sources appear:
            picking English keeps every source tagged 'en', picking French
            keeps every source tagged 'fr'.
        :param category: Grouping key for the source menu — ``"anime"`` (anime
            / manga) or ``"movies"`` (films & series). The menu lists anime
            sources first, then films/series, under section headers.
        """
        self.providers.append(
            {
                "name": name,
                "handler": handler,
                "supported_languages": supported_languages,
                "category": category,
            }
        )

    def get_providers(self, target_language: Optional[str] = None) -> List[dict]:
        """
        Get the sources relevant to the chosen content language.

        A source is shown when its ``supported_languages`` is None (applies to
        all) or contains ``target_language``. None target returns everything.
        """
        if not target_language:
            return self.providers

        filtered = []
        for p in self.providers:
            if (
                p["supported_languages"] is None
                or target_language in p["supported_languages"]
            ):
                filtered.append(p)

        return filtered


# Global singleton instance
registry = ProviderRegistry()
